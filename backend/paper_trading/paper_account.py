"""Paper trading account manager.

Manages virtual trading accounts with configurable starting capital
(default ₹100,000). Supports equity and option positions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Position:
    ticker: str
    quantity: int
    avg_price: float
    option_type: Optional[str] = None  # "CE" or "PE" for options
    strike: Optional[float] = None
    expiry: Optional[str] = None


@dataclass
class PaperAccount:
    account_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    cash: float = 100_000.0
    positions: dict[str, Position] = field(default_factory=dict)
    trade_log: list[dict] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    label: Optional[str] = None

    @property
    def equity(self) -> float:
        """Total account value: cash + position values (at avg price)."""
        pos_value = sum(p.quantity * p.avg_price for p in self.positions.values())
        return self.cash + pos_value

    def record_equity(self, date: str, market_prices: dict[str, float] | None = None) -> None:
        """Snapshot equity at a given date using market prices if available."""
        if market_prices:
            pos_value = sum(
                p.quantity * market_prices.get(p.ticker, p.avg_price)
                for p in self.positions.values()
            )
            equity = self.cash + pos_value
        else:
            equity = self.equity
        self.equity_curve.append({"date": date, "equity": equity})

    def apply_fill(self, ticker: str, side: str, quantity: int, price: float,
                   option_type: str | None = None, strike: float | None = None,
                   expiry: str | None = None) -> None:
        """Apply a simulated fill to the account."""
        cost = quantity * price
        key = f"{ticker}_{option_type}_{strike}_{expiry}" if option_type else ticker

        if side == "buy":
            if cost > self.cash:
                raise ValueError(f"Insufficient cash: need {cost}, have {self.cash}")
            self.cash -= cost
            if key in self.positions:
                pos = self.positions[key]
                total_qty = pos.quantity + quantity
                pos.avg_price = (pos.avg_price * pos.quantity + price * quantity) / total_qty
                pos.quantity = total_qty
            else:
                self.positions[key] = Position(
                    ticker=ticker, quantity=quantity, avg_price=price,
                    option_type=option_type, strike=strike, expiry=expiry,
                )
        elif side == "sell":
            if key not in self.positions or self.positions[key].quantity < quantity:
                raise ValueError(f"Insufficient position for {key}")
            pos = self.positions[key]
            pnl = (price - pos.avg_price) * quantity
            pos.quantity -= quantity
            self.cash += cost
            if pos.quantity == 0:
                del self.positions[key]
            self.trade_log.append({
                "ticker": ticker, "side": side, "quantity": quantity,
                "price": price, "pnl": pnl,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    def check_margin(self, order_cost: float) -> bool:
        """Check if account has sufficient margin for a trade."""
        return self.cash >= order_cost

    def expire_options(self, date: str, spot_prices: dict[str, float]) -> list[dict]:
        """Handle option expiry: exercise ITM, expire worthless OTM."""
        expired = []
        keys_to_remove = []
        for key, pos in self.positions.items():
            if pos.expiry and pos.expiry == date:
                spot = spot_prices.get(pos.ticker, 0)
                if pos.option_type == "CE" and spot > (pos.strike or 0):
                    # ITM call: exercise
                    pnl = (spot - (pos.strike or 0)) * pos.quantity
                    self.cash += pnl
                    expired.append({"key": key, "action": "exercised", "pnl": pnl})
                elif pos.option_type == "PE" and spot < (pos.strike or 0):
                    # ITM put: exercise
                    pnl = ((pos.strike or 0) - spot) * pos.quantity
                    self.cash += pnl
                    expired.append({"key": key, "action": "exercised", "pnl": pnl})
                else:
                    expired.append({"key": key, "action": "expired_worthless", "pnl": 0})
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del self.positions[key]
        return expired


class PaperAccountManager:
    """In-memory paper account store."""

    def __init__(self) -> None:
        self._accounts: dict[str, PaperAccount] = {}

    def create_account(self, initial_cash: float = 100_000.0, label: str | None = None) -> PaperAccount:
        account = PaperAccount(cash=initial_cash, label=label)
        self._accounts[account.account_id] = account
        return account

    def get_account(self, account_id: str) -> PaperAccount | None:
        return self._accounts.get(account_id)

    def list_accounts(self) -> list[PaperAccount]:
        return list(self._accounts.values())

    def delete_account(self, account_id: str) -> bool:
        return self._accounts.pop(account_id, None) is not None
