"""Trading endpoints: POST /trade_intent and POST /execute."""

from __future__ import annotations

import logging
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
from backend.db.models import Fill, Order
from backend.db.session import SessionLocal
from backend.services.audit_service import record_audit_event
from backend.services.risk_manager import RiskConfig, RiskManager
from backend.trading_engine.account_state import ValidationRules
from backend.trading_engine.angel_adapter import get_adapter
from backend.trading_engine.execution_engine import AccountStateExecutionEngine

router = APIRouter(tags=["trading"])
logger = logging.getLogger(__name__)

_intents: dict[str, dict] = {}


def _get_adapter():
    """Lazy adapter accessor – avoids crash on import if credentials are bad."""
    global _adapter_instance
    try:
        return _adapter_instance
    except NameError:
        _adapter_instance = get_adapter()
        return _adapter_instance


def _get_execution_engine() -> AccountStateExecutionEngine:
    global _execution_engine
    try:
        return _execution_engine
    except NameError:
        rules = ValidationRules(
            allow_pyramiding=False,
            max_position_size_pct=RiskConfig().max_position_pct,
            max_portfolio_exposure_pct=RiskConfig().max_portfolio_risk_pct,
            max_open_positions=RiskConfig().max_open_positions,
        )
        _execution_engine = AccountStateExecutionEngine(validation_rules=rules)
        return _execution_engine


def _build_route_risk_manager() -> RiskManager:
    return RiskManager(capital=0.0, config=RiskConfig())


def _require_auth(authorization: str = Header(None)):
    """Simple bearer-token guard for protected endpoints."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")
    return authorization.split(" ", 1)[1]


def _load_current_price(adapter, intent: dict) -> float:
    if intent.get("limit_price") is not None:
        return float(intent["limit_price"])
    ltp = adapter.get_ltp(intent["ticker"])
    if ltp and ltp.get("ltp") not in (None, "", 0, 0.0):
        return float(ltp["ltp"])
    raise HTTPException(
        status_code=503,
        detail=f"Live price unavailable for {intent['ticker']}; trade execution aborted.",
    )


def _persist_execution(
    *,
    execution_id: str,
    intent_id: str,
    intent: dict,
    result: dict,
    status: str,
) -> None:
    db = SessionLocal()
    try:
        order = Order(
            id=execution_id,
            intent_id=intent_id,
            ticker=intent["ticker"],
            side=intent["side"],
            quantity=intent["quantity"],
            order_type=intent["order_type"],
            limit_price=intent.get("limit_price"),
            status=status,
            option_type=intent.get("option_type"),
            strike=intent.get("strike"),
            expiry=intent.get("expiry"),
            strategy=intent.get("strategy"),
        )
        db.add(order)
        if status in {"filled", "placed"}:
            fill = Fill(
                order_id=execution_id,
                ticker=intent["ticker"],
                side=intent["side"],
                quantity=intent["quantity"],
                filled_price=float(result.get("filled_price") or intent.get("limit_price") or 0.0),
                slippage=float(result.get("slippage") or 0.0),
                latency_ms=float(result.get("latency_ms") or 0.0),
                commission=0,
                option_type=intent.get("option_type"),
                strike=intent.get("strike"),
                expiry=intent.get("expiry"),
                strategy=intent.get("strategy"),
            )
            db.add(fill)
        record_audit_event(
            "ORDER_EXECUTION_ATTEMPT",
            entity_type="order",
            entity_id=execution_id,
            data={
                "intent_id": intent_id,
                "ticker": intent["ticker"],
                "side": intent["side"],
                "quantity": intent["quantity"],
                "status": status,
                "broker_result": result,
            },
            source="trade_router",
            db=db,
            raise_on_error=True,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to persist execution %s", execution_id)
        raise RuntimeError("execution_persistence_failed") from exc
    finally:
        db.close()


@router.post("/trade_intent", response_model=TradeIntentResponse, status_code=201)
async def trade_intent(req: TradeIntentRequest):
    if req.order_type.value == "limit" and req.limit_price is None:
        raise HTTPException(status_code=400, detail="limit_price required for limit orders")

    intent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    estimated_price = req.limit_price
    if estimated_price is None:
        try:
            estimated_price = float((_get_adapter().get_ltp(req.ticker.upper()) or {}).get("ltp") or 0.0)
        except Exception:
            estimated_price = 0.0
    estimated_cost = req.quantity * float(estimated_price or 0.0)

    _intents[intent_id] = {
        "ticker": req.ticker.upper(),
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
    record_audit_event(
        "TRADE_INTENT_CREATED",
        entity_type="intent",
        entity_id=intent_id,
        data=_intents[intent_id],
        source="trade_router",
    )

    return TradeIntentResponse(
        intent_id=uuid.UUID(intent_id),
        ticker=req.ticker.upper(),
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
    del token
    intent_id = str(req.intent_id)
    if intent_id not in _intents:
        raise HTTPException(status_code=404, detail="Trade intent not found")

    intent = _intents[intent_id]
    adapter = _get_adapter()
    current_price = _load_current_price(adapter, intent)
    outcome = _get_execution_engine().execute_with_adapter(
        adapter=adapter,
        order_intent={
            "ticker": intent["ticker"],
            "side": intent["side"],
            "quantity": intent["quantity"],
            "order_type": intent["order_type"],
            "limit_price": intent.get("limit_price"),
            "option_type": intent.get("option_type"),
            "strike": intent.get("strike"),
            "expiry": intent.get("expiry"),
            "strategy": intent.get("strategy"),
        },
        current_price=current_price,
        risk_manager=_build_route_risk_manager(),
    )

    if not outcome.accepted:
        record_audit_event(
            "ORDER_EXECUTION_REJECTED",
            entity_type="intent",
            entity_id=intent_id,
            data={
                "ticker": intent["ticker"],
                "side": intent["side"],
                "quantity": intent["quantity"],
                "reason": outcome.reason,
            },
            source="trade_router",
        )
        raise HTTPException(status_code=422, detail=outcome.reason or "Order rejected")

    result = outcome.broker_result or {}
    execution_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    status = str(result.get("status") or "placed").lower()
    _persist_execution(
        execution_id=execution_id,
        intent_id=intent_id,
        intent=intent,
        result=result,
        status=status,
    )
    intent["status"] = status

    filled_price = float(result.get("filled_price") or current_price)
    return ExecuteResponse(
        execution_id=uuid.UUID(execution_id),
        intent_id=req.intent_id,
        ticker=intent["ticker"],
        side=OrderSide(intent["side"]),
        quantity=intent["quantity"],
        filled_price=filled_price,
        total_value=filled_price * intent["quantity"],
        slippage=float(result.get("slippage") or 0.0),
        latency_ms=float(result.get("latency_ms") or 0.0),
        status=status,
        option_type=OptionType(intent["option_type"]) if intent.get("option_type") else None,
        strike=intent.get("strike"),
        expiry=intent.get("expiry"),
        strategy=OptionStrategy(intent["strategy"]) if intent.get("strategy") else None,
        executed_at=now,
    )
