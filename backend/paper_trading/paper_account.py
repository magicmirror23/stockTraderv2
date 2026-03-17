"""Paper trading account manager.

Paper accounts must behave like real accounts: they track cash, holdings,
average cost, open orders, realized PnL, and a timestamped audit trail.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from backend.trading_engine.account_state import AccountState, HoldingState, OrderState


@dataclass
class Position:
    ticker: str
    quantity: int
    avg_price: float
    option_type: Optional[str] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None

    @property
    def key(self) -> str:
        if self.option_type or self.strike is not None or self.expiry:
            strike = f"{float(self.strike):g}" if self.strike is not None else ""
            return "|".join([self.ticker.upper(), self.option_type or "", strike, self.expiry or ""])
        return self.ticker.upper()


@dataclass
class PaperAccount:
    account_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    initial_cash: float = 100_000.0
    cash: float = 100_000.0
    positions: dict[str, Position] = field(default_factory=dict)
    trade_log: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    realized_pnl: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    label: Optional[str] = None

    @property
    def equity(self) -> float:
        """Total account value: cash plus marked positions at average cost."""
        pos_value = sum(p.quantity * p.avg_price for p in self.positions.values())
        return self.cash + pos_value

    @property
    def open_orders(self) -> list[dict[str, Any]]:
        return [
            order
            for order in self.orders
            if str(order.get("status") or "").lower()
            not in {"filled", "cancelled", "canceled", "rejected", "failed"}
        ]

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
        self.last_updated = datetime.now(timezone.utc)

    def register_order(
        self,
        *,
        order_id: str,
        ticker: str,
        side: str,
        quantity: int,
        status: str,
        price: float,
        option_type: str | None = None,
        strike: float | None = None,
        expiry: str | None = None,
        detail: str | None = None,
        commission: float = 0.0,
    ) -> dict[str, Any]:
        order = {
            "order_id": order_id,
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "status": status,
            "price": price,
            "option_type": option_type,
            "strike": strike,
            "expiry": expiry,
            "detail": detail,
            "commission": commission,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.orders.append(order)
        self.last_updated = datetime.now(timezone.utc)
        return order

    def apply_fill(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        option_type: str | None = None,
        strike: float | None = None,
        expiry: str | None = None,
        commission: float = 0.0,
        order_id: str | None = None,
    ) -> None:
        """Apply a simulated fill to the account and update state immediately."""
        cost = quantity * price
        position = Position(
            ticker=ticker,
            quantity=quantity,
            avg_price=price,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
        )
        key = position.key
        timestamp = datetime.now(timezone.utc).isoformat()

        if side == "buy":
            total_cost = cost + commission
            if total_cost > self.cash:
                raise ValueError(f"Insufficient cash: need {total_cost:.2f}, have {self.cash:.2f}")
            self.cash -= total_cost
            if key in self.positions:
                existing = self.positions[key]
                total_qty = existing.quantity + quantity
                weighted_cost = (existing.avg_price * existing.quantity) + (price * quantity)
                existing.avg_price = weighted_cost / total_qty if total_qty else existing.avg_price
                existing.quantity = total_qty
            else:
                self.positions[key] = position
            self.trade_log.append(
                {
                    "ticker": ticker,
                    "side": side,
                    "quantity": quantity,
                    "price": price,
                    "commission": commission,
                    "realized_pnl": 0.0,
                    "timestamp": timestamp,
                    "order_id": order_id,
                }
            )

        elif side == "sell":
            if key not in self.positions or self.positions[key].quantity < quantity:
                held = self.positions[key].quantity if key in self.positions else 0
                raise ValueError(f"Insufficient position for {key}: requested {quantity}, have {held}")
            existing = self.positions[key]
            proceeds = cost - commission
            pnl = (price - existing.avg_price) * quantity - commission
            existing.quantity -= quantity
            self.cash += proceeds
            self.realized_pnl += pnl
            if existing.quantity == 0:
                del self.positions[key]
            self.trade_log.append(
                {
                    "ticker": ticker,
                    "side": side,
                    "quantity": quantity,
                    "price": price,
                    "commission": commission,
                    "realized_pnl": pnl,
                    "avg_buy_price": existing.avg_price,
                    "timestamp": timestamp,
                    "order_id": order_id,
                }
            )
        else:
            raise ValueError(f"Unsupported side {side}")

        self.last_updated = datetime.now(timezone.utc)

    def check_margin(self, order_cost: float) -> bool:
        return self.cash >= order_cost

    def expire_options(self, date: str, spot_prices: dict[str, float]) -> list[dict]:
        """Handle option expiry: exercise ITM, expire worthless OTM."""
        expired = []
        keys_to_remove = []
        for key, pos in self.positions.items():
            if pos.expiry and pos.expiry == date:
                spot = spot_prices.get(pos.ticker, 0)
                if pos.option_type == "CE" and spot > (pos.strike or 0):
                    pnl = (spot - (pos.strike or 0)) * pos.quantity
                    self.cash += pnl
                    self.realized_pnl += pnl
                    expired.append({"key": key, "action": "exercised", "pnl": pnl})
                elif pos.option_type == "PE" and spot < (pos.strike or 0):
                    pnl = ((pos.strike or 0) - spot) * pos.quantity
                    self.cash += pnl
                    self.realized_pnl += pnl
                    expired.append({"key": key, "action": "exercised", "pnl": pnl})
                else:
                    expired.append({"key": key, "action": "expired_worthless", "pnl": 0})
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del self.positions[key]
        self.last_updated = datetime.now(timezone.utc)
        return expired

    def to_account_state(self) -> AccountState:
        holdings = {
            key: HoldingState(
                ticker=position.ticker,
                quantity=position.quantity,
                average_price=position.avg_price,
                option_type=position.option_type,
                strike=position.strike,
                expiry=position.expiry,
                source="paper_positions",
            )
            for key, position in self.positions.items()
        }
        open_orders = [
            OrderState(
                order_id=str(order.get("order_id") or ""),
                ticker=str(order.get("ticker") or ""),
                side=str(order.get("side") or ""),
                quantity=int(order.get("quantity") or 0),
                status=str(order.get("status") or "open"),
                pending_quantity=int(order.get("pending_quantity") or order.get("quantity") or 0),
                average_price=float(order.get("price") or 0.0),
                option_type=order.get("option_type"),
                strike=order.get("strike"),
                expiry=order.get("expiry"),
                source="paper_orders",
            )
            for order in self.open_orders
        ]
        return AccountState(
            account_type="paper",
            available_cash=self.cash,
            buying_power=self.cash,
            total_equity=self.equity,
            holdings=holdings,
            open_positions={},
            open_orders=open_orders,
            last_updated=self.last_updated,
            raw={"trade_log": list(self.trade_log), "orders": list(self.orders)},
        )


class PaperAccountManager:
    """In-memory paper account store."""

    def __init__(self) -> None:
        self._accounts: dict[str, PaperAccount] = {}

    def create_account(self, initial_cash: float = 100_000.0, label: str | None = None) -> PaperAccount:
        account = PaperAccount(initial_cash=initial_cash, cash=initial_cash, label=label)
        self._accounts[account.account_id] = account
        return account

    def get_account(self, account_id: str) -> PaperAccount | None:
        return self._accounts.get(account_id)

    def list_accounts(self) -> list[PaperAccount]:
        return list(self._accounts.values())

    def delete_account(self, account_id: str) -> bool:
        return self._accounts.pop(account_id, None) is not None
