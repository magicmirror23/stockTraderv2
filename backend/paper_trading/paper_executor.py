"""Paper trading execution engine.

Paper execution must obey the same pre-trade account-state checks as live
execution. Orders are validated against the latest paper account snapshot
before fills are simulated.
"""

from __future__ import annotations

import logging
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.paper_trading.paper_account import PaperAccount
from backend.trading_engine.account_state import ValidationRules, fetch_paper_account_state, validate_trade_against_account_state

logger = logging.getLogger(__name__)


@dataclass
class PaperFill:
    order_id: str
    ticker: str
    side: str
    quantity: int
    fill_price: float
    slippage: float
    commission: float
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
        validation_rules: ValidationRules | None = None,
    ) -> None:
        self._slippage_pct = slippage_pct
        self._commission = commission_per_trade
        self._fill_prob = fill_probability
        self._rng = random.Random(seed)
        self._validation_rules = validation_rules or ValidationRules()
        self.last_rejection_reason: str | None = None

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
        """Execute a paper order against an account."""
        self.last_rejection_reason = None
        order_id = str(uuid.uuid4())

        validation = validate_trade_against_account_state(
            {
                "ticker": ticker,
                "side": side,
                "quantity": quantity,
                "option_type": option_type,
                "strike": strike,
                "expiry": expiry,
            },
            fetch_paper_account_state(account),
            current_price=market_price,
            rules=self._validation_rules,
        )
        if not validation.allowed:
            account.register_order(
                order_id=order_id,
                ticker=ticker,
                side=side,
                quantity=quantity,
                status="rejected",
                price=market_price,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                detail=validation.reason,
                commission=self._commission,
            )
            self.last_rejection_reason = validation.reason
            logger.warning("Paper order rejected before fill: %s", validation.reason)
            return None

        order_state = account.register_order(
            order_id=order_id,
            ticker=ticker,
            side=side,
            quantity=quantity,
            status="pending",
            price=market_price,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            commission=self._commission,
        )

        if self._rng.random() > self._fill_prob:
            order_state["status"] = "failed"
            order_state["detail"] = "Order not filled in simulated market"
            self.last_rejection_reason = order_state["detail"]
            logger.info("Order not filled (simulated partial fill failure)")
            return None

        slippage = market_price * self._slippage_pct
        fill_price = market_price + slippage if side == "buy" else market_price - slippage
        total_cost = fill_price * quantity + self._commission

        if side == "buy" and not account.check_margin(total_cost):
            order_state["status"] = "rejected"
            order_state["detail"] = (
                f"Insufficient cash: need {total_cost:.2f}, have {account.cash:.2f}"
            )
            self.last_rejection_reason = order_state["detail"]
            logger.warning("Insufficient margin for %s %d %s @ %.2f", side, quantity, ticker, fill_price)
            return None

        try:
            account.apply_fill(
                ticker=ticker,
                side=side,
                quantity=quantity,
                price=fill_price,
                option_type=option_type,
                strike=strike,
                expiry=expiry,
                commission=self._commission,
                order_id=order_id,
            )
        except ValueError as exc:
            order_state["status"] = "rejected"
            order_state["detail"] = str(exc)
            self.last_rejection_reason = str(exc)
            logger.warning("Fill rejected: %s", exc)
            return None

        order_state["status"] = "filled"
        order_state["price"] = fill_price
        order_state["detail"] = None

        fill = PaperFill(
            order_id=order_id,
            ticker=ticker,
            side=side,
            quantity=quantity,
            fill_price=fill_price,
            slippage=slippage,
            commission=self._commission,
            timestamp=datetime.now(timezone.utc),
        )

        logger.info(
            "Paper fill: %s %d %s @ %.2f (slippage=%.4f)",
            side,
            quantity,
            ticker,
            fill_price,
            slippage,
        )
        return fill
