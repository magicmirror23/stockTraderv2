from __future__ import annotations

from backend.services.risk_manager import RiskConfig, RiskManager
from backend.trading_engine.account_state import AccountState, HoldingState


def _state(
    *,
    cash: float = 100000.0,
    total_equity: float | None = None,
    holdings: dict[str, HoldingState] | None = None,
) -> AccountState:
    normalized_holdings = holdings or {}
    equity = total_equity if total_equity is not None else cash + sum(position.exposure for position in normalized_holdings.values())
    return AccountState(
        account_type="paper",
        available_cash=cash,
        buying_power=cash,
        total_equity=equity,
        holdings=normalized_holdings,
        open_positions={},
        open_orders=[],
    )


def test_size_position_respects_max_position_budget():
    manager = RiskManager(
        capital=100000.0,
        config=RiskConfig(max_position_pct=0.10, max_symbol_exposure_pct=0.20, max_portfolio_risk_pct=0.80),
    )
    state = _state(cash=100000.0, total_equity=100000.0)

    quantity = manager.size_position(price=100.0, account_state=state, stop_loss_pct=0.02, signal_strength=1.0)

    assert quantity == 100


def test_validate_order_rejects_symbol_exposure_limit():
    manager = RiskManager(
        capital=100000.0,
        config=RiskConfig(max_position_pct=0.15, max_symbol_exposure_pct=0.20, max_portfolio_risk_pct=0.90),
    )
    state = _state(
        cash=70000.0,
        total_equity=100000.0,
        holdings={"RELIANCE": HoldingState(ticker="RELIANCE", quantity=150, average_price=100.0)},
    )

    decision = manager.validate_order(
        {"ticker": "RELIANCE", "side": "buy", "quantity": 60, "signal_strength": 1.0},
        state,
        current_price=100.0,
        expected_return_pct=0.08,
        stop_loss_pct=0.02,
    )

    assert decision.allowed is False
    assert decision.code == "symbol_exposure_limit"


def test_validate_order_rejects_daily_loss_limit():
    manager = RiskManager(capital=100000.0, config=RiskConfig(max_daily_loss=2000.0, max_daily_loss_pct=0.05))
    manager.daily_pnl = -2500.0
    state = _state(cash=100000.0, total_equity=100000.0)

    decision = manager.validate_order(
        {"ticker": "TCS", "side": "buy", "quantity": 10, "signal_strength": 1.0},
        state,
        current_price=100.0,
        expected_return_pct=0.06,
        stop_loss_pct=0.02,
    )

    assert decision.allowed is False
    assert decision.code == "daily_loss_limit"


def test_validate_order_rejects_drawdown_limit():
    manager = RiskManager(capital=100000.0, config=RiskConfig(max_drawdown_pct=0.10))
    manager.record_equity_snapshot(100000.0)
    manager.record_equity_snapshot(86000.0)
    state = _state(cash=86000.0, total_equity=86000.0)

    decision = manager.validate_order(
        {"ticker": "INFY", "side": "buy", "quantity": 5, "signal_strength": 1.0},
        state,
        current_price=1000.0,
        expected_return_pct=0.08,
        stop_loss_pct=0.02,
    )

    assert decision.allowed is False
    assert decision.code == "drawdown_limit"


def test_validate_order_rejects_cash_buffer_breach():
    manager = RiskManager(
        capital=100000.0,
        config=RiskConfig(
            max_position_pct=0.20,
            max_symbol_exposure_pct=0.50,
            max_portfolio_risk_pct=0.90,
            min_cash_buffer_pct=0.10,
        ),
    )
    state = _state(cash=12000.0, total_equity=100000.0)

    decision = manager.validate_order(
        {"ticker": "ICICIBANK", "side": "buy", "quantity": 50, "signal_strength": 1.0},
        state,
        current_price=100.0,
        expected_return_pct=0.07,
        stop_loss_pct=0.02,
    )

    assert decision.allowed is False
    assert decision.code == "cash_buffer_limit"
