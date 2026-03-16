"""Indian stock market hours service (NSE/BSE).

Provides market status, next open/close times, and trading session awareness.
All times are in IST (UTC+05:30).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import NamedTuple

# IST = UTC + 5:30
IST = timezone(timedelta(hours=5, minutes=30))

# NSE/BSE sessions
PRE_OPEN_START = time(9, 0)
PRE_OPEN_END = time(9, 15)
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
POST_CLOSE_END = time(16, 0)

# NSE holidays – extend as needed each year
NSE_HOLIDAYS: set[str] = {
    # ── 2025 ──
    "2025-01-26",  # Republic Day
    "2025-02-26",  # Maha Shivaratri
    "2025-03-14",  # Holi
    "2025-03-31",  # Id-ul-Fitr (Eid)
    "2025-04-10",  # Shri Mahavir Jayanti
    "2025-04-14",  # Dr Ambedkar Jayanti
    "2025-04-18",  # Good Friday
    "2025-05-01",  # Maharashtra Day
    "2025-06-07",  # Bakri Id
    "2025-08-15",  # Independence Day
    "2025-08-16",  # Parsi New Year
    "2025-08-27",  # Ganesh Chaturthi
    "2025-10-02",  # Mahatma Gandhi Jayanti / Dussehra
    "2025-10-21",  # Diwali Laxmi Puja
    "2025-10-22",  # Diwali Balipratipada
    "2025-11-05",  # Guru Nanak Jayanti (Prakash Gurpurab)
    "2025-12-25",  # Christmas
    # ── 2026 ──
    "2026-01-26",  # Republic Day
    "2026-02-17",  # Maha Shivaratri
    "2026-03-03",  # Holi
    "2026-03-20",  # Id-ul-Fitr (Eid)
    "2026-03-25",  # Shri Ram Navami
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-05-27",  # Bakri Id (Eid-ul-Adha)
    "2026-06-25",  # Muharram
    "2026-08-15",  # Independence Day
    "2026-08-18",  # Ganesh Chaturthi
    "2026-10-02",  # Mahatma Gandhi Jayanti
    "2026-10-20",  # Dussehra
    "2026-11-09",  # Diwali Laxmi Puja
    "2026-11-10",  # Diwali Balipratipada
    "2026-11-24",  # Guru Nanak Jayanti
    "2026-12-25",  # Christmas
}


class MarketPhase(str, Enum):
    PRE_OPEN = "pre_open"
    OPEN = "open"
    POST_CLOSE = "post_close"
    CLOSED = "closed"
    HOLIDAY = "holiday"
    WEEKEND = "weekend"


class MarketStatus(NamedTuple):
    phase: MarketPhase
    message: str
    ist_now: str
    next_event: str
    next_event_time: str
    seconds_to_next: int
    is_trading_day: bool


def _is_holiday(dt: datetime) -> bool:
    return dt.strftime("%Y-%m-%d") in NSE_HOLIDAYS


def _next_trading_day(dt: datetime) -> datetime:
    """Find the next trading day (skip weekends & holidays)."""
    nxt = dt + timedelta(days=1)
    while nxt.weekday() >= 5 or _is_holiday(nxt):
        nxt += timedelta(days=1)
    return nxt.replace(hour=9, minute=15, second=0, microsecond=0)


def get_market_status() -> MarketStatus:
    """Return current Indian market status with countdown."""
    now = datetime.now(IST)
    t = now.time()
    today_str = now.strftime("%Y-%m-%d")
    ist_now_str = now.strftime("%Y-%m-%d %H:%M:%S IST")

    # Weekend
    if now.weekday() >= 5:
        next_open = _next_trading_day(now)
        secs = int((next_open - now).total_seconds())
        return MarketStatus(
            phase=MarketPhase.WEEKEND,
            message="Market closed – Weekend",
            ist_now=ist_now_str,
            next_event="Market Opens",
            next_event_time=next_open.strftime("%Y-%m-%d %H:%M IST"),
            seconds_to_next=secs,
            is_trading_day=False,
        )

    # Holiday
    if _is_holiday(now):
        next_open = _next_trading_day(now)
        secs = int((next_open - now).total_seconds())
        return MarketStatus(
            phase=MarketPhase.HOLIDAY,
            message="Market closed – NSE Holiday",
            ist_now=ist_now_str,
            next_event="Market Opens",
            next_event_time=next_open.strftime("%Y-%m-%d %H:%M IST"),
            seconds_to_next=secs,
            is_trading_day=False,
        )

    # Before pre-open
    if t < PRE_OPEN_START:
        open_dt = now.replace(hour=9, minute=0, second=0, microsecond=0)
        secs = int((open_dt - now).total_seconds())
        return MarketStatus(
            phase=MarketPhase.CLOSED,
            message="Market closed – Opens at 9:00 AM IST",
            ist_now=ist_now_str,
            next_event="Pre-Open Session",
            next_event_time=open_dt.strftime("%H:%M IST"),
            seconds_to_next=secs,
            is_trading_day=True,
        )

    # Pre-open session
    if PRE_OPEN_START <= t < PRE_OPEN_END:
        open_dt = now.replace(hour=9, minute=15, second=0, microsecond=0)
        secs = int((open_dt - now).total_seconds())
        return MarketStatus(
            phase=MarketPhase.PRE_OPEN,
            message="Pre-open session active (9:00 – 9:15 AM)",
            ist_now=ist_now_str,
            next_event="Market Opens",
            next_event_time=open_dt.strftime("%H:%M IST"),
            seconds_to_next=secs,
            is_trading_day=True,
        )

    # Market open
    if MARKET_OPEN <= t < MARKET_CLOSE:
        close_dt = now.replace(hour=15, minute=30, second=0, microsecond=0)
        secs = int((close_dt - now).total_seconds())
        return MarketStatus(
            phase=MarketPhase.OPEN,
            message="Market is OPEN (9:15 AM – 3:30 PM IST)",
            ist_now=ist_now_str,
            next_event="Market Closes",
            next_event_time=close_dt.strftime("%H:%M IST"),
            seconds_to_next=secs,
            is_trading_day=True,
        )

    # Post-close
    if MARKET_CLOSE <= t < POST_CLOSE_END:
        next_open = _next_trading_day(now)
        secs = int((next_open - now).total_seconds())
        return MarketStatus(
            phase=MarketPhase.POST_CLOSE,
            message="Post-close session (3:30 – 4:00 PM)",
            ist_now=ist_now_str,
            next_event="Next Market Open",
            next_event_time=next_open.strftime("%Y-%m-%d %H:%M IST"),
            seconds_to_next=secs,
            is_trading_day=True,
        )

    # After post-close
    next_open = _next_trading_day(now)
    secs = int((next_open - now).total_seconds())
    return MarketStatus(
        phase=MarketPhase.CLOSED,
        message="Market closed for the day",
        ist_now=ist_now_str,
        next_event="Next Market Open",
        next_event_time=next_open.strftime("%Y-%m-%d %H:%M IST"),
        seconds_to_next=secs,
        is_trading_day=False,
    )
