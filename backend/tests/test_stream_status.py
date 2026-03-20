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


def test_price_feed_warm_skips_live_autoconnect_when_disabled(monkeypatch):
    from backend.services import price_feed as price_feed_module
    from backend.services.price_feed import PriceFeed

    feed = PriceFeed()
    monkeypatch.setattr(PriceFeed, "is_market_open", property(lambda self: True))
    monkeypatch.setattr(type(price_feed_module.settings), "live_broker_enabled", property(lambda self: True))
    monkeypatch.setattr(type(price_feed_module.settings), "replay_enabled", property(lambda self: True))
    monkeypatch.setattr(price_feed_module.settings, "AUTO_CONNECT_LIVE_FEED_ON_STARTUP", False)

    calls = {"start": 0}

    class FakeAngel:
        is_connected = False

        def start(self, symbols: list[str]):
            calls["start"] += 1
            return {"mode": "live", "connected": True, "last_error": None}

        def snapshot(self):
            return {
                "mode": "replay",
                "connected": False,
                "authenticated": False,
                "subscribed_symbols": [],
                "tick_count": 0,
                "last_error": None,
                "last_event_at": None,
            }

    feed._angel = FakeAngel()
    status = feed.warm()

    assert calls["start"] == 0
    assert status["mode"] == "replay"
