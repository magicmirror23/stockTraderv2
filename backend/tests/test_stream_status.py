def test_feed_status_endpoint(client):
    response = client.get("/api/v1/stream/feed-status")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] in {"live", "replay", "unavailable", "waking"}


def test_watchlist_endpoint(client):
    response = client.get("/api/v1/stream/watchlist")
    assert response.status_code == 200
    assert "data" in response.json()


def test_price_feed_uses_live_quote_fallback_for_indices(monkeypatch):
    from backend.services.price_feed import PriceFeed

    feed = PriceFeed()
    monkeypatch.setattr(PriceFeed, "is_market_open", property(lambda self: True))

    class FakeAngel:
        is_connected = True

        def __init__(self) -> None:
            self.fetch_calls = 0

        def get_latest(self, symbol: str):
            return None

        def fetch_quote(self, symbol: str):
            self.fetch_calls += 1
            return {
                "symbol": symbol,
                "timestamp": "2026-03-17T10:50:00+00:00",
                "price": 22500.5,
                "volume": 0,
                "bid": 22500.0,
                "ask": 22501.0,
                "open": 22480.0,
                "high": 22550.0,
                "low": 22450.0,
                "close": 22500.5,
                "prev_close": 22400.0,
                "change": 100.5,
                "change_pct": 0.45,
                "source": "angel_one_quote",
            }

    fake_angel = FakeAngel()
    feed._angel = fake_angel
    tick = feed.get_latest_price("NIFTY50")

    assert tick is not None
    assert tick.symbol == "NIFTY50"
    assert tick.price == 22500.5
    assert fake_angel.fetch_calls == 1
