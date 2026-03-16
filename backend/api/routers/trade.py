"""Trading endpoints: POST /trade_intent and POST /execute."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Header

from backend.api.schemas import (
    ExecuteRequest,
    ExecuteResponse,
    OptionStrategy,
    OptionType,
    OrderSide,
    TradeIntentRequest,
    TradeIntentResponse,
)
from backend.db.models import AuditLog, Fill, Order
from backend.db.session import SessionLocal
from backend.trading_engine.angel_adapter import get_adapter

router = APIRouter(tags=["trading"])

# In-memory intent store
_intents: dict[str, dict] = {}


def _get_adapter():
    """Lazy adapter accessor – avoids crash on import if credentials are bad."""
    global _adapter_instance
    try:
        return _adapter_instance
    except NameError:
        _adapter_instance = get_adapter()
        return _adapter_instance


def _require_auth(authorization: str = Header(None)):
    """Simple bearer-token guard for protected endpoints."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")
    return authorization.split(" ", 1)[1]


@router.post("/trade_intent", response_model=TradeIntentResponse, status_code=201)
async def trade_intent(req: TradeIntentRequest):
    # Validate limit-price rule
    if req.order_type.value == "limit" and req.limit_price is None:
        raise HTTPException(status_code=400, detail="limit_price required for limit orders")

    intent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    estimated_cost = req.quantity * (req.limit_price or 100.0)  # placeholder price

    _intents[intent_id] = {
        "ticker": req.ticker,
        "side": req.side.value,
        "quantity": req.quantity,
        "order_type": req.order_type.value,
        "limit_price": req.limit_price,
        "estimated_cost": estimated_cost,
        "status": "pending",
        "option_type": req.option_type.value if req.option_type else None,
        "strike": req.strike,
        "expiry": req.expiry,
        "strategy": req.strategy.value if req.strategy else None,
        "created_at": now,
    }

    return TradeIntentResponse(
        intent_id=uuid.UUID(intent_id),
        ticker=req.ticker,
        side=req.side,
        quantity=req.quantity,
        order_type=req.order_type,
        limit_price=req.limit_price,
        estimated_cost=estimated_cost,
        status="pending",
        option_type=req.option_type,
        strike=req.strike,
        expiry=req.expiry,
        strategy=req.strategy,
        created_at=now,
    )


@router.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest, token: str = Depends(_require_auth)):
    intent_id = str(req.intent_id)

    if intent_id not in _intents:
        raise HTTPException(status_code=404, detail="Trade intent not found")

    intent = _intents[intent_id]

    # Place order via adapter (pass option fields)
    result = _get_adapter().place_order({
        "ticker": intent["ticker"],
        "side": intent["side"],
        "quantity": intent["quantity"],
        "order_type": intent["order_type"],
        "current_price": intent.get("limit_price") or 100.0,
        "option_type": intent.get("option_type"),
        "strike": intent.get("strike"),
        "expiry": intent.get("expiry"),
        "strategy": intent.get("strategy"),
    })

    if result.get("status") != "filled":
        raise HTTPException(status_code=500, detail="Order execution failed")

    execution_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # Persist to DB (best-effort; skip if DB not available)
    try:
        db = SessionLocal()
        order = Order(
            id=str(execution_id),
            intent_id=intent_id,
            ticker=intent["ticker"],
            side=intent["side"],
            quantity=intent["quantity"],
            order_type=intent["order_type"],
            limit_price=intent.get("limit_price"),
            status="filled",
            option_type=intent.get("option_type"),
            strike=intent.get("strike"),
            expiry=intent.get("expiry"),
            strategy=intent.get("strategy"),
        )
        fill = Fill(
            order_id=str(execution_id),
            ticker=intent["ticker"],
            side=intent["side"],
            quantity=intent["quantity"],
            filled_price=result["filled_price"],
            slippage=result.get("slippage", 0),
            latency_ms=result.get("latency_ms", 0),
            commission=0,
            option_type=intent.get("option_type"),
            strike=intent.get("strike"),
            expiry=intent.get("expiry"),
            strategy=intent.get("strategy"),
        )
        audit = AuditLog(
            event="ORDER_EXECUTED",
            entity_type="order",
            entity_id=str(execution_id),
            data=json.dumps(result),
        )
        db.add_all([order, fill, audit])
        db.commit()
        db.close()
    except Exception:
        pass  # graceful degradation if DB not configured

    intent["status"] = "filled"

    return ExecuteResponse(
        execution_id=execution_id,
        intent_id=req.intent_id,
        ticker=intent["ticker"],
        side=OrderSide(intent["side"]),
        quantity=intent["quantity"],
        filled_price=result["filled_price"],
        total_value=result["filled_price"] * intent["quantity"],
        slippage=result.get("slippage", 0),
        latency_ms=result.get("latency_ms", 0),
        status="filled",
        option_type=OptionType(intent["option_type"]) if intent.get("option_type") else None,
        strike=intent.get("strike"),
        expiry=intent.get("expiry"),
        strategy=OptionStrategy(intent["strategy"]) if intent.get("strategy") else None,
        executed_at=now,
    )
