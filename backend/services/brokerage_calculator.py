"""Angel One brokerage and charges calculator.

Computes the full cost of trading on Angel One (equity segment, NSE)
including brokerage, STT, exchange charges, GST, SEBI fees, stamp duty,
and DP charges.

Fee schedule (as of 2024):
- Brokerage: ₹20/order or 0.03% (whichever is lower) — same for intraday & delivery
- STT (Securities Transaction Tax):
    Intraday: 0.025% on sell side
    Delivery: 0.1% on both sides
- Exchange transaction charges (NSE): 0.00345% of turnover
- GST: 18% on (brokerage + exchange charges)
- SEBI turnover fee: ₹10 per crore (0.0001%)
- Stamp duty: 0.003% on buy side (varies by state, 0.003% is common)
- DP charges: ₹15.34 + GST = ₹18.10 per scrip (only on delivery sell)

Reference: https://www.angelone.in/charges
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TradeType(Enum):
    INTRADAY = "intraday"
    DELIVERY = "delivery"


@dataclass
class ChargesBreakdown:
    """Itemised breakdown of all charges for a trade."""
    turnover: float
    brokerage: float
    stt: float
    exchange_charges: float
    gst: float
    sebi_fee: float
    stamp_duty: float
    dp_charges: float
    total_charges: float
    net_pnl: float  # gross P&L minus total charges
    charges_pct: float  # total charges as % of turnover

    def to_dict(self) -> dict:
        return {k: round(v, 4) for k, v in self.__dict__.items()}


# ── Constants ──────────────────────────────────────────────────────────────

BROKERAGE_FLAT = 20.0            # ₹20 per executed order
BROKERAGE_PCT = 0.0003           # 0.03%
STT_INTRADAY_SELL = 0.00025      # 0.025% sell side only
STT_DELIVERY = 0.001             # 0.1% both sides
EXCHANGE_NSE_PCT = 0.0000345     # 0.00345%
GST_RATE = 0.18                  # 18%
SEBI_PER_CRORE = 10.0            # ₹10 per crore
STAMP_DUTY_BUY = 0.00003         # 0.003% buy side
DP_CHARGES_PER_SCRIP = 18.10     # ₹15.34 + 18% GST


def calculate_charges(
    buy_price: float,
    sell_price: float,
    quantity: int,
    trade_type: TradeType = TradeType.INTRADAY,
) -> ChargesBreakdown:
    """Calculate complete Angel One charges for a round-trip trade.

    Parameters
    ----------
    buy_price : float
        Average buy price per share.
    sell_price : float
        Average sell price per share.
    quantity : int
        Number of shares traded.
    trade_type : TradeType
        INTRADAY or DELIVERY.

    Returns
    -------
    ChargesBreakdown
        Full itemised breakdown.
    """
    buy_value = buy_price * quantity
    sell_value = sell_price * quantity
    turnover = buy_value + sell_value
    gross_pnl = (sell_price - buy_price) * quantity

    # Brokerage: min(₹20, 0.03% of trade value) — per leg
    brok_buy = min(BROKERAGE_FLAT, buy_value * BROKERAGE_PCT)
    brok_sell = min(BROKERAGE_FLAT, sell_value * BROKERAGE_PCT)
    brokerage = brok_buy + brok_sell

    # STT
    if trade_type == TradeType.INTRADAY:
        stt = sell_value * STT_INTRADAY_SELL
    else:
        stt = buy_value * STT_DELIVERY + sell_value * STT_DELIVERY

    # Exchange transaction charges (both legs)
    exchange_charges = turnover * EXCHANGE_NSE_PCT

    # GST on brokerage + exchange charges
    gst = (brokerage + exchange_charges) * GST_RATE

    # SEBI turnover fee
    sebi_fee = turnover * SEBI_PER_CRORE / 1_00_00_000  # per crore

    # Stamp duty (buy side only)
    stamp_duty = buy_value * STAMP_DUTY_BUY

    # DP charges (delivery sell only)
    dp_charges = DP_CHARGES_PER_SCRIP if trade_type == TradeType.DELIVERY else 0.0

    total_charges = brokerage + stt + exchange_charges + gst + sebi_fee + stamp_duty + dp_charges
    net_pnl = gross_pnl - total_charges
    charges_pct = (total_charges / turnover * 100) if turnover > 0 else 0.0

    return ChargesBreakdown(
        turnover=turnover,
        brokerage=brokerage,
        stt=stt,
        exchange_charges=exchange_charges,
        gst=gst,
        sebi_fee=sebi_fee,
        stamp_duty=stamp_duty,
        dp_charges=dp_charges,
        total_charges=total_charges,
        net_pnl=net_pnl,
        charges_pct=charges_pct,
    )


def estimate_breakeven_move(
    price: float,
    quantity: int,
    trade_type: TradeType = TradeType.INTRADAY,
) -> float:
    """Estimate the minimum price move (in ₹) needed to break even after charges.

    Useful for the trading bot to skip trades where expected profit < charges.
    """
    # Simulate a round-trip at the same price to get the fixed cost
    charges = calculate_charges(price, price, quantity, trade_type)
    # Break-even move per share
    return charges.total_charges / quantity if quantity > 0 else 0.0


def net_pnl_after_charges(
    buy_price: float,
    sell_price: float,
    quantity: int,
    trade_type: TradeType = TradeType.INTRADAY,
) -> float:
    """Quick helper: returns net P&L after all Angel One charges."""
    return calculate_charges(buy_price, sell_price, quantity, trade_type).net_pnl
