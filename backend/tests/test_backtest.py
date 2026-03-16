"""Tests for backtester and simulator."""

import numpy as np
import pandas as pd

from backend.prediction_engine.backtest.backtester import Backtester, ExecutionConfig
from backend.trading_engine.simulator import PaperSimulator, OrderIntent


# ---------------------------------------------------------------------------
# Backtester
# ---------------------------------------------------------------------------

def test_backtester_basic():
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=10, freq="B")

    predictions = pd.DataFrame({
        "date": dates,
        "ticker": "TEST",
        "action": ["buy"] * 5 + ["sell"] * 5,
        "confidence": 0.8,
    })
    prices = pd.DataFrame({
        "Date": dates,
        "ticker": "TEST",
        "Close": np.linspace(100, 110, 10),
    })

    bt = Backtester(ExecutionConfig(slippage_pct=0, commission_per_trade=0, fill_probability=1.0))
    result = bt.run(predictions, prices, initial_capital=100_000.0)

    assert result.status == "completed"
    assert result.initial_capital == 100_000.0
    assert result.final_value > 0
    assert len(result.trades) > 0


def test_backtester_metrics():
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=20, freq="B")

    predictions = pd.DataFrame({
        "date": dates,
        "ticker": "TEST",
        "action": (["buy"] * 10 + ["sell"] * 10),
        "confidence": 0.8,
    })
    prices = pd.DataFrame({
        "Date": dates,
        "ticker": "TEST",
        "Close": np.linspace(100, 120, 20),
    })

    bt = Backtester(ExecutionConfig(fill_probability=1.0))
    result = bt.run(predictions, prices)

    assert result.sharpe_ratio is not None or result.max_drawdown_pct is not None


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

def test_simulator_buy_and_sell():
    sim = PaperSimulator(slippage_pct=0, commission=0, initial_capital=100_000)

    # Buy
    intent = OrderIntent(ticker="TEST", side="buy", quantity=10, order_type="market")
    fill = sim.execute_intent(intent, market_price=100.0)
    assert fill is not None
    assert fill.side == "buy"
    assert sim.positions["TEST"] == 10

    # Sell
    intent = OrderIntent(ticker="TEST", side="sell", quantity=10, order_type="market")
    fill = sim.execute_intent(intent, market_price=110.0)
    assert fill is not None
    assert fill.side == "sell"
    assert sim.positions["TEST"] == 0


def test_simulator_insufficient_funds():
    sim = PaperSimulator(initial_capital=50)
    intent = OrderIntent(ticker="TEST", side="buy", quantity=100, order_type="market")
    fill = sim.execute_intent(intent, market_price=100.0)
    assert fill is None


def test_simulator_audit_log():
    sim = PaperSimulator(initial_capital=100_000)
    intent = OrderIntent(ticker="TEST", side="buy", quantity=1, order_type="market")
    sim.execute_intent(intent, market_price=100.0)
    log = sim.export_audit_log()
    assert len(log) >= 2  # ORDER_RECEIVED + ORDER_FILLED
    assert log[0]["event"] == "ORDER_RECEIVED"


def test_simulator_replay_day():
    sim = PaperSimulator(initial_capital=100_000, slippage_pct=0, commission=0)
    intents = [
        OrderIntent(ticker="A", side="buy", quantity=5, order_type="market"),
        OrderIntent(ticker="B", side="buy", quantity=5, order_type="market"),
    ]
    prices = {"A": 100.0, "B": 200.0}
    fills = sim.replay_day(intents, prices)
    assert len(fills) == 2
