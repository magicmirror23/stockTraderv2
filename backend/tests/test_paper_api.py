from __future__ import annotations

from types import SimpleNamespace


def _mock_price(monkeypatch, price: float = 100.0):
    from backend.services import price_feed

    monkeypatch.setattr(
        price_feed.PriceFeed,
        "get_latest_price",
        lambda self, ticker: SimpleNamespace(price=price, symbol=ticker),
    )


def test_create_and_list_paper_accounts(client):
    create = client.post("/api/v1/paper/accounts", json={"initial_cash": 50000, "label": "demo"})
    assert create.status_code == 201
    account_id = create.json()["account_id"]

    listing = client.get("/api/v1/paper/accounts")
    assert listing.status_code == 200
    assert any(account["account_id"] == account_id for account in listing.json())


def test_paper_buy_updates_state_after_fill(client, monkeypatch):
    _mock_price(monkeypatch, price=100.0)
    create = client.post("/api/v1/paper/accounts", json={"initial_cash": 10000})
    account_id = create.json()["account_id"]

    response = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "RELIANCE", "side": "buy", "quantity": 10, "order_type": "market"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "filled"
    assert payload["account_state_after"]["holdings"]["RELIANCE"]["quantity"] == 10
    assert payload["account_state_after"]["available_cash"] < payload["account_state_before"]["available_cash"]


def test_paper_buy_rejects_insufficient_cash(client, monkeypatch):
    _mock_price(monkeypatch, price=100.0)
    create = client.post("/api/v1/paper/accounts", json={"initial_cash": 100})
    account_id = create.json()["account_id"]

    response = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "RELIANCE", "side": "buy", "quantity": 10, "order_type": "market"},
    )
    assert response.status_code == 422
    assert "insufficient" in response.json()["detail"].lower()


def test_paper_sell_rejects_without_holdings(client, monkeypatch):
    _mock_price(monkeypatch, price=100.0)
    create = client.post("/api/v1/paper/accounts", json={"initial_cash": 10000})
    account_id = create.json()["account_id"]

    response = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "RELIANCE", "side": "sell", "quantity": 1, "order_type": "market"},
    )
    assert response.status_code == 422
    assert "holdings" in response.json()["detail"].lower()


def test_paper_duplicate_buy_is_blocked(client, monkeypatch):
    _mock_price(monkeypatch, price=100.0)
    create = client.post("/api/v1/paper/accounts", json={"initial_cash": 10000})
    account_id = create.json()["account_id"]

    first = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "INFY", "side": "buy", "quantity": 5, "order_type": "market"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "INFY", "side": "buy", "quantity": 1, "order_type": "market"},
    )
    assert second.status_code == 422
    assert "position already exists" in second.json()["detail"].lower() or "pyramiding" in second.json()["detail"].lower()


def test_paper_sell_updates_holdings_and_cash(client, monkeypatch):
    _mock_price(monkeypatch, price=100.0)
    create = client.post("/api/v1/paper/accounts", json={"initial_cash": 10000})
    account_id = create.json()["account_id"]

    buy = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "TCS", "side": "buy", "quantity": 5, "order_type": "market"},
    )
    assert buy.status_code == 200

    _mock_price(monkeypatch, price=110.0)
    sell = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "TCS", "side": "sell", "quantity": 5, "order_type": "market"},
    )
    assert sell.status_code == 200
    payload = sell.json()
    assert "TCS" not in payload["account_state_after"]["holdings"]
    assert payload["account_state_after"]["available_cash"] > payload["account_state_before"]["available_cash"]


def test_paper_metrics_include_portfolio_analytics(client, monkeypatch):
    _mock_price(monkeypatch, price=100.0)
    create = client.post("/api/v1/paper/accounts", json={"initial_cash": 10000})
    account_id = create.json()["account_id"]

    buy = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "RELIANCE", "side": "buy", "quantity": 10, "order_type": "market"},
    )
    assert buy.status_code == 200

    _mock_price(monkeypatch, price=115.0)
    sell = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "RELIANCE", "side": "sell", "quantity": 5, "order_type": "market"},
    )
    assert sell.status_code == 200

    metrics = client.get(f"/api/v1/paper/{account_id}/metrics")
    assert metrics.status_code == 200
    payload = metrics.json()
    assert "current_equity" in payload
    assert "total_return_pct" in payload
    assert "holdings" in payload
    assert payload["open_positions"] >= 1
    assert payload["holdings"][0]["ticker"] == "RELIANCE"
