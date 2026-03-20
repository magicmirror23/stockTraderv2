"""Tests for account-state-aware trading safeguards."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.trading_engine.account_state import (
    AccountState,
    HoldingState,
    OrderState,
    ValidationRules,
    validate_trade_against_account_state,
)
from backend.trading_engine.angel_adapter import AngelPaperAdapter
from backend.trading_engine.execution_engine import AccountStateExecutionEngine


def _account_state(
    *,
    cash: float = 100000.0,
    holdings: dict[str, HoldingState] | None = None,
    open_orders: list[OrderState] | None = None,
) -> AccountState:
    return AccountState(
        account_type="paper",
        available_cash=cash,
        buying_power=cash,
        total_equity=cash + sum(position.exposure for position in (holdings or {}).values()),
        holdings=holdings or {},
        open_positions={},
        open_orders=open_orders or [],
    )


def test_validate_buy_with_enough_cash():
    result = validate_trade_against_account_state(
        {"ticker": "RELIANCE", "side": "buy", "quantity": 10},
        _account_state(cash=5000.0),
        current_price=100.0,
        rules=ValidationRules(max_position_size_pct=1.0, max_portfolio_exposure_pct=1.0),
    )
    assert result.allowed is True


def test_validate_buy_with_insufficient_cash():
    result = validate_trade_against_account_state(
        {"ticker": "RELIANCE", "side": "buy", "quantity": 100},
        _account_state(cash=1000.0),
        current_price=50.0,
        rules=ValidationRules(max_position_size_pct=1.0, max_portfolio_exposure_pct=1.0),
    )
    assert result.allowed is False
    assert result.code == "insufficient_cash"


def test_validate_sell_with_sufficient_holdings():
    state = _account_state(
        cash=1000.0,
        holdings={"RELIANCE": HoldingState(ticker="RELIANCE", quantity=5, average_price=100.0)},
    )
    result = validate_trade_against_account_state(
        {"ticker": "RELIANCE", "side": "sell", "quantity": 5},
        state,
        current_price=120.0,
    )
    assert result.allowed is True


def test_validate_sell_without_holdings():
    result = validate_trade_against_account_state(
        {"ticker": "RELIANCE", "side": "sell", "quantity": 1},
        _account_state(cash=1000.0),
        current_price=100.0,
    )
    assert result.allowed is False
    assert result.code == "insufficient_holdings"


def test_validate_duplicate_buy_prevention():
    state = _account_state(
        cash=10000.0,
        open_orders=[
            OrderState(
                order_id="open-buy-1",
                ticker="RELIANCE",
                side="buy",
                quantity=5,
                status="open",
                pending_quantity=5,
            )
        ],
    )
    result = validate_trade_against_account_state(
        {"ticker": "RELIANCE", "side": "buy", "quantity": 2},
        state,
        current_price=100.0,
    )
    assert result.allowed is False
    assert result.code == "duplicate_open_order"


def test_execution_engine_refreshes_account_state_before_execution():
    class FakeAdapter:
        def __init__(self) -> None:
            self.fetch_calls = 0
            self.place_calls = 0
            self.holdings: dict[str, HoldingState] = {}

        def fetch_account_state(self) -> AccountState:
            self.fetch_calls += 1
            return AccountState(
                account_type="real",
                available_cash=10000.0,
                buying_power=10000.0,
                total_equity=10000.0,
                holdings=dict(self.holdings),
                open_positions={},
                open_orders=[],
            )

        def place_order(self, order_intent: dict) -> dict:
            self.place_calls += 1
            self.holdings["RELIANCE"] = HoldingState(
                ticker="RELIANCE",
                quantity=order_intent["quantity"],
                average_price=order_intent["current_price"],
            )
            return {
                "order_id": "broker-1",
                "status": "filled",
                "filled_price": order_intent["current_price"],
                "ticker": order_intent["ticker"],
                "quantity": order_intent["quantity"],
            }

    engine = AccountStateExecutionEngine(
        ValidationRules(max_position_size_pct=1.0, max_portfolio_exposure_pct=1.0)
    )
    adapter = FakeAdapter()
    outcome = engine.execute_with_adapter(
        adapter,
        {"ticker": "RELIANCE", "side": "buy", "quantity": 5, "order_type": "market"},
        current_price=100.0,
    )
    assert outcome.accepted is True
    assert adapter.place_calls == 1
    assert adapter.fetch_calls >= 2
    assert outcome.account_state_after.held_quantity("RELIANCE") == 5


def test_execution_engine_uses_adapter_state_methods_when_fetch_account_state_missing():
    class LegacyAdapter:
        def __init__(self) -> None:
            self.balance_calls = 0
            self.holdings_calls = 0
            self.positions_calls = 0
            self.open_orders_calls = 0
            self.place_calls = 0

        def get_balance(self) -> dict:
            self.balance_calls += 1
            return {"available_cash": 10000.0, "buying_power": 10000.0, "total_equity": 10000.0}

        def get_holdings(self) -> list[dict]:
            self.holdings_calls += 1
            return []

        def get_positions(self) -> list[dict]:
            self.positions_calls += 1
            return []

        def get_open_orders(self) -> list[dict]:
            self.open_orders_calls += 1
            return []

        def place_order(self, order_intent: dict) -> dict:
            self.place_calls += 1
            return {
                "order_id": "legacy-1",
                "status": "filled",
                "filled_price": order_intent["current_price"],
                "ticker": order_intent["ticker"],
                "quantity": order_intent["quantity"],
            }

    engine = AccountStateExecutionEngine(
        ValidationRules(max_position_size_pct=1.0, max_portfolio_exposure_pct=1.0)
    )
    adapter = LegacyAdapter()
    outcome = engine.execute_with_adapter(
        adapter,
        {"ticker": "INFY", "side": "buy", "quantity": 3, "order_type": "market"},
        current_price=100.0,
    )
    assert outcome.accepted is True
    assert adapter.place_calls == 1
    assert adapter.balance_calls >= 1
    assert adapter.holdings_calls >= 1
    assert adapter.positions_calls >= 1
    assert adapter.open_orders_calls >= 1


def test_adapter_buy_and_sell_enforce_account_state():
    adapter = AngelPaperAdapter(slippage_pct=0.0, option_slippage_pct=0.0)
    buy = adapter.place_order(
        {
            "ticker": "TEST",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
            "current_price": 100.0,
        }
    )
    assert buy["status"] == "filled"
    sell = adapter.place_order(
        {
            "ticker": "TEST",
            "side": "sell",
            "quantity": 10,
            "order_type": "market",
            "current_price": 101.0,
        }
    )
    assert sell["status"] == "filled"


def test_adapter_rejects_sell_without_holdings():
    adapter = AngelPaperAdapter(slippage_pct=0.0, option_slippage_pct=0.0)
    result = adapter.place_order(
        {
            "ticker": "TEST",
            "side": "sell",
            "quantity": 1,
            "order_type": "market",
            "current_price": 100.0,
        }
    )
    assert result["status"] == "rejected"


def test_trade_execute_route_rejects_duplicate_position(auth_client, monkeypatch):
    from backend.api.routers import trade as trade_router

    class FakeAdapter:
        def fetch_account_state(self) -> AccountState:
            return AccountState(
                account_type="real",
                available_cash=10000.0,
                buying_power=10000.0,
                total_equity=10000.0,
                holdings={"RELIANCE": HoldingState(ticker="RELIANCE", quantity=2, average_price=100.0)},
                open_positions={},
                open_orders=[],
            )

        def get_ltp(self, ticker: str) -> dict:
            return {"ltp": 100.0, "ticker": ticker}

        def place_order(self, order_intent: dict) -> dict:  # pragma: no cover - should never be called
            raise AssertionError("place_order should not be called when account state blocks the trade")

    monkeypatch.setattr(trade_router, "_get_adapter", lambda: FakeAdapter())
    create = auth_client.post(
        "/api/v1/trade_intent",
        json={"ticker": "RELIANCE", "side": "buy", "quantity": 1, "order_type": "market"},
    )
    assert create.status_code == 201
    execute = auth_client.post(
        "/api/v1/execute",
        json={"intent_id": create.json()["intent_id"]},
    )
    assert execute.status_code == 422
    assert "pyramiding" in execute.json()["detail"].lower() or "position already exists" in execute.json()["detail"].lower()


def test_trade_execute_route_rejects_when_live_price_is_unavailable(auth_client, monkeypatch):
    from backend.api.routers import trade as trade_router

    class FakeAdapter:
        def fetch_account_state(self) -> AccountState:
            return AccountState(
                account_type="real",
                available_cash=10000.0,
                buying_power=10000.0,
                total_equity=10000.0,
                holdings={},
                open_positions={},
                open_orders=[],
            )

        def get_ltp(self, ticker: str) -> dict:
            return {"ltp": 0.0, "ticker": ticker}

        def place_order(self, order_intent: dict) -> dict:  # pragma: no cover - should never be called
            raise AssertionError("place_order should not be called when price data is unavailable")

    monkeypatch.setattr(trade_router, "_get_adapter", lambda: FakeAdapter())
    create = auth_client.post(
        "/api/v1/trade_intent",
        json={"ticker": "INFY", "side": "buy", "quantity": 1, "order_type": "market"},
    )
    assert create.status_code == 201

    execute = auth_client.post(
        "/api/v1/execute",
        json={"intent_id": create.json()["intent_id"]},
    )
    assert execute.status_code == 503
    assert "live price unavailable" in execute.json()["detail"].lower()


def test_trade_execute_route_surfaces_persistence_failure(monkeypatch):
    from backend.api.routers import trade as trade_router
    from backend.core.config import settings

    class FakeAdapter:
        def fetch_account_state(self) -> AccountState:
            return AccountState(
                account_type="real",
                available_cash=10000.0,
                buying_power=10000.0,
                total_equity=10000.0,
                holdings={},
                open_positions={},
                open_orders=[],
            )

        def get_ltp(self, ticker: str) -> dict:
            return {"ltp": 100.0, "ticker": ticker}

        def place_order(self, order_intent: dict) -> dict:
            return {
                "order_id": "broker-1",
                "status": "filled",
                "filled_price": 100.0,
                "ticker": order_intent["ticker"],
                "quantity": order_intent["quantity"],
            }

    monkeypatch.setattr(trade_router, "_get_adapter", lambda: FakeAdapter())
    monkeypatch.setattr(
        trade_router,
        "_persist_execution",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("execution_persistence_failed")),
    )

    with TestClient(
        app,
        headers={"Authorization": f"Bearer {settings.SECRET_KEY}"},
        raise_server_exceptions=False,
    ) as client:
        create = client.post(
            "/api/v1/trade_intent",
            json={"ticker": "INFY", "side": "buy", "quantity": 1, "order_type": "market"},
        )
        assert create.status_code == 201

        execute = client.post(
            "/api/v1/execute",
            json={"intent_id": create.json()["intent_id"]},
        )
        assert execute.status_code == 500
