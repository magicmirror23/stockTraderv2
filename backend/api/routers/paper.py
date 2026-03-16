"""Paper trading API routes.

Endpoints for paper account management, order placement, and replay.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from backend.api.schemas import (
    EquityPoint,
    PaperAccountCreateRequest,
    PaperAccountResponse,
    PaperOrderIntentRequest,
    PaperReplayRequest,
)
from backend.paper_trading.paper_account import PaperAccountManager
from backend.paper_trading.paper_executor import PaperExecutor
from backend.paper_trading.paper_replayer import PaperReplayer

router = APIRouter(tags=["paper-trading"])

# Singleton instances
_account_manager = PaperAccountManager()
_executor = PaperExecutor()
_replayer = PaperReplayer(executor=_executor)


@router.post("/paper/accounts", response_model=PaperAccountResponse, status_code=201)
async def create_paper_account(req: PaperAccountCreateRequest):
    account = _account_manager.create_account(
        initial_cash=req.initial_cash, label=req.label
    )
    return PaperAccountResponse(
        account_id=account.account_id,
        cash=account.cash,
        equity=account.equity,
        positions={k: v.quantity for k, v in account.positions.items()},
        created_at=account.created_at,
    )


@router.get("/paper/accounts")
async def list_paper_accounts():
    accounts = _account_manager.list_accounts()
    return [
        {
            "account_id": a.account_id,
            "cash": a.cash,
            "equity": a.equity,
            "label": a.label,
            "created_at": a.created_at.isoformat(),
        }
        for a in accounts
    ]


@router.get("/paper/{account_id}/equity", response_model=list[EquityPoint])
async def get_equity_curve(account_id: str):
    account = _account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return [EquityPoint(**pt) for pt in account.equity_curve]


@router.get("/paper/{account_id}/metrics")
async def get_account_metrics(account_id: str):
    account = _account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    trades = account.trade_log
    if not trades:
        return {
            "sharpe": None, "sortino": None, "max_drawdown": None,
            "win_rate": None, "total_trades": 0, "net_pnl": 0,
        }

    pnls = [t.get("pnl", 0) for t in trades]
    import numpy as np
    pnl_arr = np.array(pnls)
    wins = sum(1 for p in pnls if p > 0)
    net_pnl = float(pnl_arr.sum())

    # Simple Sharpe approximation
    if len(pnl_arr) > 1 and pnl_arr.std() > 0:
        sharpe = float(pnl_arr.mean() / pnl_arr.std() * np.sqrt(252))
        downside = pnl_arr[pnl_arr < 0]
        if len(downside) > 0 and downside.std() > 0:
            sortino = float(pnl_arr.mean() / downside.std() * np.sqrt(252))
        else:
            sortino = None
    else:
        sharpe = None
        sortino = None

    # Drawdown from equity curve
    max_drawdown = None
    if account.equity_curve:
        equities = [pt["equity"] for pt in account.equity_curve]
        peak = equities[0]
        max_dd = 0
        for eq in equities:
            peak = max(peak, eq)
            dd = (peak - eq) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        max_drawdown = max_dd

    return {
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "win_rate": wins / len(trades) if trades else None,
        "total_trades": len(trades),
        "net_pnl": net_pnl,
    }


@router.post("/paper/{account_id}/order_intent")
async def paper_order_intent(account_id: str, req: PaperOrderIntentRequest):
    account = _account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Get market price
    from backend.services.price_feed import PriceFeed
    feed = PriceFeed()
    tick = feed.get_latest_price(req.ticker)
    if not tick:
        raise HTTPException(status_code=404, detail=f"No price data for {req.ticker}")

    fill = _executor.execute_order(
        account=account,
        ticker=req.ticker,
        side=req.side.value,
        quantity=req.quantity,
        market_price=tick.price,
        option_type=req.option_type.value if req.option_type else None,
        strike=req.strike,
        expiry=req.expiry,
    )

    if not fill:
        raise HTTPException(status_code=422, detail="Order not filled")

    return {
        "ticker": fill.ticker,
        "side": fill.side,
        "quantity": fill.quantity,
        "fill_price": fill.fill_price,
        "slippage": fill.slippage,
        "status": fill.status,
        "timestamp": fill.timestamp.isoformat(),
    }


@router.post("/paper/{account_id}/replay")
async def replay_day(account_id: str, req: PaperReplayRequest):
    account = _account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    result = _replayer.replay_day(account, req.date)
    return result
