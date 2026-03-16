"""Unified live/replay price feed with free-host resilience."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

import pandas as pd

from backend.core.config import settings
from backend.services.angel_feed import AngelLiveFeed
from backend.services.market_hours import MarketPhase, get_market_status


logger = logging.getLogger(__name__)
DEFAULT_WATCHLIST = settings.watchlist_symbols or ["RELIANCE", "TCS", "INFY"]


@dataclass
class PriceTick:
    symbol: str
    timestamp: datetime
    price: float
    volume: int
    bid: float | None = None
    ask: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    prev_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    feed_mode: str = "replay"


class PriceFeed:
    """Process-wide market feed that prefers broker ticks and falls back to replay."""

    _instance: "PriceFeed | None" = None

    def __new__(cls) -> "PriceFeed":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._data_dir = settings.raw_data_path
        self._angel = AngelLiveFeed()
        self._mode = "waking"
        self._latest: dict[str, PriceTick] = {}
        self._last_error: str | None = None
        self._reconnecting = False
        self._warm_complete = False

    @property
    def feed_mode(self) -> str:
        if self._mode == "waking" and not self._warm_complete:
            return "waking"
        if self.is_market_open and self._angel.is_connected:
            return "live"
        if settings.replay_enabled and self.has_replay_data:
            return "replay"
        if settings.demo_enabled:
            return "replay"
        return "unavailable"

    @property
    def market_status(self) -> dict[str, Any]:
        status = get_market_status()
        return {
            "phase": status.phase.value,
            "message": status.message,
            "ist_now": status.ist_now,
            "next_event": status.next_event,
            "next_event_time": status.next_event_time,
            "seconds_to_next": status.seconds_to_next,
            "is_trading_day": status.is_trading_day,
        }

    @property
    def is_market_open(self) -> bool:
        return get_market_status().phase == MarketPhase.OPEN

    @property
    def has_replay_data(self) -> bool:
        return self._data_dir.exists() and any(self._data_dir.glob("*.csv"))

    @property
    def feed_status(self) -> dict[str, Any]:
        live = self._angel.snapshot()
        market = self.market_status
        serving_mode = "live" if self.is_market_open and self._angel.is_connected else "last_close"
        return {
            "mode": self.feed_mode,
            "connected": self._angel.is_connected,
            "reconnecting": self._reconnecting,
            "available": self.feed_mode != "unavailable",
            "backend_sleep_possible": True,
            "last_error": live.get("last_error") or self._last_error,
            "watchlist": self.default_watchlist(),
            "market": market,
            "market_phase": market["phase"],
            "serving_mode": serving_mode,
            "live": live,
        }

    def warm(self) -> dict[str, Any]:
        self._mode = "waking"
        if settings.live_broker_enabled and self.is_market_open:
            logger.info("Attempting broker warmup", extra={"mode": "live"})
            live_status = self._angel.start(self.default_watchlist())
            self._mode = live_status.get("mode", "replay")
            self._last_error = live_status.get("last_error")
        elif settings.live_broker_enabled and not self.is_market_open:
            self._mode = "replay" if settings.replay_enabled else "unavailable"
            self._last_error = "market_closed_last_close_mode"
        else:
            self._mode = "replay" if settings.replay_enabled else "unavailable"
        self._warm_complete = True
        return self.feed_status

    def connect_live(self, symbols: list[str] | None = None) -> dict[str, Any]:
        if not self.is_market_open:
            self._mode = "replay" if settings.replay_enabled else "unavailable"
            self._last_error = "market_closed_last_close_mode"
            return self.feed_status
        self._reconnecting = True
        try:
            status = self._angel.start(symbols or self.default_watchlist())
            self._mode = status.get("mode", self._mode)
            self._last_error = status.get("last_error")
            return self.feed_status
        finally:
            self._reconnecting = False

    def disconnect_live(self) -> dict[str, Any]:
        self._angel.stop()
        self._mode = "replay" if settings.replay_enabled else "unavailable"
        return self.feed_status

    def default_watchlist(self) -> list[str]:
        return DEFAULT_WATCHLIST

    def available_symbols(self) -> list[str]:
        if not self._data_dir.exists():
            return self.default_watchlist()
        symbols = sorted(path.stem for path in self._data_dir.glob("*.csv") if path.name != ".gitkeep")
        return symbols or self.default_watchlist()

    def get_latest_price(self, symbol: str) -> PriceTick | None:
        symbol = symbol.upper()
        if self.is_market_open and self._angel.is_connected:
            live = self._angel.get_latest(symbol)
            if live:
                tick = self._tick_from_dict(live, self.feed_mode)
                self._latest[symbol] = tick
                return tick
        tick = self._closing_tick(symbol) if not self.is_market_open else self._replay_last_tick(symbol)
        if tick:
            self._latest[symbol] = tick
        return tick

    async def stream(self, symbol: str, speed: float = 1.0, recent_days: int = 20) -> AsyncIterator[PriceTick]:
        if not self.is_market_open:
            tick = self._closing_tick(symbol)
            if tick:
                self._latest[symbol.upper()] = tick
                yield tick
            return
        if self._angel.is_connected:
            async for tick in self._live_single(symbol):
                yield tick
            return
        async for tick in self._replay_single(symbol, speed=speed, recent_days=recent_days):
            yield tick

    async def stream_multi(self, symbols: list[str], speed: float = 10.0, recent_days: int = 20) -> AsyncIterator[PriceTick]:
        if not self.is_market_open:
            for symbol in symbols:
                tick = self._closing_tick(symbol)
                if tick:
                    self._latest[symbol.upper()] = tick
                    yield tick
            return
        if self._angel.is_connected:
            async for tick in self._live_multi(symbols):
                yield tick
            return
        async for tick in self._replay_multi(symbols, speed=speed, recent_days=recent_days):
            yield tick

    async def _live_single(self, symbol: str) -> AsyncIterator[PriceTick]:
        last_seen: str | None = None
        while True:
            live = self._angel.get_latest(symbol.upper())
            if live and live.get("timestamp") != last_seen:
                last_seen = live["timestamp"]
                tick = self._tick_from_dict(live, "live")
                self._latest[symbol.upper()] = tick
                yield tick
            elif self.feed_mode != "live":
                break
            await asyncio.sleep(0.5)
        async for tick in self._replay_single(symbol, speed=8.0, recent_days=10):
            yield tick

    async def _live_multi(self, symbols: list[str]) -> AsyncIterator[PriceTick]:
        last_seen: dict[str, str] = {}
        while self.feed_mode == "live":
            for symbol in symbols:
                live = self._angel.get_latest(symbol.upper())
                if live and live.get("timestamp") != last_seen.get(symbol.upper()):
                    last_seen[symbol.upper()] = live["timestamp"]
                    tick = self._tick_from_dict(live, "live")
                    self._latest[symbol.upper()] = tick
                    yield tick
            await asyncio.sleep(0.3)
        async for tick in self._replay_multi(symbols, speed=12.0, recent_days=10):
            yield tick

    async def _replay_single(self, symbol: str, speed: float, recent_days: int) -> AsyncIterator[PriceTick]:
        frame = self._load_frame(symbol)
        if frame is None:
            return
        if recent_days > 0 and len(frame) > recent_days:
            frame = frame.tail(recent_days).reset_index(drop=True)
        delay = max(0.05, 0.5 / max(speed, 1.0))
        for index, row in frame.iterrows():
            prev_close = float(frame.iloc[index - 1]["Close"]) if index > 0 else float(row["Open"])
            for tick in self._row_to_ticks(symbol.upper(), row, prev_close, n_ticks=12):
                self._latest[symbol.upper()] = tick
                yield tick
                await asyncio.sleep(delay)

    async def _replay_multi(self, symbols: list[str], speed: float, recent_days: int) -> AsyncIterator[PriceTick]:
        all_ticks: list[PriceTick] = []
        for symbol in symbols:
            frame = self._load_frame(symbol)
            if frame is None:
                continue
            if recent_days > 0 and len(frame) > recent_days:
                frame = frame.tail(recent_days).reset_index(drop=True)
            for index, row in frame.iterrows():
                prev_close = float(frame.iloc[index - 1]["Close"]) if index > 0 else float(row["Open"])
                all_ticks.extend(self._row_to_ticks(symbol.upper(), row, prev_close, n_ticks=8))
        all_ticks.sort(key=lambda item: item.timestamp)
        delay = max(0.05, 0.3 / max(speed, 1.0))
        for tick in all_ticks:
            self._latest[tick.symbol] = tick
            yield tick
            await asyncio.sleep(delay)

    def get_watchlist_snapshot(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        snapshot = []
        for symbol in symbols or self.default_watchlist():
            tick = self.get_latest_price(symbol)
            if tick is None:
                continue
            snapshot.append(self._tick_to_dict(tick))
        return snapshot

    def get_market_overview(self) -> dict[str, Any]:
        snapshot = self.get_watchlist_snapshot(self.available_symbols()[:20])
        if not snapshot:
            return {
                "mode": self.feed_mode,
                "gainers": [],
                "losers": [],
                "volume_leaders": [],
                "indices": [],
                "categories": {},
                "total_symbols": 0,
            }
        sorted_by_change = sorted(snapshot, key=lambda item: item.get("change_pct") or 0.0, reverse=True)
        return {
            "mode": self.feed_mode,
            "gainers": sorted_by_change[:5],
            "losers": list(reversed(sorted_by_change[-5:])),
            "volume_leaders": sorted(snapshot, key=lambda item: item.get("volume") or 0, reverse=True)[:5],
            "indices": [item for item in snapshot if item["symbol"] in {"NIFTY50", "BANKNIFTY", "SENSEX"}],
            "categories": {"watchlist": snapshot},
            "total_symbols": len(snapshot),
        }

    def _replay_last_tick(self, symbol: str) -> PriceTick | None:
        frame = self._load_frame(symbol)
        if frame is None or frame.empty:
            return None
        row = frame.iloc[-1]
        prev_close = float(frame.iloc[-2]["Close"]) if len(frame) > 1 else float(row["Open"])
        tick = self._row_to_ticks(symbol.upper(), row, prev_close, n_ticks=1)[0]
        return tick

    def _closing_tick(self, symbol: str) -> PriceTick | None:
        frame = self._load_frame(symbol)
        if frame is None or frame.empty:
            return None
        row = frame.iloc[-1]
        close_price = float(row["Close"])
        prev_close = float(frame.iloc[-2]["Close"]) if len(frame) > 1 else float(row["Open"])
        change = round(close_price - prev_close, 2)
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0
        spread = round(max(close_price * 0.0007, 0.05), 2)
        base = row["Date"].to_pydatetime() if hasattr(row["Date"], "to_pydatetime") else row["Date"]
        return PriceTick(
            symbol=symbol.upper(),
            timestamp=base.replace(hour=15, minute=30, second=0, microsecond=0, tzinfo=timezone.utc),
            price=round(close_price, 2),
            volume=int(row.get("Volume", 0)),
            bid=round(close_price - spread, 2),
            ask=round(close_price + spread, 2),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=round(close_price, 2),
            prev_close=round(prev_close, 2),
            change=change,
            change_pct=change_pct,
            feed_mode="close",
        )

    def _load_frame(self, symbol: str) -> pd.DataFrame | None:
        path = self._data_dir / f"{symbol.upper()}.csv"
        if not path.exists():
            self._last_error = f"missing_replay_data:{symbol.upper()}"
            return None
        return pd.read_csv(path, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)

    def _row_to_ticks(self, symbol: str, row: Any, prev_close: float, n_ticks: int) -> list[PriceTick]:
        base = row["Date"].to_pydatetime() if hasattr(row["Date"], "to_pydatetime") else row["Date"]
        o = float(row["Open"])
        h = float(row["High"])
        l = float(row["Low"])
        c = float(row["Close"])
        volume = int(row.get("Volume", 0))
        prices = [o]
        if n_ticks > 1:
            for _ in range(max(n_ticks - 2, 0)):
                prices.append(round(random.uniform(l, h), 2))
            prices.append(c)
        ticks: list[PriceTick] = []
        for idx, price in enumerate(prices):
            ts = base.replace(hour=9, minute=15, tzinfo=timezone.utc) + timedelta(minutes=idx * 5)
            change = round(price - prev_close, 2)
            change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0
            spread = round(max(price * 0.0007, 0.05), 2)
            ticks.append(
                PriceTick(
                    symbol=symbol,
                    timestamp=ts,
                    price=round(price, 2),
                    volume=max(1, volume // max(n_ticks, 1)),
                    bid=round(price - spread, 2),
                    ask=round(price + spread, 2),
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    prev_close=round(prev_close, 2),
                    change=change,
                    change_pct=change_pct,
                    feed_mode="replay",
                )
            )
        return ticks

    def _tick_from_dict(self, payload: dict[str, Any], mode: str) -> PriceTick:
        timestamp = payload.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return PriceTick(
            symbol=payload["symbol"],
            timestamp=timestamp,
            price=float(payload["price"]),
            volume=int(payload.get("volume", 0)),
            bid=payload.get("bid"),
            ask=payload.get("ask"),
            open=payload.get("open"),
            high=payload.get("high"),
            low=payload.get("low"),
            close=payload.get("close"),
            prev_close=payload.get("prev_close"),
            change=payload.get("change"),
            change_pct=payload.get("change_pct"),
            feed_mode=mode,
        )

    @staticmethod
    def _tick_to_dict(tick: PriceTick) -> dict[str, Any]:
        return {
            "symbol": tick.symbol,
            "timestamp": tick.timestamp.isoformat(),
            "price": tick.price,
            "volume": tick.volume,
            "bid": tick.bid,
            "ask": tick.ask,
            "open": tick.open,
            "high": tick.high,
            "low": tick.low,
            "close": tick.close,
            "prev_close": tick.prev_close,
            "change": tick.change,
            "change_pct": tick.change_pct,
            "feed_mode": tick.feed_mode,
        }
