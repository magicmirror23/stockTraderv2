"""Backend-only Angel One SmartAPI live feed integration."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from backend.core.config import settings


logger = logging.getLogger(__name__)

TOKEN_CACHE = settings.storage_path / "angel_tokens.json"
NSE_CM = 1
BSE_CM = 3

_INDEX_TOKENS: dict[str, dict[str, Any]] = {
    "NIFTY50": {"token": "99926000", "exchange": NSE_CM, "tradingsymbol": "NIFTY 50"},
    "BANKNIFTY": {"token": "99926009", "exchange": NSE_CM, "tradingsymbol": "NIFTY BANK"},
    "SENSEX": {"token": "99919000", "exchange": BSE_CM, "tradingsymbol": "SENSEX"},
}


class AngelLiveFeed:
    """Singleton wrapper around Angel SmartAPI with non-fatal lifecycle management."""

    _instance: "AngelLiveFeed | None" = None
    _guard = threading.Lock()

    def __new__(cls) -> "AngelLiveFeed":
        if cls._instance is None:
            with cls._guard:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._lock = threading.Lock()
        self._smart_api = None
        self._socket = None
        self._auth_token: str | None = None
        self._feed_token: str | None = None
        self._status: dict[str, Any] = {
            "mode": "unavailable",
            "available": settings.live_broker_enabled,
            "connected": False,
            "authenticated": False,
            "subscribed_symbols": [],
            "tick_count": 0,
            "last_error": None,
            "last_event_at": None,
        }
        self._tokens: dict[str, dict[str, Any]] = {}
        self._latest_ticks: dict[str, dict[str, Any]] = {}
        self._load_token_cache()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    @property
    def is_connected(self) -> bool:
        return bool(self._status["connected"])

    def get_latest(self, symbol: str) -> dict[str, Any] | None:
        with self._lock:
            return self._latest_ticks.get(symbol.upper())

    def start(self, symbols: list[str]) -> dict[str, Any]:
        if not settings.live_broker_enabled:
            return self._set_status(
                mode="unavailable",
                connected=False,
                authenticated=False,
                last_error="live_broker_disabled_or_credentials_missing",
            )

        self._set_status(mode="waking", connected=False, last_error=None)

        if not self._authenticate():
            fallback_mode = "replay" if settings.replay_enabled else "unavailable"
            logger.warning("Angel feed auth failed; falling back", extra={"mode": fallback_mode})
            return self._set_status(mode=fallback_mode, connected=False, last_error=self._status["last_error"])

        resolved = self._resolve_tokens(symbols)
        if not resolved:
            fallback_mode = "replay" if settings.replay_enabled else "unavailable"
            return self._set_status(mode=fallback_mode, connected=False, last_error="no_tokens_resolved")

        try:
            from SmartApi.smartWebSocketV2 import SmartWebSocketV2
        except ImportError:
            fallback_mode = "replay" if settings.replay_enabled else "unavailable"
            return self._set_status(mode=fallback_mode, connected=False, last_error="smartapi_websocket_missing")

        token_list: dict[int, list[str]] = {}
        for symbol in resolved:
            info = self._tokens[symbol]
            token_list.setdefault(info["exchange"], []).append(info["token"])

        subscriptions = [{"exchangeType": exchange, "tokens": tokens} for exchange, tokens in token_list.items()]
        self._socket = SmartWebSocketV2(self._auth_token, settings.ANGEL_API_KEY, settings.ANGEL_CLIENT_ID, self._feed_token)

        def on_open(_wsapp):
            logger.info("Angel feed connected", extra={"mode": "live"})
            self._set_status(mode="live", connected=True, authenticated=True, subscribed_symbols=resolved, last_error=None)
            try:
                logger.info("Angel feed subscribing", extra={"mode": "live"})
                self._socket.subscribe("stocktrader", 2, subscriptions)
            except Exception as exc:
                logger.warning("Angel feed subscribe failed: %s", exc)
                self._fallback("subscribe_failed")

        def on_data(_wsapp, message):
            self._record_tick(message)

        def on_error(_wsapp, error):
            logger.warning("Angel feed websocket error: %s", error)
            self._fallback(str(error))

        def on_close(_wsapp):
            logger.info("Angel feed websocket closed")
            if settings.replay_enabled:
                self._fallback("socket_closed")
            else:
                self._set_status(mode="unavailable", connected=False, last_error="socket_closed")

        self._socket.on_open = on_open
        self._socket.on_data = on_data
        self._socket.on_error = on_error
        self._socket.on_close = on_close

        thread = threading.Thread(target=self._socket.connect, daemon=True, name="angel-live-feed")
        thread.start()

        for _ in range(30):
            if self.is_connected:
                break
            time.sleep(0.2)

        if not self.is_connected:
            self._fallback("connect_timeout")

        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        if self._socket is not None:
            try:
                self._socket.close_connection()
            except Exception:
                logger.debug("Angel socket close raised; ignoring")
        self._socket = None
        return self._set_status(
            mode="replay" if settings.replay_enabled else "unavailable",
            connected=False,
            authenticated=False,
            subscribed_symbols=[],
            last_error=None,
        )

    def _authenticate(self) -> bool:
        try:
            from SmartApi import SmartConnect
            import pyotp
        except ImportError:
            self._set_status(last_error="smartapi_dependencies_missing")
            return False

        try:
            totp = pyotp.TOTP(settings.ANGEL_TOTP_SECRET).now()
            self._smart_api = SmartConnect(api_key=settings.ANGEL_API_KEY)
            session = self._smart_api.generateSession(settings.ANGEL_CLIENT_ID, settings.ANGEL_CLIENT_PIN, totp)
            if not session or session.get("status") is False:
                self._set_status(last_error=(session or {}).get("message", "angel_login_failed"))
                return False
            self._auth_token = session["data"]["jwtToken"]
            self._feed_token = self._smart_api.getfeedToken()
            self._set_status(authenticated=True, available=True)
            return True
        except Exception as exc:
            self._set_status(last_error=f"angel_auth_error:{exc}")
            return False

    def _resolve_tokens(self, symbols: list[str]) -> list[str]:
        resolved: list[str] = []
        for symbol in [s.upper() for s in symbols]:
            if symbol in self._tokens:
                resolved.append(symbol)
                continue
            if symbol in _INDEX_TOKENS:
                self._tokens[symbol] = dict(_INDEX_TOKENS[symbol])
                resolved.append(symbol)
                continue
            if self._smart_api is None:
                continue
            try:
                query = symbol.replace("_", "&")
                result = self._smart_api.searchScrip("NSE", query)
                for item in (result or {}).get("data", []):
                    tradingsymbol = item.get("tradingsymbol", "")
                    if tradingsymbol in {query, f"{query}-EQ"}:
                        self._tokens[symbol] = {
                            "token": item["symboltoken"],
                            "exchange": NSE_CM,
                            "tradingsymbol": tradingsymbol,
                        }
                        resolved.append(symbol)
                        break
            except Exception as exc:
                logger.warning("Angel token resolution failed for %s: %s", symbol, exc)
        self._save_token_cache()
        return resolved

    def _record_tick(self, raw: dict[str, Any]) -> None:
        token = str(raw.get("token", ""))
        exchange = raw.get("exchange_type", NSE_CM)
        symbol = None
        for candidate, info in self._tokens.items():
            if str(info.get("token")) == token and info.get("exchange") == exchange:
                symbol = candidate
                break
        if not symbol:
            return
        normalized = self._normalize_tick(symbol, raw)
        with self._lock:
            self._latest_ticks[symbol] = normalized
            self._status["tick_count"] += 1
            self._status["last_event_at"] = normalized["timestamp"]

    def _normalize_tick(self, symbol: str, raw: dict[str, Any]) -> dict[str, Any]:
        def paisa(value: Any) -> float | None:
            if value in (None, ""):
                return None
            return round(float(value) / 100.0, 2)

        price = paisa(raw.get("last_traded_price")) or 0.0
        prev_close = paisa(raw.get("closed_price")) or 0.0
        change = round(price - prev_close, 2) if prev_close else 0.0
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0
        return {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price": price,
            "volume": int(raw.get("volume_trade_for_the_day", 0) or 0),
            "bid": paisa(((raw.get("best_5_buy_data") or [{}])[0]).get("price")),
            "ask": paisa(((raw.get("best_5_sell_data") or [{}])[0]).get("price")),
            "open": paisa(raw.get("open_price_of_the_day")),
            "high": paisa(raw.get("high_price_of_the_day")),
            "low": paisa(raw.get("low_price_of_the_day")),
            "close": price,
            "prev_close": prev_close,
            "change": change,
            "change_pct": change_pct,
            "source": "angel_one",
        }

    def _fallback(self, error: str) -> None:
        mode = "replay" if settings.replay_enabled else "unavailable"
        logger.warning("Angel feed fallback_to_replay", extra={"mode": mode})
        self._set_status(mode=mode, connected=False, last_error=error)

    def _set_status(self, **updates: Any) -> dict[str, Any]:
        with self._lock:
            self._status.update(updates)
            self._status["available"] = settings.live_broker_enabled
            return dict(self._status)

    def _load_token_cache(self) -> None:
        if not TOKEN_CACHE.exists():
            return
        try:
            data = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            self._tokens = data.get("tokens", {})
        except Exception:
            logger.debug("Angel token cache unreadable; ignoring")

    def _save_token_cache(self) -> None:
        try:
            TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_CACHE.write_text(json.dumps({"tokens": self._tokens}, indent=2), encoding="utf-8")
        except Exception:
            logger.debug("Angel token cache write failed; ignoring")
