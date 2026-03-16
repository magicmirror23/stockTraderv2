"""Paper trading simulator.

Replays intraday / daily data, applies order intents from model outputs,
and produces audit logs and per-trade records.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class OrderIntent:
    ticker: str
    side: str       # "buy" | "sell"
    quantity: int
    order_type: str  # "market" | "limit"
    limit_price: float | None = None


@dataclass
class Fill:
    fill_id: str
    ticker: str
    side: str
    quantity: int
    price: float
    slippage: float
    commission: float
    timestamp: str


@dataclass
class AuditEntry:
    timestamp: str
    event: str
    data: dict


class PaperSimulator:
    """Simulates order execution with configurable slippage and fees."""

    def __init__(
        self,
        slippage_pct: float = 0.001,
        commission: float = 20.0,
        initial_capital: float = 100_000.0,
    ) -> None:
        self.slippage_pct = slippage_pct
        self.commission = commission
        self.cash = initial_capital
        self.initial_capital = initial_capital
        self.positions: dict[str, int] = {}
        self.fills: list[Fill] = []
        self.audit_log: list[AuditEntry] = []

    def execute_intent(self, intent: OrderIntent, market_price: float) -> Fill | None:
        """Attempt to fill an order intent at the given market price."""
        now = datetime.now(timezone.utc).isoformat()

        self._log(now, "ORDER_RECEIVED", asdict(intent))

        # Determine execution price with slippage
        if intent.side == "buy":
            exec_price = market_price * (1 + self.slippage_pct)
        else:
            exec_price = market_price * (1 - self.slippage_pct)

        # Limit order check
        if intent.order_type == "limit" and intent.limit_price is not None:
            if intent.side == "buy" and exec_price > intent.limit_price:
                self._log(now, "ORDER_REJECTED", {"reason": "limit price exceeded"})
                return None
            if intent.side == "sell" and exec_price < intent.limit_price:
                self._log(now, "ORDER_REJECTED", {"reason": "limit price not met"})
                return None

        total_cost = intent.quantity * exec_price + self.commission

        # Validate
        if intent.side == "buy" and total_cost > self.cash:
            self._log(now, "ORDER_REJECTED", {"reason": "insufficient funds"})
            return None
        if intent.side == "sell" and self.positions.get(intent.ticker, 0) < intent.quantity:
            self._log(now, "ORDER_REJECTED", {"reason": "insufficient position"})
            return None

        # Execute
        fill = Fill(
            fill_id=str(uuid.uuid4()),
            ticker=intent.ticker,
            side=intent.side,
            quantity=intent.quantity,
            price=round(exec_price, 2),
            slippage=round(abs(exec_price - market_price), 4),
            commission=self.commission,
            timestamp=now,
        )

        if intent.side == "buy":
            self.cash -= total_cost
            self.positions[intent.ticker] = self.positions.get(intent.ticker, 0) + intent.quantity
        else:
            self.cash += intent.quantity * exec_price - self.commission
            self.positions[intent.ticker] -= intent.quantity

        self.fills.append(fill)
        self._log(now, "ORDER_FILLED", asdict(fill))
        return fill

    def replay_day(
        self,
        intents: list[OrderIntent],
        prices: dict[str, float],
    ) -> list[Fill]:
        """Replay a single trading day: execute each intent against given prices."""
        fills = []
        for intent in intents:
            price = prices.get(intent.ticker)
            if price is None:
                continue
            fill = self.execute_intent(intent, price)
            if fill:
                fills.append(fill)
        return fills

    def get_portfolio_value(self, prices: dict[str, float]) -> float:
        pos_value = sum(
            qty * prices.get(tkr, 0) for tkr, qty in self.positions.items()
        )
        return self.cash + pos_value

    def _log(self, timestamp: str, event: str, data: dict) -> None:
        self.audit_log.append(AuditEntry(timestamp=timestamp, event=event, data=data))

    def export_audit_log(self) -> list[dict]:
        return [asdict(e) for e in self.audit_log]
