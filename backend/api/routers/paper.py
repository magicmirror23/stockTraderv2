"""Paper trading API routes."""

from __future__ import annotations

from typing import Any

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
from backend.services.risk_manager import RiskConfig, RiskManager
from backend.trading_engine.account_state import ValidationRules, fetch_paper_account_state
from backend.trading_engine.execution_engine import AccountStateExecutionEngine

router = APIRouter(tags=["paper-trading"])

_account_manager = PaperAccountManager()
_executor = PaperExecutor()
_replayer = PaperReplayer(executor=_executor)


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


def _paper_risk_manager(account) -> RiskManager:
    manager = RiskManager(capital=max(account.equity, account.cash, 0.0), config=RiskConfig())
    manager.daily_pnl = float(account.realized_pnl)
    manager.record_equity_snapshot(float(account.equity))
    manager.sync_account_state(fetch_paper_account_state(account))
    return manager


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

    snapshot = _portfolio_snapshot(account)
    trades = [trade for trade in account.trade_log if trade.get("side") == "sell"]
    if not trades:
        return {
            "sharpe": None, "sortino": None, "max_drawdown": None,
            "win_rate": None, "total_trades": 0, "net_pnl": 0,
            "profit_factor": None,
            "avg_win": None,
            "avg_loss": None,
            "best_trade": None,
            "worst_trade": None,
            "realized_pnl": round(account.realized_pnl, 2),
            "unrealized_pnl": round(snapshot["unrealized_pnl"], 2),
            "starting_cash": round(account.initial_cash, 2),
            "current_cash": round(account.cash, 2),
            "current_equity": round(snapshot["current_equity"], 2),
            "total_return_pct": round(snapshot["total_return_pct"], 4),
            "cash_utilization_pct": round(snapshot["cash_utilization_pct"], 4),
            "open_positions": snapshot["open_positions"],
            "holdings": snapshot["holdings"],
        }

    pnls = [trade.get("realized_pnl", trade.get("pnl", 0)) for trade in trades]
    import numpy as np

    pnl_arr = np.array(pnls)
    wins = sum(1 for pnl in pnls if pnl > 0)
    net_pnl = float(pnl_arr.sum())
    positive_sum = float(sum(pnl for pnl in pnls if pnl > 0))
    negative_sum = float(sum(pnl for pnl in pnls if pnl < 0))
    avg_win = float(np.mean([pnl for pnl in pnls if pnl > 0])) if any(pnl > 0 for pnl in pnls) else None
    avg_loss = float(np.mean([pnl for pnl in pnls if pnl < 0])) if any(pnl < 0 for pnl in pnls) else None
    profit_factor = None
    if negative_sum < 0:
        profit_factor = positive_sum / abs(negative_sum)

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

    max_drawdown = None
    if account.equity_curve:
        equities = [pt["equity"] for pt in account.equity_curve]
        peak = equities[0]
        max_dd = 0
        for equity in equities:
            peak = max(peak, equity)
            drawdown = (peak - equity) / peak if peak > 0 else 0
            max_dd = max(max_dd, drawdown)
        max_drawdown = max_dd

    return {
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "win_rate": wins / len(trades) if trades else None,
        "total_trades": len(trades),
        "net_pnl": net_pnl,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "best_trade": float(max(pnls)) if pnls else None,
        "worst_trade": float(min(pnls)) if pnls else None,
        "realized_pnl": round(account.realized_pnl, 2),
        "unrealized_pnl": round(snapshot["unrealized_pnl"], 2),
        "starting_cash": round(account.initial_cash, 2),
        "current_cash": round(account.cash, 2),
        "current_equity": round(snapshot["current_equity"], 2),
        "total_return_pct": round(snapshot["total_return_pct"], 4),
        "cash_utilization_pct": round(snapshot["cash_utilization_pct"], 4),
        "open_positions": snapshot["open_positions"],
        "holdings": snapshot["holdings"],
    }


@router.post("/paper/{account_id}/order_intent")
async def paper_order_intent(account_id: str, req: PaperOrderIntentRequest):
    account = _account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    from backend.services.price_feed import PriceFeed

    feed = PriceFeed()
    tick = feed.get_latest_price(req.ticker)
    if not tick:
        raise HTTPException(status_code=404, detail=f"No price data for {req.ticker}")

    before_state, validation, _risk_decision = _get_execution_engine().validate_paper_order(
        account=account,
        order_intent={
            "ticker": req.ticker.upper(),
            "side": req.side.value,
            "quantity": req.quantity,
            "option_type": req.option_type.value if req.option_type else None,
            "strike": req.strike,
            "expiry": req.expiry,
        },
        current_price=tick.price,
        risk_manager=_paper_risk_manager(account),
    )
    if not validation.allowed:
        raise HTTPException(status_code=422, detail=validation.reason)

    fill = _executor.execute_order(
        account=account,
        ticker=req.ticker.upper(),
        side=req.side.value,
        quantity=req.quantity,
        market_price=tick.price,
        option_type=req.option_type.value if req.option_type else None,
        strike=req.strike,
        expiry=req.expiry,
    )

    if not fill:
        raise HTTPException(
            status_code=422,
            detail=_executor.last_rejection_reason or "Order not filled",
        )

    after_state = fetch_paper_account_state(account)
    return {
        "ticker": fill.ticker,
        "side": fill.side,
        "quantity": fill.quantity,
        "fill_price": fill.fill_price,
        "slippage": fill.slippage,
        "commission": fill.commission,
        "status": fill.status,
        "timestamp": fill.timestamp.isoformat(),
        "account_state_before": {
            "available_cash": before_state.available_cash,
            "buying_power": before_state.buying_power,
            "total_equity": before_state.total_equity,
            "holdings": {
                key: {"quantity": position.quantity, "avg_price": position.average_price}
                for key, position in before_state.combined_positions().items()
            },
        },
        "account_state_after": {
            "available_cash": after_state.available_cash,
            "buying_power": after_state.buying_power,
            "total_equity": after_state.total_equity,
            "holdings": {
                key: {"quantity": position.quantity, "avg_price": position.average_price}
                for key, position in after_state.combined_positions().items()
            },
        },
    }


@router.post("/paper/{account_id}/replay")
async def replay_day(account_id: str, req: PaperReplayRequest):
    account = _account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    result = _replayer.replay_day(account, req.date)
    return result


def _portfolio_snapshot(account) -> dict[str, Any]:
    from backend.services.price_feed import PriceFeed

    feed = PriceFeed()
    holdings: list[dict[str, Any]] = []
    market_value_total = 0.0
    unrealized_pnl = 0.0

    for position in account.positions.values():
        latest = feed.get_latest_price(position.ticker)
        last_price = float(getattr(latest, "price", position.avg_price) or position.avg_price)
        cost_basis = position.quantity * position.avg_price
        market_value = position.quantity * last_price
        pnl = market_value - cost_basis
        market_value_total += market_value
        unrealized_pnl += pnl
        holdings.append(
            {
                "ticker": position.ticker,
                "quantity": position.quantity,
                "avg_price": round(position.avg_price, 2),
                "last_price": round(last_price, 2),
                "cost_basis": round(cost_basis, 2),
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(pnl, 2),
                "weight_pct": 0.0,
            }
        )

    current_equity = account.cash + market_value_total
    for holding in holdings:
        holding["weight_pct"] = round(
            (holding["market_value"] / current_equity) if current_equity > 0 else 0.0,
            4,
        )

    return {
        "current_equity": current_equity,
        "unrealized_pnl": unrealized_pnl,
        "cash_utilization_pct": (market_value_total / current_equity) if current_equity > 0 else 0.0,
        "total_return_pct": ((current_equity - account.initial_cash) / account.initial_cash) if account.initial_cash > 0 else 0.0,
        "open_positions": len(account.positions),
        "holdings": holdings,
    }
