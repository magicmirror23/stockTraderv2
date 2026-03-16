"""Tests for order manager and Angel adapter."""

from backend.trading_engine.order_manager import OrderManager, RiskConfig, OrderIntent
from backend.trading_engine.angel_adapter import AngelPaperAdapter


# ---------------------------------------------------------------------------
# Order Manager
# ---------------------------------------------------------------------------

def test_order_manager_buy():
    mgr = OrderManager(capital=100_000)
    intent = mgr.prediction_to_intent("TEST", "buy", 0.8, 100.0)
    assert intent is not None
    assert intent.side == "buy"
    assert intent.quantity > 0
    assert intent.stop_loss is not None
    assert intent.take_profit is not None


def test_order_manager_sell_without_position():
    mgr = OrderManager(capital=100_000)
    intent = mgr.prediction_to_intent("TEST", "sell", 0.9, 100.0)
    assert intent is None  # no position to sell


def test_order_manager_sell_with_position():
    mgr = OrderManager(capital=100_000)
    mgr.positions["TEST"] = 50
    intent = mgr.prediction_to_intent("TEST", "sell", 0.9, 100.0)
    assert intent is not None
    assert intent.side == "sell"
    assert intent.quantity == 50


def test_order_manager_low_confidence():
    mgr = OrderManager(capital=100_000)
    intent = mgr.prediction_to_intent("TEST", "buy", 0.3, 100.0)
    assert intent is None


def test_order_manager_hold():
    mgr = OrderManager(capital=100_000)
    intent = mgr.prediction_to_intent("TEST", "hold", 0.9, 100.0)
    assert intent is None


def test_order_manager_batch():
    mgr = OrderManager(capital=100_000)
    predictions = [
        {"ticker": "A", "action": "buy", "confidence": 0.8},
        {"ticker": "B", "action": "hold", "confidence": 0.9},
        {"ticker": "C", "action": "buy", "confidence": 0.7},
    ]
    prices = {"A": 100.0, "B": 200.0, "C": 150.0}
    intents = mgr.batch_predictions_to_intents(predictions, prices)
    assert len(intents) == 2  # only A and C (B is hold)


# ---------------------------------------------------------------------------
# Angel Adapter
# ---------------------------------------------------------------------------

def test_adapter_place_order():
    adapter = AngelPaperAdapter(slippage_pct=0.001)
    result = adapter.place_order({
        "ticker": "TEST",
        "side": "buy",
        "quantity": 10,
        "order_type": "market",
        "current_price": 100.0,
    })
    assert result["status"] == "filled"
    assert result["ticker"] == "TEST"
    assert result["filled_price"] > 100.0  # slippage applied


def test_adapter_cancel():
    adapter = AngelPaperAdapter()
    result = adapter.place_order({
        "ticker": "X", "side": "buy", "quantity": 1,
        "order_type": "market", "current_price": 50.0,
    })
    order_id = result["order_id"]
    cancel = adapter.cancel_order(order_id)
    assert cancel["status"] == "cancelled"


def test_adapter_cancel_nonexistent():
    adapter = AngelPaperAdapter()
    result = adapter.cancel_order("nonexistent")
    assert result["status"] == "not_found"
