"""Paper trading execution engine.

Simulates order fills with configurable slippage, latency, and
partial fill probability. Supports equity and option orders.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.paper_trading.paper_account import PaperAccount

logger = logging.getLogger(__name__)


@dataclass
class PaperFill:
    ticker: str
    side: str
    quantity: int
    fill_price: float
    slippage: float
    timestamp: datetime
    status: str = "filled"


class PaperExecutor:
    """Executes orders in paper mode with realistic simulation."""

    def __init__(
        self,
        slippage_pct: float = 0.001,
        commission_per_trade: float = 20.0,
        fill_probability: float = 0.95,
        seed: int = 42,
    ) -> None:
        self._slippage_pct = slippage_pct
        self._commission = commission_per_trade
        self._fill_prob = fill_probability
        self._rng = random.Random(seed)

    def execute_order(
        self,
        account: PaperAccount,
        ticker: str,
        side: str,
        quantity: int,
        market_price: float,
        option_type: str | None = None,
        strike: float | None = None,
        expiry: str | None = None,
    ) -> PaperFill | None:
        """Execute a paper order against an account.

        Returns PaperFill on success, None if not filled (random partial fill simulation).
        """
        # Simulate fill probability
        if self._rng.random() > self._fill_prob:
            logger.info("Order not filled (simulated partial fill failure)")
            return None

        # Apply slippage
        slippage = market_price * self._slippage_pct
        if side == "buy":
            fill_price = market_price + slippage
        else:
            fill_price = market_price - slippage

        # Deduct commission
        total_cost = fill_price * quantity + self._commission

        # Margin check
        if side == "buy" and not account.check_margin(total_cost):
            logger.warning("Insufficient margin for %s %d %s @ %.2f", side, quantity, ticker, fill_price)
            return None

        # Apply fill
        try:
            account.apply_fill(
                ticker=ticker, side=side, quantity=quantity, price=fill_price,
                option_type=option_type, strike=strike, expiry=expiry,
            )
        except ValueError as e:
            logger.warning("Fill rejected: %s", e)
            return None

        # Deduct commission from cash
        account.cash -= self._commission

        fill = PaperFill(
            ticker=ticker, side=side, quantity=quantity,
            fill_price=fill_price, slippage=slippage,
            timestamp=datetime.now(timezone.utc),
        )

        logger.info("Paper fill: %s %d %s @ %.2f (slippage=%.4f)", side, quantity, ticker, fill_price, slippage)
        return fill
