"""Risk management module for the trading bot.

Provides position sizing, daily loss limits, portfolio-level risk checks,
and trailing stop-loss logic for safe real-money trading.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """Configurable risk parameters."""
    max_position_pct: float = 0.10      # Max 10% of capital per position
    max_portfolio_risk_pct: float = 0.30  # Max 30% of capital at risk
    max_daily_loss: float = 5_000.0     # Hard daily loss limit (₹)
    max_daily_loss_pct: float = 0.02    # 2% of capital daily loss limit
    trailing_stop_pct: float = 0.015    # 1.5% trailing stop
    min_risk_reward_ratio: float = 2.0  # Minimum risk:reward before entry
    max_open_positions: int = 5
    cooldown_after_loss: int = 2        # Skip N cycles after a stop-loss hit


@dataclass
class PositionRisk:
    """Live risk state for a single position."""
    ticker: str
    side: str
    entry_price: float
    quantity: int
    highest_price: float = 0.0   # For trailing stop (long)
    lowest_price: float = 1e9    # For trailing stop (short)
    trailing_stop: float = 0.0

    def update_trailing_stop(self, current_price: float, trail_pct: float) -> None:
        if self.side == "buy":
            if current_price > self.highest_price:
                self.highest_price = current_price
            self.trailing_stop = self.highest_price * (1 - trail_pct)
        else:
            if current_price < self.lowest_price:
                self.lowest_price = current_price
            self.trailing_stop = self.lowest_price * (1 + trail_pct)

    def should_exit_trailing(self, current_price: float) -> bool:
        if self.trailing_stop <= 0:
            return False
        if self.side == "buy":
            return current_price <= self.trailing_stop
        else:
            return current_price >= self.trailing_stop


class RiskManager:
    """Portfolio-level risk manager."""

    def __init__(self, capital: float, config: RiskConfig | None = None) -> None:
        self.capital = capital
        self._initial_capital = capital
        self.config = config or RiskConfig()
        self.daily_pnl: float = 0.0
        self.positions: dict[str, PositionRisk] = {}
        self.loss_cooldown: int = 0  # remaining cycles to skip

    def update_capital(self, available_cash: float) -> None:
        """Refresh capital from the broker's available balance."""
        self.capital = available_cash
        logger.debug("RiskManager capital updated to ₹%.2f", available_cash)

    def can_open_position(self, ticker: str, price: float, quantity: int) -> tuple[bool, str]:
        """Check whether a new position is allowed under risk rules.

        Returns (allowed, reason).
        """
        if self.loss_cooldown > 0:
            return False, f"Cooldown active ({self.loss_cooldown} cycles remaining after stop-loss)"

        # Daily loss limit
        daily_limit = min(self.config.max_daily_loss, self.capital * self.config.max_daily_loss_pct)
        if self.daily_pnl <= -daily_limit:
            return False, f"Daily loss limit reached (₹{daily_limit:.0f})"

        # Max open positions
        if len(self.positions) >= self.config.max_open_positions:
            return False, f"Max open positions ({self.config.max_open_positions}) reached"

        # Already in this ticker
        if ticker in self.positions:
            return False, f"Already holding {ticker}"

        # Position size limit
        position_value = price * quantity
        max_position = self.capital * self.config.max_position_pct
        if position_value > max_position:
            return False, f"Position ₹{position_value:.0f} exceeds max ₹{max_position:.0f}"

        # Portfolio heat (total exposure)
        total_exposure = sum(
            p.entry_price * p.quantity for p in self.positions.values()
        ) + position_value
        max_exposure = self.capital * self.config.max_portfolio_risk_pct
        if total_exposure > max_exposure:
            return False, f"Portfolio exposure ₹{total_exposure:.0f} would exceed max ₹{max_exposure:.0f}"

        return True, "OK"

    def optimal_quantity(self, price: float, stop_loss_pct: float) -> int:
        """Calculate position size using fixed-fractional risk model.

        Risks at most max_position_pct of capital, with the stop-loss
        determining how many shares that translates to.
        """
        if price <= 0 or stop_loss_pct <= 0:
            return 0

        risk_per_share = price * stop_loss_pct
        max_risk_amount = self.capital * self.config.max_position_pct * stop_loss_pct
        qty = int(max_risk_amount / risk_per_share)
        return max(1, qty) if qty > 0 else 0

    def register_entry(self, ticker: str, side: str, price: float, quantity: int) -> None:
        """Track a new position."""
        pos = PositionRisk(
            ticker=ticker, side=side, entry_price=price, quantity=quantity,
            highest_price=price, lowest_price=price,
        )
        pos.update_trailing_stop(price, self.config.trailing_stop_pct)
        self.positions[ticker] = pos

    def check_exit(self, ticker: str, current_price: float) -> tuple[bool, str]:
        """Check if a position should be exited.

        Returns (should_exit, reason).
        """
        pos = self.positions.get(ticker)
        if not pos:
            return False, ""

        pos.update_trailing_stop(current_price, self.config.trailing_stop_pct)

        if pos.should_exit_trailing(current_price):
            return True, "TRAILING_STOP"

        return False, ""

    def register_exit(self, ticker: str, pnl: float, reason: str) -> None:
        """Record an exit and update daily P&L."""
        self.daily_pnl += pnl
        if ticker in self.positions:
            del self.positions[ticker]

        if reason in ("STOP_LOSS", "TRAILING_STOP"):
            self.loss_cooldown = self.config.cooldown_after_loss
            logger.info("Stop-loss hit on %s, cooldown for %d cycles", ticker, self.loss_cooldown)

    def tick_cycle(self) -> None:
        """Called each bot cycle to decrement cooldown."""
        if self.loss_cooldown > 0:
            self.loss_cooldown -= 1

    def reset_daily(self) -> None:
        """Reset daily P&L (call at market open)."""
        self.daily_pnl = 0.0
        self.loss_cooldown = 0

    def meets_risk_reward(
        self, expected_return_pct: float, stop_loss_pct: float
    ) -> bool:
        """Check if the expected reward justifies the risk."""
        if stop_loss_pct <= 0:
            return False
        ratio = expected_return_pct / stop_loss_pct
        return ratio >= self.config.min_risk_reward_ratio

    @property
    def status(self) -> dict:
        return {
            "daily_pnl": round(self.daily_pnl, 2),
            "open_positions": len(self.positions),
            "loss_cooldown": self.loss_cooldown,
            "capital": self.capital,
            "portfolio_exposure": round(
                sum(p.entry_price * p.quantity for p in self.positions.values()), 2
            ),
        }
