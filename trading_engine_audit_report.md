# Trading Engine Audit Report

## Summary
- Added a shared AccountState abstraction and shared trade validation rules.
- Refactored real and paper execution paths to refresh account state before each execution.
- Added duplicate-order, insufficient-cash, insufficient-holdings, and stale-state safeguards.
- Added focused regression tests for live and paper account-state behavior.

## Changed Files (Full Content)

### .\stocktrader\backend\trading_engine\account_state.py

```python
"""Shared account-state models and pre-trade validation helpers.

Both real and paper execution paths must refresh account state before placing
orders. This module provides a broker-agnostic representation of that state
plus the validation rules the trading engine applies before every trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Mapping


def instrument_key(
    ticker: str,
    option_type: str | None = None,
    strike: float | None = None,
    expiry: str | None = None,
) -> str:
    """Normalize an equity or option symbol into a stable lookup key."""
    normalized = str(ticker or "").strip().upper()
    if not normalized:
        return ""
    if option_type or strike is not None or expiry:
        strike_part = ""
        if strike is not None:
            strike_part = f"{float(strike):g}"
        return "|".join([normalized, option_type or "", strike_part, expiry or ""])
    return normalized


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in ("", None):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _extract_ticker(payload: Mapping[str, Any]) -> str:
    for key in ("ticker", "symbol", "tradingsymbol", "trading_symbol", "name"):
        value = payload.get(key)
        if value:
            return str(value).strip().upper()
    return ""


def _extract_option_type(payload: Mapping[str, Any]) -> str | None:
    for key in ("option_type", "optionType"):
        value = payload.get(key)
        if value:
            return str(value).strip().upper()
    return None


def _extract_expiry(payload: Mapping[str, Any]) -> str | None:
    for key in ("expiry", "expiry_date", "expiryDate"):
        value = payload.get(key)
        if value:
            return str(value).strip()
    return None


def _extract_strike(payload: Mapping[str, Any]) -> float | None:
    for key in ("strike", "strike_price", "strikePrice"):
        if payload.get(key) not in ("", None):
            return _safe_float(payload.get(key))
    return None


def _extract_quantity(payload: Mapping[str, Any]) -> int:
    for key in (
        "quantity",
        "qty",
        "netqty",
        "netQty",
        "holdingquantity",
        "holdingQuantity",
        "sellableqty",
        "sellableQty",
    ):
        if payload.get(key) not in ("", None):
            return _safe_int(payload.get(key))
    return 0


def _extract_average_price(payload: Mapping[str, Any]) -> float:
    for key in (
        "average_price",
        "avg_price",
        "avgPrice",
        "averageprice",
        "avgNetPrice",
        "ltp",
        "last_price",
    ):
        if payload.get(key) not in ("", None):
            return _safe_float(payload.get(key))
    return 0.0


def _normalize_status(value: Any) -> str:
    return str(value or "").strip().lower()


@dataclass(slots=True)
class HoldingState:
    ticker: str
    quantity: int
    average_price: float = 0.0
    market_price: float | None = None
    option_type: str | None = None
    strike: float | None = None
    expiry: str | None = None
    source: str = "holdings"

    @property
    def key(self) -> str:
        return instrument_key(self.ticker, self.option_type, self.strike, self.expiry)

    @property
    def sellable_quantity(self) -> int:
        return max(self.quantity, 0)

    @property
    def exposure(self) -> float:
        reference_price = self.market_price if self.market_price is not None else self.average_price
        return abs(self.quantity) * max(reference_price, 0.0)


@dataclass(slots=True)
class OrderState:
    order_id: str
    ticker: str
    side: str
    quantity: int
    status: str
    pending_quantity: int | None = None
    average_price: float | None = None
    option_type: str | None = None
    strike: float | None = None
    expiry: str | None = None
    source: str = "orders"

    @property
    def key(self) -> str:
        return instrument_key(self.ticker, self.option_type, self.strike, self.expiry)

    @property
    def normalized_side(self) -> str:
        return str(self.side or "").strip().lower()

    @property
    def normalized_status(self) -> str:
        return _normalize_status(self.status)

    @property
    def remaining_quantity(self) -> int:
        return max(self.pending_quantity if self.pending_quantity is not None else self.quantity, 0)

    @property
    def is_open(self) -> bool:
        return self.normalized_status not in {
            "filled",
            "complete",
            "completed",
            "cancelled",
            "canceled",
            "rejected",
            "failed",
            "not_found",
        }


@dataclass(slots=True)
class AccountState:
    account_type: Literal["real", "paper"]
    available_cash: float
    buying_power: float
    total_equity: float
    holdings: dict[str, HoldingState] = field(default_factory=dict)
    open_positions: dict[str, HoldingState] = field(default_factory=dict)
    open_orders: list[OrderState] = field(default_factory=list)
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw: dict[str, Any] = field(default_factory=dict)

    def _position_maps(self) -> tuple[dict[str, HoldingState], dict[str, HoldingState]]:
        return self.holdings, self.open_positions

    def combined_positions(self) -> dict[str, HoldingState]:
        """Combine holdings and open positions into a single normalized view."""
        combined: dict[str, HoldingState] = {}
        for source in self._position_maps():
            for key, position in source.items():
                if key not in combined:
                    combined[key] = HoldingState(
                        ticker=position.ticker,
                        quantity=position.quantity,
                        average_price=position.average_price,
                        market_price=position.market_price,
                        option_type=position.option_type,
                        strike=position.strike,
                        expiry=position.expiry,
                        source=position.source,
                    )
                    continue
                existing = combined[key]
                total_qty = existing.quantity + position.quantity
                if total_qty == 0:
                    existing.quantity = 0
                    continue
                total_cost = (existing.average_price * existing.quantity) + (
                    position.average_price * position.quantity
                )
                existing.average_price = total_cost / total_qty if total_qty else existing.average_price
                existing.quantity = total_qty
                existing.market_price = position.market_price or existing.market_price
        return combined

    def get_position(
        self,
        ticker: str,
        option_type: str | None = None,
        strike: float | None = None,
        expiry: str | None = None,
    ) -> HoldingState | None:
        key = instrument_key(ticker, option_type, strike, expiry)
        return self.combined_positions().get(key)

    def held_quantity(
        self,
        ticker: str,
        option_type: str | None = None,
        strike: float | None = None,
        expiry: str | None = None,
    ) -> int:
        position = self.get_position(ticker, option_type, strike, expiry)
        if not position:
            return 0
        return position.sellable_quantity

    def average_buy_price(
        self,
        ticker: str,
        option_type: str | None = None,
        strike: float | None = None,
        expiry: str | None = None,
    ) -> float:
        position = self.get_position(ticker, option_type, strike, expiry)
        return position.average_price if position else 0.0

    def has_position(
        self,
        ticker: str,
        option_type: str | None = None,
        strike: float | None = None,
        expiry: str | None = None,
    ) -> bool:
        return self.held_quantity(ticker, option_type, strike, expiry) > 0

    def pending_order_quantity(
        self,
        ticker: str,
        side: str,
        option_type: str | None = None,
        strike: float | None = None,
        expiry: str | None = None,
    ) -> int:
        key = instrument_key(ticker, option_type, strike, expiry)
        side_normalized = str(side or "").strip().lower()
        return sum(
            order.remaining_quantity
            for order in self.open_orders
            if order.is_open and order.key == key and order.normalized_side == side_normalized
        )

    def has_open_order(
        self,
        ticker: str,
        side: str | None = None,
        option_type: str | None = None,
        strike: float | None = None,
        expiry: str | None = None,
    ) -> bool:
        key = instrument_key(ticker, option_type, strike, expiry)
        side_normalized = str(side or "").strip().lower() if side else None
        for order in self.open_orders:
            if not order.is_open or order.key != key:
                continue
            if side_normalized is None or order.normalized_side == side_normalized:
                return True
        return False

    def total_exposure(self, current_prices: Mapping[str, float] | None = None) -> float:
        current_prices = current_prices or {}
        total = 0.0
        for key, position in self.combined_positions().items():
            reference_price = current_prices.get(key)
            if reference_price is None:
                reference_price = position.market_price if position.market_price is not None else position.average_price
            total += abs(position.quantity) * max(reference_price, 0.0)
        return total

    def position_count(self) -> int:
        return sum(1 for position in self.combined_positions().values() if position.sellable_quantity > 0)


@dataclass(slots=True)
class ValidationRules:
    allow_pyramiding: bool = False
    allow_partial_exit: bool = True
    prevent_duplicate_orders: bool = True
    prevent_conflicting_open_orders: bool = True
    max_position_size_pct: float = 0.10
    max_portfolio_exposure_pct: float = 0.80
    max_open_positions: int | None = None
    enforce_cash_check: bool = True
    enforce_holdings_check: bool = True


@dataclass(slots=True)
class TradeValidationResult:
    allowed: bool
    reason: str
    code: str
    account_state: AccountState
    normalized_quantity: int = 0
    available_cash: float = 0.0
    held_quantity: int = 0
    pending_buy_quantity: int = 0
    pending_sell_quantity: int = 0
    estimated_cost: float = 0.0


def holding_from_mapping(payload: Mapping[str, Any], source: str = "holdings") -> HoldingState | None:
    ticker = _extract_ticker(payload)
    if not ticker:
        return None
    quantity = _extract_quantity(payload)
    return HoldingState(
        ticker=ticker,
        quantity=quantity,
        average_price=_extract_average_price(payload),
        market_price=payload.get("ltp") and _safe_float(payload.get("ltp")),
        option_type=_extract_option_type(payload),
        strike=_extract_strike(payload),
        expiry=_extract_expiry(payload),
        source=source,
    )


def order_from_mapping(payload: Mapping[str, Any], source: str = "orders") -> OrderState | None:
    ticker = _extract_ticker(payload)
    if not ticker:
        return None
    quantity = _extract_quantity(payload)
    if quantity <= 0 and payload.get("pending_quantity") not in ("", None):
        quantity = _safe_int(payload.get("pending_quantity"))
    order_id = str(
        payload.get("order_id")
        or payload.get("orderid")
        or payload.get("id")
        or ""
    )
    side = str(
        payload.get("side")
        or payload.get("transactiontype")
        or payload.get("transaction_type")
        or ""
    ).strip().lower()
    status = str(payload.get("status") or payload.get("orderstatus") or "open")
    pending_quantity = payload.get("pending_quantity")
    if pending_quantity in ("", None):
        filled_quantity = payload.get("filledshares") or payload.get("filled_quantity")
        if filled_quantity not in ("", None):
            pending_quantity = max(quantity - _safe_int(filled_quantity), 0)
    return OrderState(
        order_id=order_id,
        ticker=ticker,
        side=side,
        quantity=quantity,
        status=status,
        pending_quantity=_safe_int(pending_quantity, quantity),
        average_price=payload.get("average_price") and _safe_float(payload.get("average_price")),
        option_type=_extract_option_type(payload),
        strike=_extract_strike(payload),
        expiry=_extract_expiry(payload),
        source=source,
    )


def _normalize_position_map(
    rows: Iterable[Mapping[str, Any]] | None,
    source: str,
) -> dict[str, HoldingState]:
    normalized: dict[str, HoldingState] = {}
    for row in rows or []:
        position = holding_from_mapping(row, source=source)
        if not position or not position.key:
            continue
        normalized[position.key] = position
    return normalized


def _normalize_open_orders(rows: Iterable[Mapping[str, Any]] | None) -> list[OrderState]:
    normalized: list[OrderState] = []
    for row in rows or []:
        order = order_from_mapping(row)
        if order:
            normalized.append(order)
    return normalized


def fetch_real_account_state(adapter: Any) -> AccountState:
    """Fetch the freshest broker account state available from an adapter."""
    if hasattr(adapter, "fetch_account_state"):
        state = adapter.fetch_account_state()
        if isinstance(state, AccountState):
            return state

    balance = adapter.get_balance() if hasattr(adapter, "get_balance") else {}
    holdings = adapter.get_holdings() if hasattr(adapter, "get_holdings") else []
    positions = adapter.get_positions() if hasattr(adapter, "get_positions") else []
    open_orders = adapter.get_open_orders() if hasattr(adapter, "get_open_orders") else []

    available_cash = _safe_float(balance.get("available_cash"))
    buying_power = _safe_float(balance.get("buying_power"), available_cash)
    total_equity = _safe_float(balance.get("total_equity"), available_cash)

    return AccountState(
        account_type="real",
        available_cash=available_cash,
        buying_power=buying_power or available_cash,
        total_equity=total_equity or available_cash,
        holdings=_normalize_position_map(holdings, source="broker_holdings"),
        open_positions=_normalize_position_map(positions, source="broker_positions"),
        open_orders=_normalize_open_orders(open_orders),
        raw={
            "balance": balance,
            "holdings": list(holdings or []),
            "positions": list(positions or []),
            "open_orders": list(open_orders or []),
        },
    )


def fetch_paper_account_state(account: Any) -> AccountState:
    """Fetch the freshest paper account state from the simulator account."""
    if hasattr(account, "to_account_state"):
        state = account.to_account_state()
        if isinstance(state, AccountState):
            return state

    positions = getattr(account, "positions", {})
    holdings: dict[str, HoldingState] = {}
    for key, position in positions.items():
        holdings[str(key)] = HoldingState(
            ticker=position.ticker,
            quantity=position.quantity,
            average_price=position.avg_price,
            option_type=getattr(position, "option_type", None),
            strike=getattr(position, "strike", None),
            expiry=getattr(position, "expiry", None),
            source="paper_positions",
        )
    cash = _safe_float(getattr(account, "cash", 0.0))
    equity = _safe_float(getattr(account, "equity", cash), cash)
    return AccountState(
        account_type="paper",
        available_cash=cash,
        buying_power=cash,
        total_equity=equity,
        holdings=holdings,
        open_positions={},
        open_orders=[],
        last_updated=getattr(account, "last_updated", datetime.now(timezone.utc)),
    )


def validate_trade_against_account_state(
    order_intent: Mapping[str, Any],
    account_state: AccountState,
    current_price: float,
    rules: ValidationRules | None = None,
) -> TradeValidationResult:
    """Validate a trade against the latest account state.

    This is the shared guardrail both real and paper trading must pass before
    an order is placed.
    """
    rules = rules or ValidationRules()
    side = str(order_intent.get("side") or "").strip().lower()
    ticker = str(order_intent.get("ticker") or "").strip().upper()
    option_type = order_intent.get("option_type")
    strike = order_intent.get("strike")
    expiry = order_intent.get("expiry")
    quantity = _safe_int(order_intent.get("quantity"))
    price = max(_safe_float(current_price), 0.0)

    held_quantity = account_state.held_quantity(ticker, option_type, strike, expiry)
    pending_buy_quantity = account_state.pending_order_quantity(
        ticker, "buy", option_type, strike, expiry
    )
    pending_sell_quantity = account_state.pending_order_quantity(
        ticker, "sell", option_type, strike, expiry
    )
    available_cash = max(account_state.buying_power, account_state.available_cash, 0.0)
    estimated_cost = price * max(quantity, 0)
    key = instrument_key(ticker, option_type, strike, expiry)
    portfolio_exposure = account_state.total_exposure({key: price})
    total_equity = max(account_state.total_equity, available_cash + portfolio_exposure, 0.0)
    current_position_exposure = held_quantity * price

    def reject(reason: str, code: str) -> TradeValidationResult:
        return TradeValidationResult(
            allowed=False,
            reason=reason,
            code=code,
            account_state=account_state,
            normalized_quantity=max(quantity, 0),
            available_cash=available_cash,
            held_quantity=held_quantity,
            pending_buy_quantity=pending_buy_quantity,
            pending_sell_quantity=pending_sell_quantity,
            estimated_cost=estimated_cost,
        )

    if side not in {"buy", "sell"}:
        return reject("Only buy and sell orders can be executed.", "unsupported_side")
    if not ticker:
        return reject("Ticker is required for execution.", "missing_ticker")
    if quantity <= 0:
        return reject("Order quantity must be greater than zero.", "invalid_quantity")
    if price <= 0:
        return reject("Current price must be greater than zero.", "invalid_price")

    if side == "buy":
        if rules.prevent_conflicting_open_orders and pending_sell_quantity > 0:
            return reject(
                f"Cannot buy {ticker}: a sell order is already pending.",
                "conflicting_open_order",
            )
        if rules.prevent_duplicate_orders and pending_buy_quantity > 0:
            return reject(
                f"Cannot buy {ticker}: a buy order is already pending.",
                "duplicate_open_order",
            )
        if not rules.allow_pyramiding and held_quantity > 0:
            return reject(
                f"Cannot buy {ticker}: position already exists and pyramiding is disabled.",
                "existing_position",
            )
        if rules.enforce_cash_check and estimated_cost > available_cash + 1e-9:
            return reject(
                f"Insufficient buying power for {ticker}: need {estimated_cost:.2f}, have {available_cash:.2f}.",
                "insufficient_cash",
            )
        if (
            rules.max_open_positions is not None
            and held_quantity <= 0
            and account_state.position_count() >= rules.max_open_positions
        ):
            return reject(
                f"Cannot buy {ticker}: max open positions ({rules.max_open_positions}) reached.",
                "max_open_positions",
            )
        if total_equity > 0 and rules.max_position_size_pct > 0:
            max_position_value = total_equity * rules.max_position_size_pct
            if current_position_exposure + estimated_cost > max_position_value + 1e-9:
                return reject(
                    f"Cannot buy {ticker}: position would exceed max size of {max_position_value:.2f}.",
                    "max_position_size",
                )
        if total_equity > 0 and rules.max_portfolio_exposure_pct > 0:
            max_portfolio_value = total_equity * rules.max_portfolio_exposure_pct
            if portfolio_exposure + estimated_cost > max_portfolio_value + 1e-9:
                return reject(
                    f"Cannot buy {ticker}: portfolio exposure would exceed {max_portfolio_value:.2f}.",
                    "max_portfolio_exposure",
                )

    if side == "sell":
        if rules.prevent_conflicting_open_orders and pending_buy_quantity > 0:
            return reject(
                f"Cannot sell {ticker}: a buy order is already pending.",
                "conflicting_open_order",
            )
        if rules.prevent_duplicate_orders and pending_sell_quantity > 0:
            return reject(
                f"Cannot sell {ticker}: a sell order is already pending.",
                "duplicate_open_order",
            )
        sellable_quantity = held_quantity - pending_sell_quantity
        if rules.enforce_holdings_check and sellable_quantity <= 0:
            return reject(
                f"Cannot sell {ticker}: no holdings are available.",
                "insufficient_holdings",
            )
        if rules.enforce_holdings_check and quantity > sellable_quantity:
            return reject(
                f"Cannot sell {ticker}: requested {quantity}, available {sellable_quantity}.",
                "insufficient_holdings",
            )
        if not rules.allow_partial_exit and quantity != held_quantity:
            return reject(
                f"Cannot sell {ticker}: partial exits are disabled.",
                "partial_exit_disabled",
            )

    return TradeValidationResult(
        allowed=True,
        reason="OK",
        code="ok",
        account_state=account_state,
        normalized_quantity=quantity,
        available_cash=available_cash,
        held_quantity=held_quantity,
        pending_buy_quantity=pending_buy_quantity,
        pending_sell_quantity=pending_sell_quantity,
        estimated_cost=estimated_cost,
    )
```

### .\stocktrader\backend\trading_engine\execution_engine.py

```python
"""Shared execution helpers that refresh account state before every trade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from backend.trading_engine.account_state import (
    AccountState,
    TradeValidationResult,
    ValidationRules,
    fetch_paper_account_state,
    fetch_real_account_state,
    validate_trade_against_account_state,
)


@dataclass(slots=True)
class ExecutionContext:
    accepted: bool
    status: str
    reason: str | None
    validation: TradeValidationResult
    account_state_before: AccountState
    account_state_after: AccountState
    broker_result: dict[str, Any] | None = None


class AccountStateExecutionEngine:
    """Centralizes pre/post refresh and validation for trade execution."""

    def __init__(self, validation_rules: ValidationRules | None = None) -> None:
        self.validation_rules = validation_rules or ValidationRules()

    def execute_with_adapter(
        self,
        adapter: Any,
        order_intent: Mapping[str, Any],
        current_price: float,
    ) -> ExecutionContext:
        before_state = fetch_real_account_state(adapter)
        validation = validate_trade_against_account_state(
            order_intent,
            before_state,
            current_price=current_price,
            rules=self.validation_rules,
        )
        if not validation.allowed:
            return ExecutionContext(
                accepted=False,
                status="rejected",
                reason=validation.reason,
                validation=validation,
                account_state_before=before_state,
                account_state_after=before_state,
                broker_result=None,
            )

        try:
            broker_result = adapter.place_order({**dict(order_intent), "current_price": current_price})
        except Exception as exc:
            return ExecutionContext(
                accepted=False,
                status="error",
                reason=str(exc),
                validation=validation,
                account_state_before=before_state,
                account_state_after=before_state,
                broker_result={"status": "error", "detail": str(exc)},
            )
        status = str(broker_result.get("status") or "unknown").lower()
        accepted = status not in {"failed", "rejected", "error"}
        after_state = fetch_real_account_state(adapter)
        return ExecutionContext(
            accepted=accepted,
            status=status,
            reason=None if accepted else str(broker_result.get("detail") or "Order execution failed"),
            validation=validation,
            account_state_before=before_state,
            account_state_after=after_state,
            broker_result=broker_result,
        )

    def validate_paper_order(
        self,
        account: Any,
        order_intent: Mapping[str, Any],
        current_price: float,
    ) -> tuple[AccountState, TradeValidationResult]:
        before_state = fetch_paper_account_state(account)
        validation = validate_trade_against_account_state(
            order_intent,
            before_state,
            current_price=current_price,
            rules=self.validation_rules,
        )
        return before_state, validation
```

### .\stocktrader\backend\trading_engine\angel_adapter.py

```python
"""Angel One SmartAPI adapter – paper + live implementations."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import numpy as np

from backend.core.config import settings
from backend.trading_engine.account_state import (
    AccountState,
    HoldingState,
    OrderState,
    holding_from_mapping,
    instrument_key,
    order_from_mapping,
)

logger = logging.getLogger(__name__)

PAPER_MODE = settings.PAPER_MODE
ANGEL_API_KEY = settings.ANGEL_API_KEY or ""
ANGEL_CLIENT_ID = settings.ANGEL_CLIENT_ID or ""
ANGEL_MPIN = settings.ANGEL_CLIENT_PIN or ""
ANGEL_TOTP_SECRET = settings.ANGEL_TOTP_SECRET or ""


class BrokerAdapter(Protocol):
    """Pluggable broker adapter interface."""

    def get_account_type(self) -> str:
        ...

    def place_order(self, order_intent: dict) -> dict:
        ...

    def cancel_order(self, order_id: str) -> dict:
        ...

    def get_order_status(self, order_id: str) -> dict:
        ...

    def get_ltp(self, ticker: str) -> dict:
        ...

    def get_balance(self) -> dict:
        ...

    def get_positions(self) -> list[dict]:
        ...

    def get_holdings(self) -> list[dict]:
        ...

    def get_open_orders(self) -> list[dict]:
        ...

    def fetch_account_state(self) -> AccountState:
        ...


@dataclass
class SimulatedFill:
    order_id: str
    ticker: str
    side: str
    quantity: int
    filled_price: float
    slippage: float
    latency_ms: float
    status: str
    timestamp: str
    option_type: str | None = None
    strike: float | None = None
    expiry: str | None = None
    strategy: str | None = None
    detail: str | None = None


_DEFAULT_PAPER_BALANCE = 100000.0


class AngelPaperAdapter:
    """Simulates Angel One SmartAPI in paper mode."""

    def __init__(
        self,
        slippage_pct: float = 0.001,
        option_slippage_pct: float = 0.003,
        max_retries: int = 3,
        rate_limit_delay: float = 0.1,
        simulated_latency_ms: float = 15.0,
        initial_balance: float | None = None,
    ) -> None:
        self.slippage_pct = slippage_pct
        self.option_slippage_pct = option_slippage_pct
        self.max_retries = max_retries
        self.rate_limit_delay = rate_limit_delay
        self.simulated_latency_ms = simulated_latency_ms
        self._orders: dict[str, dict[str, Any]] = {}
        self._positions: dict[str, dict[str, Any]] = {}
        self._initial_balance = initial_balance or _DEFAULT_PAPER_BALANCE
        self._available_cash: float = self._initial_balance
        self._used_margin: float = 0.0

    def get_account_type(self) -> str:
        return "paper"

    def place_order(self, order_intent: dict) -> dict:
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._execute(order_intent)
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Order attempt %d/%d failed: %s", attempt, self.max_retries, exc
                )
                if attempt < self.max_retries:
                    time.sleep(self.rate_limit_delay * attempt)
        return {"status": "failed", "detail": "Max retries exceeded"}

    def cancel_order(self, order_id: str) -> dict:
        if order_id in self._orders:
            self._orders[order_id]["status"] = "cancelled"
            return {"order_id": order_id, "status": "cancelled"}
        return {"order_id": order_id, "status": "not_found"}

    def get_order_status(self, order_id: str) -> dict:
        if order_id in self._orders:
            return self._orders[order_id]
        return {"order_id": order_id, "status": "not_found"}

    def get_ltp(self, ticker: str) -> dict:
        last_price = 100.0
        ticker_upper = str(ticker).upper()
        for order in reversed(list(self._orders.values())):
            if order.get("ticker") == ticker_upper and order.get("status") == "filled":
                last_price = order["filled_price"]
                break
        rng = np.random.default_rng()
        jitter = rng.normal(0, 0.002)
        ltp = round(last_price * (1 + jitter), 2)
        return {"ltp": ltp, "ticker": ticker_upper}

    def get_balance(self) -> dict:
        return {
            "available_cash": round(self._available_cash, 2),
            "buying_power": round(self._available_cash, 2),
            "used_margin": round(self._used_margin, 2),
            "total_equity": round(self._available_cash + self._used_margin, 2),
        }

    def get_positions(self) -> list[dict]:
        return [
            {
                "ticker": position["ticker"],
                "quantity": position["quantity"],
                "average_price": position["avg_price"],
                "option_type": position.get("option_type"),
                "strike": position.get("strike"),
                "expiry": position.get("expiry"),
            }
            for position in self._positions.values()
            if position["quantity"] > 0
        ]

    def get_holdings(self) -> list[dict]:
        return self.get_positions()

    def get_open_orders(self) -> list[dict]:
        return [
            order
            for order in self._orders.values()
            if str(order.get("status") or "").lower()
            not in {"filled", "cancelled", "canceled", "rejected", "failed"}
        ]

    def fetch_account_state(self) -> AccountState:
        holdings = {
            key: HoldingState(
                ticker=position["ticker"],
                quantity=position["quantity"],
                average_price=position["avg_price"],
                option_type=position.get("option_type"),
                strike=position.get("strike"),
                expiry=position.get("expiry"),
                source="paper_positions",
            )
            for key, position in self._positions.items()
            if position["quantity"] > 0
        }
        open_orders = [
            OrderState(
                order_id=str(order.get("order_id") or ""),
                ticker=str(order.get("ticker") or ""),
                side=str(order.get("side") or ""),
                quantity=int(order.get("quantity") or 0),
                status=str(order.get("status") or "open"),
                pending_quantity=int(order.get("pending_quantity") or order.get("quantity") or 0),
                average_price=float(order.get("filled_price") or order.get("price") or 0.0),
                option_type=order.get("option_type"),
                strike=order.get("strike"),
                expiry=order.get("expiry"),
                source="paper_orders",
            )
            for order in self.get_open_orders()
        ]
        balance = self.get_balance()
        return AccountState(
            account_type="paper",
            available_cash=float(balance["available_cash"]),
            buying_power=float(balance["buying_power"]),
            total_equity=float(balance["total_equity"]),
            holdings=holdings,
            open_positions={},
            open_orders=open_orders,
            raw={"orders": list(self._orders.values())},
        )

    def _position_key(self, intent: dict) -> str:
        return instrument_key(
            intent["ticker"],
            intent.get("option_type"),
            intent.get("strike"),
            intent.get("expiry"),
        )

    def _recompute_used_margin(self) -> None:
        self._used_margin = round(
            sum(position["quantity"] * position["avg_price"] for position in self._positions.values()),
            2,
        )

    def _execute(self, intent: dict) -> dict:
        order_id = str(uuid.uuid4())
        ticker = str(intent["ticker"]).upper()
        base_price = float(intent.get("current_price", 100.0))
        quantity = int(intent["quantity"])
        side = str(intent["side"]).lower()
        is_option = intent.get("option_type") is not None
        slip_pct = self.option_slippage_pct if is_option else self.slippage_pct

        rng = np.random.default_rng()
        effective_slip = slip_pct * rng.uniform(0.5, 1.5)
        filled_price = round(
            base_price * (1 + effective_slip if side == "buy" else 1 - effective_slip),
            2,
        )
        latency = round(self.simulated_latency_ms * rng.uniform(0.8, 1.5), 2)
        key = self._position_key(intent)
        order_value = filled_price * quantity

        if side == "buy" and order_value > self._available_cash:
            rejected = {
                "order_id": order_id,
                "ticker": ticker,
                "side": side,
                "quantity": quantity,
                "status": "rejected",
                "detail": f"Insufficient cash: need {order_value:.2f}, have {self._available_cash:.2f}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._orders[order_id] = rejected
            return rejected

        if side == "sell":
            position = self._positions.get(key)
            held_qty = int(position["quantity"]) if position else 0
            if held_qty < quantity:
                rejected = {
                    "order_id": order_id,
                    "ticker": ticker,
                    "side": side,
                    "quantity": quantity,
                    "status": "rejected",
                    "detail": f"Insufficient holdings: requested {quantity}, held {held_qty}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                self._orders[order_id] = rejected
                return rejected

        fill = SimulatedFill(
            order_id=order_id,
            ticker=ticker,
            side=side,
            quantity=quantity,
            filled_price=filled_price,
            slippage=round(abs(filled_price - base_price), 4),
            latency_ms=latency,
            status="filled",
            timestamp=datetime.now(timezone.utc).isoformat(),
            option_type=intent.get("option_type"),
            strike=intent.get("strike"),
            expiry=intent.get("expiry"),
            strategy=intent.get("strategy"),
        )
        result = asdict(fill)
        self._orders[order_id] = result

        if side == "buy":
            self._available_cash -= order_value
            position = self._positions.get(key)
            if position:
                total_qty = position["quantity"] + quantity
                weighted_cost = (position["avg_price"] * position["quantity"]) + (filled_price * quantity)
                position["avg_price"] = weighted_cost / total_qty if total_qty else position["avg_price"]
                position["quantity"] = total_qty
            else:
                self._positions[key] = {
                    "ticker": ticker,
                    "quantity": quantity,
                    "avg_price": filled_price,
                    "option_type": intent.get("option_type"),
                    "strike": intent.get("strike"),
                    "expiry": intent.get("expiry"),
                }
        else:
            position = self._positions[key]
            position["quantity"] -= quantity
            self._available_cash += order_value
            if position["quantity"] <= 0:
                del self._positions[key]

        self._recompute_used_margin()
        logger.info(
            "Simulated fill: %s %s %d @ %.2f (slip=%.4f, latency=%.1fms, bal=%.2f)",
            side,
            ticker,
            quantity,
            filled_price,
            fill.slippage,
            latency,
            self._available_cash,
        )
        return result


class AngelLiveAdapter:
    """Real Angel One SmartAPI adapter for live trading."""

    def __init__(self) -> None:
        if not all([ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_MPIN, ANGEL_TOTP_SECRET]):
            raise RuntimeError(
                "Missing AngelOne credentials. Set ANGEL_API_KEY, ANGEL_CLIENT_ID, "
                "ANGEL_MPIN, and ANGEL_TOTP_SECRET in your .env file."
            )
        self._smart_api = None
        self._connected = False

    def get_account_type(self) -> str:
        return "real"

    def _ensure_connected(self) -> None:
        if self._connected:
            return
        try:
            from SmartApi import SmartConnect
            import pyotp
        except ImportError as exc:
            raise ImportError(
                "Install smartapi-python and pyotp: pip install smartapi-python pyotp"
            ) from exc

        totp = pyotp.TOTP(ANGEL_TOTP_SECRET).now()
        self._smart_api = SmartConnect(api_key=ANGEL_API_KEY)
        data = self._smart_api.generateSession(ANGEL_CLIENT_ID, ANGEL_MPIN, totp)
        if not data or data.get("status") is False:
            raise RuntimeError(f"AngelOne login failed: {data}")
        self._connected = True
        logger.info("AngelOne SmartAPI session established for %s", ANGEL_CLIENT_ID)

    def place_order(self, order_intent: dict) -> dict:
        self._ensure_connected()
        params = {
            "variety": "NORMAL",
            "tradingsymbol": order_intent["ticker"],
            "symboltoken": order_intent.get("symbol_token", ""),
            "transactiontype": str(order_intent["side"]).upper(),
            "exchange": order_intent.get("exchange", "NSE"),
            "ordertype": order_intent.get("order_type", "MARKET").upper(),
            "producttype": order_intent.get("product_type", "INTRADAY"),
            "duration": "DAY",
            "quantity": str(order_intent["quantity"]),
        }
        if order_intent.get("limit_price"):
            params["price"] = str(order_intent["limit_price"])

        result = self._smart_api.placeOrder(params)
        order_id = result if isinstance(result, str) else str(result)
        logger.info("AngelOne order placed: %s", result)
        current_price = float(order_intent.get("current_price") or order_intent.get("limit_price") or 0.0)
        return {
            "order_id": order_id,
            "ticker": order_intent["ticker"],
            "side": order_intent["side"],
            "quantity": order_intent["quantity"],
            "filled_price": current_price,
            "status": "placed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def cancel_order(self, order_id: str) -> dict:
        self._ensure_connected()
        result = self._smart_api.cancelOrder(order_id, "NORMAL")
        return {"order_id": order_id, "status": "cancelled", "detail": result}

    def get_order_status(self, order_id: str) -> dict:
        self._ensure_connected()
        order_book = self._smart_api.orderBook()
        if order_book and order_book.get("data"):
            for order in order_book["data"]:
                if str(order.get("orderid")) == str(order_id):
                    return order
        return {"order_id": order_id, "status": "not_found"}

    def get_ltp(self, ticker: str) -> dict:
        self._ensure_connected()
        try:
            data = self._smart_api.ltpData("NSE", ticker, "")
            if data and data.get("data"):
                return {"ltp": float(data["data"].get("ltp", 0)), "ticker": ticker}
        except Exception as exc:
            logger.warning("LTP fetch failed for %s: %s", ticker, exc)
        return {"ltp": 0.0, "ticker": ticker}

    def get_balance(self) -> dict:
        self._ensure_connected()
        try:
            rms = self._smart_api.rmsLimit()
            data = rms.get("data", {}) if rms else {}
            available_cash = float(data.get("availablecash", 0) or 0)
            buying_power = float(data.get("availableintradaypayin", 0) or available_cash)
            total_equity = float(data.get("net", 0) or available_cash)
            return {
                "available_cash": available_cash,
                "buying_power": buying_power or available_cash,
                "used_margin": float(data.get("utiliseddebits", 0) or 0),
                "total_equity": total_equity or available_cash,
            }
        except Exception as exc:
            logger.warning("Balance fetch failed: %s", exc)
            return {"available_cash": 0.0, "buying_power": 0.0, "used_margin": 0.0, "total_equity": 0.0}

    def get_positions(self) -> list[dict]:
        self._ensure_connected()
        try:
            response = self._smart_api.position()
            data = response.get("data", []) if response else []
            return list(data or [])
        except Exception as exc:
            logger.warning("Position fetch failed: %s", exc)
            return []

    def get_holdings(self) -> list[dict]:
        self._ensure_connected()
        try:
            response = self._smart_api.holding()
            data = response.get("data", []) if response else []
            return list(data or [])
        except Exception as exc:
            logger.warning("Holdings fetch failed: %s", exc)
            return []

    def get_open_orders(self) -> list[dict]:
        self._ensure_connected()
        try:
            response = self._smart_api.orderBook()
            data = response.get("data", []) if response else []
            open_orders = []
            for order in data or []:
                status = str(order.get("orderstatus") or order.get("status") or "").lower()
                if status not in {"complete", "filled", "cancelled", "rejected"}:
                    open_orders.append(order)
            return open_orders
        except Exception as exc:
            logger.warning("Open order fetch failed: %s", exc)
            return []

    def fetch_account_state(self) -> AccountState:
        balance = self.get_balance()
        holdings = {
            position.key: position
            for row in self.get_holdings()
            if (position := holding_from_mapping(row, source="broker_holdings")) is not None
        }
        open_positions = {
            position.key: position
            for row in self.get_positions()
            if (position := holding_from_mapping(row, source="broker_positions")) is not None
        }
        open_orders = [
            order
            for row in self.get_open_orders()
            if (order := order_from_mapping(row, source="broker_orders")) is not None
        ]
        return AccountState(
            account_type="real",
            available_cash=float(balance.get("available_cash", 0.0)),
            buying_power=float(balance.get("buying_power", 0.0) or balance.get("available_cash", 0.0)),
            total_equity=float(balance.get("total_equity", 0.0) or balance.get("available_cash", 0.0)),
            holdings=holdings,
            open_positions=open_positions,
            open_orders=open_orders,
            raw={"balance": balance},
        )


def get_adapter() -> BrokerAdapter:
    """Return the appropriate broker adapter based on PAPER_MODE env var."""
    if PAPER_MODE:
        logger.info("Using paper-mode adapter")
        return AngelPaperAdapter()
    logger.info("Using LIVE AngelOne SmartAPI adapter")
    return AngelLiveAdapter()
```

### .\stocktrader\backend\paper_trading\paper_account.py

```python
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
        account = PaperAccount(cash=initial_cash, label=label)
        self._accounts[account.account_id] = account
        return account

    def get_account(self, account_id: str) -> PaperAccount | None:
        return self._accounts.get(account_id)

    def list_accounts(self) -> list[PaperAccount]:
        return list(self._accounts.values())

    def delete_account(self, account_id: str) -> bool:
        return self._accounts.pop(account_id, None) is not None
```

### .\stocktrader\backend\paper_trading\paper_executor.py

```python
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
```

### .\stocktrader\backend\services\risk_manager.py

```python
"""Risk management module for the trading bot.

Provides position sizing, daily loss limits, portfolio-level risk checks,
and trailing stop-loss logic for safe real-money trading.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.trading_engine.account_state import AccountState

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

    def sync_account_state(self, account_state: AccountState) -> None:
        """Replace cached risk state with the latest broker or paper state."""
        self.capital = max(account_state.buying_power, account_state.available_cash, 0.0)
        synced_positions: dict[str, PositionRisk] = {}
        for position in account_state.combined_positions().values():
            if position.sellable_quantity <= 0:
                continue
            synced = PositionRisk(
                ticker=position.ticker,
                side="buy",
                entry_price=position.average_price,
                quantity=position.sellable_quantity,
                highest_price=position.market_price or position.average_price,
                lowest_price=position.market_price or position.average_price,
            )
            synced.update_trailing_stop(
                position.market_price or position.average_price,
                self.config.trailing_stop_pct,
            )
            synced_positions[position.ticker] = synced
        self.positions = synced_positions
        logger.debug(
            "RiskManager synced from account state: capital=₹%.2f, positions=%d",
            self.capital,
            len(self.positions),
        )

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
```

### .\stocktrader\backend\api\routers\trade.py

```python
"""Trading endpoints: POST /trade_intent and POST /execute."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Header

from backend.api.schemas import (
    ExecuteRequest,
    ExecuteResponse,
    OptionStrategy,
    OptionType,
    OrderSide,
    TradeIntentRequest,
    TradeIntentResponse,
)
from backend.db.models import AuditLog, Fill, Order
from backend.db.session import SessionLocal
from backend.services.risk_manager import RiskConfig
from backend.trading_engine.account_state import ValidationRules
from backend.trading_engine.angel_adapter import get_adapter
from backend.trading_engine.execution_engine import AccountStateExecutionEngine

router = APIRouter(tags=["trading"])

_intents: dict[str, dict] = {}


def _get_adapter():
    """Lazy adapter accessor – avoids crash on import if credentials are bad."""
    global _adapter_instance
    try:
        return _adapter_instance
    except NameError:
        _adapter_instance = get_adapter()
        return _adapter_instance


def _get_execution_engine() -> AccountStateExecutionEngine:
    global _execution_engine
    try:
        return _execution_engine
    except NameError:
        rules = ValidationRules(
            allow_pyramiding=False,
            max_position_size_pct=RiskConfig().max_position_pct,
            max_portfolio_exposure_pct=RiskConfig().max_portfolio_risk_pct,
            max_open_positions=RiskConfig().max_open_positions,
        )
        _execution_engine = AccountStateExecutionEngine(validation_rules=rules)
        return _execution_engine


def _require_auth(authorization: str = Header(None)):
    """Simple bearer-token guard for protected endpoints."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")
    return authorization.split(" ", 1)[1]


def _load_current_price(adapter, intent: dict) -> float:
    if intent.get("limit_price"):
        return float(intent["limit_price"])
    ltp = adapter.get_ltp(intent["ticker"])
    if ltp and ltp.get("ltp"):
        return float(ltp["ltp"])
    return 100.0


def _persist_execution(
    *,
    execution_id: str,
    intent_id: str,
    intent: dict,
    result: dict,
    status: str,
) -> None:
    try:
        db = SessionLocal()
        order = Order(
            id=execution_id,
            intent_id=intent_id,
            ticker=intent["ticker"],
            side=intent["side"],
            quantity=intent["quantity"],
            order_type=intent["order_type"],
            limit_price=intent.get("limit_price"),
            status=status,
            option_type=intent.get("option_type"),
            strike=intent.get("strike"),
            expiry=intent.get("expiry"),
            strategy=intent.get("strategy"),
        )
        db.add(order)
        if status in {"filled", "placed"}:
            fill = Fill(
                order_id=execution_id,
                ticker=intent["ticker"],
                side=intent["side"],
                quantity=intent["quantity"],
                filled_price=float(result.get("filled_price") or intent.get("limit_price") or 0.0),
                slippage=float(result.get("slippage") or 0.0),
                latency_ms=float(result.get("latency_ms") or 0.0),
                commission=0,
                option_type=intent.get("option_type"),
                strike=intent.get("strike"),
                expiry=intent.get("expiry"),
                strategy=intent.get("strategy"),
            )
            db.add(fill)
        audit = AuditLog(
            event="ORDER_EXECUTION_ATTEMPT",
            entity_type="order",
            entity_id=execution_id,
            data=json.dumps(result),
        )
        db.add(audit)
        db.commit()
        db.close()
    except Exception:
        pass


@router.post("/trade_intent", response_model=TradeIntentResponse, status_code=201)
async def trade_intent(req: TradeIntentRequest):
    if req.order_type.value == "limit" and req.limit_price is None:
        raise HTTPException(status_code=400, detail="limit_price required for limit orders")

    intent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    estimated_cost = req.quantity * (req.limit_price or 100.0)

    _intents[intent_id] = {
        "ticker": req.ticker.upper(),
        "side": req.side.value,
        "quantity": req.quantity,
        "order_type": req.order_type.value,
        "limit_price": req.limit_price,
        "estimated_cost": estimated_cost,
        "status": "pending",
        "option_type": req.option_type.value if req.option_type else None,
        "strike": req.strike,
        "expiry": req.expiry,
        "strategy": req.strategy.value if req.strategy else None,
        "created_at": now,
    }

    return TradeIntentResponse(
        intent_id=uuid.UUID(intent_id),
        ticker=req.ticker.upper(),
        side=req.side,
        quantity=req.quantity,
        order_type=req.order_type,
        limit_price=req.limit_price,
        estimated_cost=estimated_cost,
        status="pending",
        option_type=req.option_type,
        strike=req.strike,
        expiry=req.expiry,
        strategy=req.strategy,
        created_at=now,
    )


@router.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest, token: str = Depends(_require_auth)):
    del token
    intent_id = str(req.intent_id)
    if intent_id not in _intents:
        raise HTTPException(status_code=404, detail="Trade intent not found")

    intent = _intents[intent_id]
    adapter = _get_adapter()
    current_price = _load_current_price(adapter, intent)
    outcome = _get_execution_engine().execute_with_adapter(
        adapter=adapter,
        order_intent={
            "ticker": intent["ticker"],
            "side": intent["side"],
            "quantity": intent["quantity"],
            "order_type": intent["order_type"],
            "limit_price": intent.get("limit_price"),
            "option_type": intent.get("option_type"),
            "strike": intent.get("strike"),
            "expiry": intent.get("expiry"),
            "strategy": intent.get("strategy"),
        },
        current_price=current_price,
    )

    if not outcome.accepted:
        raise HTTPException(status_code=422, detail=outcome.reason or "Order rejected")

    result = outcome.broker_result or {}
    execution_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    status = str(result.get("status") or "placed").lower()
    _persist_execution(
        execution_id=execution_id,
        intent_id=intent_id,
        intent=intent,
        result=result,
        status=status,
    )
    intent["status"] = status

    filled_price = float(result.get("filled_price") or current_price)
    return ExecuteResponse(
        execution_id=uuid.UUID(execution_id),
        intent_id=req.intent_id,
        ticker=intent["ticker"],
        side=OrderSide(intent["side"]),
        quantity=intent["quantity"],
        filled_price=filled_price,
        total_value=filled_price * intent["quantity"],
        slippage=float(result.get("slippage") or 0.0),
        latency_ms=float(result.get("latency_ms") or 0.0),
        status=status,
        option_type=OptionType(intent["option_type"]) if intent.get("option_type") else None,
        strike=intent.get("strike"),
        expiry=intent.get("expiry"),
        strategy=OptionStrategy(intent["strategy"]) if intent.get("strategy") else None,
        executed_at=now,
    )
```

### .\stocktrader\backend\api\routers\paper.py

```python
"""Paper trading API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.schemas import (
    EquityPoint,
    PaperAccountCreateRequest,
    PaperAccountResponse,
    PaperOrderIntentRequest,
    PaperReplayRequest,
)
from backend.paper_trading.paper_account import PaperAccountManager
from backend.paper_trading.paper_executor import PaperExecutor
from backend.paper_trading.paper_replayer import PaperReplayer
from backend.services.risk_manager import RiskConfig
from backend.trading_engine.account_state import ValidationRules, fetch_paper_account_state
from backend.trading_engine.execution_engine import AccountStateExecutionEngine

router = APIRouter(tags=["paper-trading"])

_account_manager = PaperAccountManager()
_executor = PaperExecutor()
_replayer = PaperReplayer(executor=_executor)


def _get_execution_engine() -> AccountStateExecutionEngine:
    global _execution_engine
    try:
        return _execution_engine
    except NameError:
        rules = ValidationRules(
            allow_pyramiding=False,
            max_position_size_pct=RiskConfig().max_position_pct,
            max_portfolio_exposure_pct=RiskConfig().max_portfolio_risk_pct,
            max_open_positions=RiskConfig().max_open_positions,
        )
        _execution_engine = AccountStateExecutionEngine(validation_rules=rules)
        return _execution_engine


@router.post("/paper/accounts", response_model=PaperAccountResponse, status_code=201)
async def create_paper_account(req: PaperAccountCreateRequest):
    account = _account_manager.create_account(
        initial_cash=req.initial_cash, label=req.label
    )
    return PaperAccountResponse(
        account_id=account.account_id,
        cash=account.cash,
        equity=account.equity,
        positions={k: v.quantity for k, v in account.positions.items()},
        created_at=account.created_at,
    )


@router.get("/paper/accounts")
async def list_paper_accounts():
    accounts = _account_manager.list_accounts()
    return [
        {
            "account_id": a.account_id,
            "cash": a.cash,
            "equity": a.equity,
            "label": a.label,
            "created_at": a.created_at.isoformat(),
        }
        for a in accounts
    ]


@router.get("/paper/{account_id}/equity", response_model=list[EquityPoint])
async def get_equity_curve(account_id: str):
    account = _account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return [EquityPoint(**pt) for pt in account.equity_curve]


@router.get("/paper/{account_id}/metrics")
async def get_account_metrics(account_id: str):
    account = _account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    trades = [trade for trade in account.trade_log if trade.get("side") == "sell"]
    if not trades:
        return {
            "sharpe": None, "sortino": None, "max_drawdown": None,
            "win_rate": None, "total_trades": 0, "net_pnl": 0,
        }

    pnls = [trade.get("realized_pnl", trade.get("pnl", 0)) for trade in trades]
    import numpy as np

    pnl_arr = np.array(pnls)
    wins = sum(1 for pnl in pnls if pnl > 0)
    net_pnl = float(pnl_arr.sum())

    if len(pnl_arr) > 1 and pnl_arr.std() > 0:
        sharpe = float(pnl_arr.mean() / pnl_arr.std() * np.sqrt(252))
        downside = pnl_arr[pnl_arr < 0]
        if len(downside) > 0 and downside.std() > 0:
            sortino = float(pnl_arr.mean() / downside.std() * np.sqrt(252))
        else:
            sortino = None
    else:
        sharpe = None
        sortino = None

    max_drawdown = None
    if account.equity_curve:
        equities = [pt["equity"] for pt in account.equity_curve]
        peak = equities[0]
        max_dd = 0
        for equity in equities:
            peak = max(peak, equity)
            drawdown = (peak - equity) / peak if peak > 0 else 0
            max_dd = max(max_dd, drawdown)
        max_drawdown = max_dd

    return {
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "win_rate": wins / len(trades) if trades else None,
        "total_trades": len(trades),
        "net_pnl": net_pnl,
    }


@router.post("/paper/{account_id}/order_intent")
async def paper_order_intent(account_id: str, req: PaperOrderIntentRequest):
    account = _account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    from backend.services.price_feed import PriceFeed

    feed = PriceFeed()
    tick = feed.get_latest_price(req.ticker)
    if not tick:
        raise HTTPException(status_code=404, detail=f"No price data for {req.ticker}")

    before_state, validation = _get_execution_engine().validate_paper_order(
        account=account,
        order_intent={
            "ticker": req.ticker.upper(),
            "side": req.side.value,
            "quantity": req.quantity,
            "option_type": req.option_type.value if req.option_type else None,
            "strike": req.strike,
            "expiry": req.expiry,
        },
        current_price=tick.price,
    )
    if not validation.allowed:
        raise HTTPException(status_code=422, detail=validation.reason)

    fill = _executor.execute_order(
        account=account,
        ticker=req.ticker.upper(),
        side=req.side.value,
        quantity=req.quantity,
        market_price=tick.price,
        option_type=req.option_type.value if req.option_type else None,
        strike=req.strike,
        expiry=req.expiry,
    )

    if not fill:
        raise HTTPException(
            status_code=422,
            detail=_executor.last_rejection_reason or "Order not filled",
        )

    after_state = fetch_paper_account_state(account)
    return {
        "ticker": fill.ticker,
        "side": fill.side,
        "quantity": fill.quantity,
        "fill_price": fill.fill_price,
        "slippage": fill.slippage,
        "commission": fill.commission,
        "status": fill.status,
        "timestamp": fill.timestamp.isoformat(),
        "account_state_before": {
            "available_cash": before_state.available_cash,
            "buying_power": before_state.buying_power,
            "total_equity": before_state.total_equity,
            "holdings": {
                key: {"quantity": position.quantity, "avg_price": position.average_price}
                for key, position in before_state.combined_positions().items()
            },
        },
        "account_state_after": {
            "available_cash": after_state.available_cash,
            "buying_power": after_state.buying_power,
            "total_equity": after_state.total_equity,
            "holdings": {
                key: {"quantity": position.quantity, "avg_price": position.average_price}
                for key, position in after_state.combined_positions().items()
            },
        },
    }


@router.post("/paper/{account_id}/replay")
async def replay_day(account_id: str, req: PaperReplayRequest):
    account = _account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    result = _replayer.replay_day(account, req.date)
    return result
```

### .\stocktrader\backend\api\routers\market.py

```python
"""Market status, account verification, and auto-trading bot endpoints."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from backend.core.config import settings
from backend.services.market_hours import get_market_status
from backend.services.risk_manager import RiskConfig, RiskManager
from backend.trading_engine.account_state import ValidationRules, fetch_real_account_state, validate_trade_against_account_state
from backend.trading_engine.execution_engine import AccountStateExecutionEngine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["market"])


@router.get("/market/status")
async def market_status():
    """Return current Indian stock market (NSE) status with countdown."""
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


def _get_angel_profile() -> dict[str, Any]:
    """Connect to AngelOne SmartAPI and fetch profile plus balance."""
    api_key = settings.ANGEL_API_KEY or ""
    client_id = settings.ANGEL_CLIENT_ID or ""
    mpin = settings.ANGEL_CLIENT_PIN or ""
    totp_secret = settings.ANGEL_TOTP_SECRET or ""

    if not all([api_key, client_id, mpin, totp_secret]):
        return {
            "status": "not_configured",
            "message": "AngelOne credentials are not set. Add ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_CLIENT_PIN, ANGEL_TOTP_SECRET to the backend environment.",
            "credentials_set": {
                "ANGEL_API_KEY": bool(api_key),
                "ANGEL_CLIENT_ID": bool(client_id),
                "ANGEL_CLIENT_PIN": bool(mpin),
                "ANGEL_TOTP_SECRET": bool(totp_secret),
            },
        }

    if settings.PAPER_MODE:
        paper_balance = 100000.0
        return {
            "status": "paper_mode",
            "message": "Running in Paper Mode. Set PAPER_MODE=false to connect to a real broker account.",
            "name": "Paper Trader",
            "client_id": client_id,
            "email": "paper@demo.local",
            "balance": paper_balance,
            "net": paper_balance,
            "available_margin": paper_balance,
            "credentials_set": {
                "ANGEL_API_KEY": True,
                "ANGEL_CLIENT_ID": True,
                "ANGEL_CLIENT_PIN": True,
                "ANGEL_TOTP_SECRET": True,
            },
        }

    try:
        from SmartApi import SmartConnect
        import pyotp

        totp = pyotp.TOTP(totp_secret).now()
        api = SmartConnect(api_key=api_key)
        session = api.generateSession(client_id, mpin, totp)

        if not session or session.get("status") is False:
            return {
                "status": "login_failed",
                "message": f"AngelOne login failed: {session.get('message', 'Unknown error')}",
                "credentials_set": {
                    "ANGEL_API_KEY": True,
                    "ANGEL_CLIENT_ID": True,
                    "ANGEL_CLIENT_PIN": True,
                    "ANGEL_TOTP_SECRET": True,
                },
            }

        profile = api.getProfile(session["data"]["refreshToken"])
        rms = api.rmsLimit()
        profile_data = profile.get("data", {}) if profile else {}
        rms_data = rms.get("data", {}) if rms else {}

        return {
            "status": "connected",
            "message": "Credentials verified - connected to AngelOne",
            "name": profile_data.get("name", "N/A"),
            "client_id": profile_data.get("clientcode", client_id),
            "email": profile_data.get("email", ""),
            "phone": profile_data.get("mobileno", ""),
            "broker": profile_data.get("broker", "ANGEL"),
            "balance": float(rms_data.get("availablecash", 0)),
            "net": float(rms_data.get("net", 0)),
            "available_margin": float(rms_data.get("availableintradaypayin", 0)),
            "utilized_margin": float(rms_data.get("utiliseddebits", 0)),
            "credentials_set": {
                "ANGEL_API_KEY": True,
                "ANGEL_CLIENT_ID": True,
                "ANGEL_CLIENT_PIN": True,
                "ANGEL_TOTP_SECRET": True,
            },
        }
    except ImportError:
        return {
            "status": "missing_package",
            "message": "Install smartapi-python: pip install smartapi-python pyotp",
        }
    except Exception as exc:  # pragma: no cover - broker dependent
        logger.exception("Account verification failed")
        return {"status": "error", "message": str(exc)}


@router.get("/account/profile")
async def account_profile():
    """Verify AngelOne credentials and fetch account name, balance, margin."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_angel_profile)


class TradingBot:
    """Automated trading bot that refreshes account state before every cycle."""

    def __init__(self) -> None:
        self.running = False
        self.watchlist: list[str] = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
        self.min_confidence: float = 0.7
        self.max_positions: int = 5
        self.position_size_pct: float = 0.10
        self.stop_loss_pct: float = 0.02
        self.take_profit_pct: float = 0.05
        self.cycle_interval: int = 60
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.trades_today: list[dict[str, Any]] = []
        self.total_pnl: float = 0.0
        self.total_charges: float = 0.0
        self.positions: dict[str, dict[str, Any]] = {}
        self.cycle_count: int = 0
        self.last_cycle: str | None = None
        self.errors: list[str] = []
        self._available_balance: float = 0.0
        self._total_equity: float = 0.0
        self._latest_account_state = None
        self._risk_mgr: RiskManager | None = None
        self._adapter: Any = None
        self._execution_engine = AccountStateExecutionEngine(self._validation_rules())
        self._paused_for_market_close: bool = False
        self._consent_pending: bool = False
        self._consent_requested_at: float | None = None
        self._auto_resume_seconds: int = 600

    def _validation_rules(self) -> ValidationRules:
        config = RiskConfig(
            max_position_pct=self.position_size_pct,
            max_portfolio_risk_pct=0.30,
            max_open_positions=self.max_positions,
        )
        return ValidationRules(
            allow_pyramiding=False,
            prevent_duplicate_orders=True,
            prevent_conflicting_open_orders=True,
            max_position_size_pct=config.max_position_pct,
            max_portfolio_exposure_pct=config.max_portfolio_risk_pct,
            max_open_positions=config.max_open_positions,
        )

    def _get_risk_manager(self) -> RiskManager:
        if self._risk_mgr is None:
            config = RiskConfig(
                max_position_pct=self.position_size_pct,
                max_daily_loss=5000.0,
                max_daily_loss_pct=0.02,
                trailing_stop_pct=0.015,
                min_risk_reward_ratio=2.0,
                max_open_positions=self.max_positions,
                cooldown_after_loss=2,
            )
            capital = self._available_balance or 100000.0
            self._risk_mgr = RiskManager(capital, config)
        return self._risk_mgr

    def _get_adapter(self):
        if self._adapter is None:
            from backend.trading_engine.angel_adapter import get_adapter

            self._adapter = get_adapter()
        return self._adapter

    def _refresh_account_state(self):
        adapter = self._get_adapter()
        state = fetch_real_account_state(adapter)
        self._latest_account_state = state
        self._available_balance = state.available_cash
        self._total_equity = state.total_equity
        self._get_risk_manager().sync_account_state(state)
        return state

    def _sync_bot_positions(self, account_state) -> None:
        for ticker in list(self.positions.keys()):
            if not account_state.has_position(ticker) and not account_state.has_open_order(ticker):
                del self.positions[ticker]
                continue
            held_qty = account_state.held_quantity(ticker)
            if held_qty > 0:
                self.positions[ticker]["quantity"] = held_qty
                avg_price = account_state.average_buy_price(ticker)
                if avg_price > 0:
                    self.positions[ticker]["entry_price"] = avg_price

    @property
    def status(self) -> dict:
        risk = self._get_risk_manager().status if self._risk_mgr else {}
        auto_resume_in = None
        if self._consent_pending and self._consent_requested_at:
            elapsed = time.time() - self._consent_requested_at
            auto_resume_in = int(max(0, self._auto_resume_seconds - elapsed))
        return {
            "running": self.running,
            "paused": self._paused_for_market_close,
            "consent_pending": self._consent_pending,
            "auto_resume_in": auto_resume_in,
            "watchlist": self.watchlist,
            "min_confidence": self.min_confidence,
            "max_positions": self.max_positions,
            "position_size_pct": self.position_size_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "cycle_interval": self.cycle_interval,
            "cycle_count": self.cycle_count,
            "last_cycle": self.last_cycle,
            "available_balance": round(self._available_balance, 2),
            "total_equity": round(self._total_equity, 2),
            "account_state_updated_at": self._latest_account_state.last_updated.isoformat() if self._latest_account_state else None,
            "active_positions": len(self.positions),
            "positions": self.positions,
            "trades_today": self.trades_today[-20:],
            "total_pnl": round(self.total_pnl, 2),
            "total_charges": round(self.total_charges, 2),
            "net_pnl": round(self.total_pnl - self.total_charges, 2),
            "risk": risk,
            "errors": self.errors[-10:],
        }

    def start(self, config: dict | None = None) -> dict:
        if self.running:
            return {"status": "already_running", "message": "Bot is already running"}

        if config:
            self.watchlist = config.get("watchlist", self.watchlist)
            self.min_confidence = config.get("min_confidence", self.min_confidence)
            self.max_positions = config.get("max_positions", self.max_positions)
            self.position_size_pct = config.get("position_size_pct", self.position_size_pct)
            self.stop_loss_pct = config.get("stop_loss_pct", self.stop_loss_pct)
            self.take_profit_pct = config.get("take_profit_pct", self.take_profit_pct)
            self.cycle_interval = config.get("cycle_interval", self.cycle_interval)

        self.running = True
        self._stop_event.clear()
        self._paused_for_market_close = False
        self._consent_pending = False
        self._consent_requested_at = None
        self.trades_today = []
        self.total_pnl = 0.0
        self.total_charges = 0.0
        self.cycle_count = 0
        self.errors = []
        self.positions = {}
        self._risk_mgr = None
        self._adapter = None
        self._execution_engine = AccountStateExecutionEngine(self._validation_rules())

        try:
            self._refresh_account_state()
        except Exception as exc:
            self.running = False
            return {"status": "error", "message": f"Cannot start bot: {exc}"}

        if self._available_balance <= 0:
            self.running = False
            return {
                "status": "error",
                "message": "Cannot start bot: available balance is ₹0. Check broker or paper account funding.",
            }

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Trading bot started with watchlist: %s", self.watchlist)
        return {"status": "started", "message": "Bot started", "config": self.status}

    def stop(self) -> dict:
        if not self.running:
            return {"status": "not_running", "message": "Bot is not running"}
        self._stop_event.set()
        self.running = False
        self._paused_for_market_close = False
        self._consent_pending = False
        self._consent_requested_at = None
        logger.info("Trading bot stopped. Cycles: %d, PnL: %.2f", self.cycle_count, self.total_pnl)
        return {
            "status": "stopped",
            "message": "Bot stopped",
            "cycles": self.cycle_count,
            "total_pnl": round(self.total_pnl, 2),
            "trades": len(self.trades_today),
        }

    def _run_loop(self) -> None:
        was_market_open = False
        while not self._stop_event.is_set():
            try:
                market = get_market_status()
                is_open = market.phase.value in ("open", "pre_open")

                if is_open and self._paused_for_market_close:
                    self._check_market_reopen()

                if is_open:
                    if self._consent_pending:
                        elapsed = time.time() - (self._consent_requested_at or 0)
                        if elapsed >= self._auto_resume_seconds:
                            logger.info("Auto-resuming bot after %ds", self._auto_resume_seconds)
                            self._consent_pending = False
                            self._paused_for_market_close = False
                        else:
                            self._stop_event.wait(5)
                            continue
                    if self._paused_for_market_close:
                        self._stop_event.wait(5)
                        continue
                    was_market_open = True
                    self._run_cycle()
                else:
                    if was_market_open and not self._paused_for_market_close:
                        self._paused_for_market_close = True
                        logger.info("Market closed - bot paused, waiting for next session")
                    was_market_open = False
                    self._stop_event.wait(30)
                    continue
            except Exception as exc:  # pragma: no cover - long-running path
                msg = f"Bot cycle error: {exc}"
                logger.exception(msg)
                self.errors.append(msg)
            self._stop_event.wait(self.cycle_interval)

    def _check_market_reopen(self) -> None:
        if self._paused_for_market_close and not self._consent_pending:
            self._consent_pending = True
            self._consent_requested_at = time.time()
            logger.info("Market reopened - requesting user consent")

    def grant_consent(self) -> dict:
        if not self._consent_pending:
            return {"status": "no_consent_needed", "message": "No consent request pending"}
        self._consent_pending = False
        self._paused_for_market_close = False
        self._consent_requested_at = None
        logger.info("User granted consent - bot resuming")
        return {"status": "resumed", "message": "Trading resumed with user consent"}

    def decline_consent(self) -> dict:
        if not self._consent_pending:
            return {"status": "no_consent_needed", "message": "No consent request pending"}
        self._consent_pending = False
        self._paused_for_market_close = False
        self._consent_requested_at = None
        return self.stop()

    def _run_cycle(self) -> None:
        from backend.services.brokerage_calculator import TradeType, estimate_breakeven_move, net_pnl_after_charges
        from backend.services.model_manager import ModelManager

        self.cycle_count += 1
        self.last_cycle = datetime.now(timezone.utc).isoformat()
        adapter = self._get_adapter()
        model_manager = ModelManager()
        risk = self._get_risk_manager()
        risk.tick_cycle()

        account_state = self._refresh_account_state()
        self._sync_bot_positions(account_state)

        for ticker in list(self.positions.keys()):
            self._check_exit(ticker, adapter)

        account_state = self._refresh_account_state()
        self._sync_bot_positions(account_state)

        for ticker in self.watchlist:
            if len(self.positions) >= self.max_positions:
                break
            if account_state.has_position(ticker) or account_state.has_open_order(ticker):
                continue

            try:
                prediction = model_manager.predict(ticker, horizon_days=1)
                if not prediction:
                    continue
                action = prediction.get("action", "hold")
                confidence = float(prediction.get("confidence", 0))
                if action != "buy" or confidence < self.min_confidence:
                    continue

                price = float(prediction.get("close", prediction.get("predicted_price", 0)) or 0)
                if price <= 0:
                    continue

                max_trade_value = min(account_state.buying_power, account_state.available_cash) * self.position_size_pct
                if max_trade_value < price:
                    continue
                quantity = max(1, int(max_trade_value / price))

                breakeven_move = estimate_breakeven_move(price, quantity, TradeType.INTRADAY)
                signal_return = abs(prediction.get("net_expected_return", prediction.get("expected_return", 0.0)))
                expected_profit = price * signal_return
                if expected_profit < breakeven_move:
                    continue

                validation = validate_trade_against_account_state(
                    {"ticker": ticker, "side": "buy", "quantity": quantity},
                    account_state,
                    current_price=price,
                    rules=self._validation_rules(),
                )
                if not validation.allowed:
                    continue

                allowed, reason = risk.can_open_position(ticker, price, quantity)
                if not allowed:
                    logger.debug("Risk blocked %s: %s", ticker, reason)
                    continue

                outcome = self._execution_engine.execute_with_adapter(
                    adapter=adapter,
                    order_intent={
                        "ticker": ticker,
                        "side": "buy",
                        "quantity": quantity,
                        "order_type": "market",
                    },
                    current_price=price,
                )
                if not outcome.accepted:
                    self.errors.append(outcome.reason or f"Entry rejected for {ticker}")
                    continue

                result = outcome.broker_result or {}
                filled_price = float(result.get("filled_price") or price)
                account_state = outcome.account_state_after
                self._sync_bot_positions(account_state)
                held_qty = account_state.held_quantity(ticker)
                if held_qty > 0:
                    self.positions[ticker] = {
                        "side": "buy",
                        "quantity": held_qty,
                        "entry_price": account_state.average_buy_price(ticker) or filled_price,
                        "current_price": filled_price,
                        "pnl": 0.0,
                        "net_pnl": 0.0,
                        "order_id": result.get("order_id", ""),
                        "entered_at": datetime.now(timezone.utc).isoformat(),
                    }

                self.trades_today.append(
                    {
                        "ticker": ticker,
                        "action": "ENTRY",
                        "side": "buy",
                        "quantity": quantity,
                        "price": filled_price,
                        "confidence": confidence,
                        "status": result.get("status", "placed"),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                logger.info("Bot entered buy %s @ ₹%.2f (conf=%.2f)", ticker, filled_price, confidence)
            except Exception as exc:  # pragma: no cover - long-running path
                self.errors.append(f"Predict/trade {ticker}: {exc}")

    def _check_exit(self, ticker: str, adapter: Any) -> None:
        from backend.services.brokerage_calculator import TradeType, net_pnl_after_charges

        position = self.positions.get(ticker)
        if not position:
            return

        account_state = self._refresh_account_state()
        if not account_state.has_position(ticker):
            del self.positions[ticker]
            return

        held_qty = account_state.held_quantity(ticker)
        if held_qty <= 0:
            del self.positions[ticker]
            return

        try:
            current = float(adapter.get_ltp(ticker).get("ltp") or position["entry_price"])
        except Exception:
            current = float(position["current_price"])

        position["current_price"] = round(current, 2)
        position["quantity"] = held_qty
        entry = float(position["entry_price"])
        gross_pnl = (current - entry) * held_qty
        pnl_pct = (current - entry) / entry if entry > 0 else 0.0
        net_pnl = net_pnl_after_charges(entry, current, held_qty, TradeType.INTRADAY)
        position["pnl"] = round(gross_pnl, 2)
        position["net_pnl"] = round(net_pnl, 2)

        risk = self._get_risk_manager()
        exit_reason = None
        should_trail, trail_reason = risk.check_exit(ticker, current)
        if should_trail:
            exit_reason = trail_reason
        if exit_reason is None and pnl_pct <= -self.stop_loss_pct:
            exit_reason = "STOP_LOSS"
        if exit_reason is None and pnl_pct >= self.take_profit_pct:
            exit_reason = "TAKE_PROFIT"
        if exit_reason is None:
            return

        validation = validate_trade_against_account_state(
            {"ticker": ticker, "side": "sell", "quantity": held_qty},
            account_state,
            current_price=current,
            rules=self._validation_rules(),
        )
        if not validation.allowed:
            self.errors.append(validation.reason)
            return

        outcome = self._execution_engine.execute_with_adapter(
            adapter=adapter,
            order_intent={"ticker": ticker, "side": "sell", "quantity": held_qty, "order_type": "market"},
            current_price=current,
        )
        if not outcome.accepted:
            self.errors.append(outcome.reason or f"Exit rejected for {ticker}")
            return

        remaining_qty = outcome.account_state_after.held_quantity(ticker)
        if remaining_qty >= held_qty and outcome.account_state_after.has_open_order(ticker, "sell"):
            self.positions[ticker]["pending_exit"] = True
            self.positions[ticker]["exit_order_id"] = outcome.broker_result.get("order_id", "") if outcome.broker_result else ""
            logger.info("Exit order placed for %s; waiting for broker state confirmation", ticker)
            return

        charges = gross_pnl - net_pnl
        self.total_pnl += gross_pnl
        self.total_charges += charges
        risk.register_exit(ticker, net_pnl, exit_reason)
        self.trades_today.append(
            {
                "ticker": ticker,
                "action": exit_reason,
                "side": "sell",
                "quantity": held_qty,
                "price": round(current, 2),
                "gross_pnl": round(gross_pnl, 2),
                "charges": round(charges, 2),
                "net_pnl": round(net_pnl, 2),
                "status": outcome.status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        if not outcome.account_state_after.has_position(ticker):
            del self.positions[ticker]
        else:
            self.positions[ticker]["quantity"] = outcome.account_state_after.held_quantity(ticker)
            self.positions[ticker]["entry_price"] = (
                outcome.account_state_after.average_buy_price(ticker) or self.positions[ticker]["entry_price"]
            )
            self.positions[ticker].pop("pending_exit", None)
            self.positions[ticker].pop("exit_order_id", None)


_bot = TradingBot()


@router.post("/bot/start")
async def bot_start(config: dict | None = None):
    return _bot.start(config)


@router.post("/bot/stop")
async def bot_stop():
    return _bot.stop()


@router.get("/bot/status")
async def bot_status():
    return _bot.status


@router.put("/bot/config")
async def bot_config(config: dict):
    if config.get("watchlist"):
        _bot.watchlist = config["watchlist"]
    if config.get("min_confidence") is not None:
        _bot.min_confidence = config["min_confidence"]
    if config.get("max_positions") is not None:
        _bot.max_positions = config["max_positions"]
    if config.get("position_size_pct") is not None:
        _bot.position_size_pct = config["position_size_pct"]
    if config.get("stop_loss_pct") is not None:
        _bot.stop_loss_pct = config["stop_loss_pct"]
    if config.get("take_profit_pct") is not None:
        _bot.take_profit_pct = config["take_profit_pct"]
    if config.get("cycle_interval") is not None:
        _bot.cycle_interval = config["cycle_interval"]
    _bot._execution_engine = AccountStateExecutionEngine(_bot._validation_rules())
    if _bot._risk_mgr is not None:
        _bot._risk_mgr.config.max_position_pct = _bot.position_size_pct
        _bot._risk_mgr.config.max_open_positions = _bot.max_positions
    return {"status": "updated", "config": _bot.status}


@router.post("/bot/consent")
async def bot_consent(action: dict | None = None):
    resume = True
    if action and "resume" in action:
        resume = action["resume"]
    if resume:
        return _bot.grant_consent()
    return _bot.decline_consent()
```

### .\stocktrader\backend\tests\test_trading.py

```python
"""Tests for account-state-aware trading safeguards."""

from __future__ import annotations

from types import SimpleNamespace

from backend.trading_engine.account_state import (
    AccountState,
    HoldingState,
    OrderState,
    ValidationRules,
    validate_trade_against_account_state,
)
from backend.trading_engine.angel_adapter import AngelPaperAdapter
from backend.trading_engine.execution_engine import AccountStateExecutionEngine


def _account_state(
    *,
    cash: float = 100000.0,
    holdings: dict[str, HoldingState] | None = None,
    open_orders: list[OrderState] | None = None,
) -> AccountState:
    return AccountState(
        account_type="paper",
        available_cash=cash,
        buying_power=cash,
        total_equity=cash + sum(position.exposure for position in (holdings or {}).values()),
        holdings=holdings or {},
        open_positions={},
        open_orders=open_orders or [],
    )


def test_validate_buy_with_enough_cash():
    result = validate_trade_against_account_state(
        {"ticker": "RELIANCE", "side": "buy", "quantity": 10},
        _account_state(cash=5000.0),
        current_price=100.0,
        rules=ValidationRules(max_position_size_pct=1.0, max_portfolio_exposure_pct=1.0),
    )
    assert result.allowed is True


def test_validate_buy_with_insufficient_cash():
    result = validate_trade_against_account_state(
        {"ticker": "RELIANCE", "side": "buy", "quantity": 100},
        _account_state(cash=1000.0),
        current_price=50.0,
        rules=ValidationRules(max_position_size_pct=1.0, max_portfolio_exposure_pct=1.0),
    )
    assert result.allowed is False
    assert result.code == "insufficient_cash"


def test_validate_sell_with_sufficient_holdings():
    state = _account_state(
        cash=1000.0,
        holdings={"RELIANCE": HoldingState(ticker="RELIANCE", quantity=5, average_price=100.0)},
    )
    result = validate_trade_against_account_state(
        {"ticker": "RELIANCE", "side": "sell", "quantity": 5},
        state,
        current_price=120.0,
    )
    assert result.allowed is True


def test_validate_sell_without_holdings():
    result = validate_trade_against_account_state(
        {"ticker": "RELIANCE", "side": "sell", "quantity": 1},
        _account_state(cash=1000.0),
        current_price=100.0,
    )
    assert result.allowed is False
    assert result.code == "insufficient_holdings"


def test_validate_duplicate_buy_prevention():
    state = _account_state(
        cash=10000.0,
        open_orders=[
            OrderState(
                order_id="open-buy-1",
                ticker="RELIANCE",
                side="buy",
                quantity=5,
                status="open",
                pending_quantity=5,
            )
        ],
    )
    result = validate_trade_against_account_state(
        {"ticker": "RELIANCE", "side": "buy", "quantity": 2},
        state,
        current_price=100.0,
    )
    assert result.allowed is False
    assert result.code == "duplicate_open_order"


def test_execution_engine_refreshes_account_state_before_execution():
    class FakeAdapter:
        def __init__(self) -> None:
            self.fetch_calls = 0
            self.place_calls = 0
            self.holdings: dict[str, HoldingState] = {}

        def fetch_account_state(self) -> AccountState:
            self.fetch_calls += 1
            return AccountState(
                account_type="real",
                available_cash=10000.0,
                buying_power=10000.0,
                total_equity=10000.0,
                holdings=dict(self.holdings),
                open_positions={},
                open_orders=[],
            )

        def place_order(self, order_intent: dict) -> dict:
            self.place_calls += 1
            self.holdings["RELIANCE"] = HoldingState(
                ticker="RELIANCE",
                quantity=order_intent["quantity"],
                average_price=order_intent["current_price"],
            )
            return {
                "order_id": "broker-1",
                "status": "filled",
                "filled_price": order_intent["current_price"],
                "ticker": order_intent["ticker"],
                "quantity": order_intent["quantity"],
            }

    engine = AccountStateExecutionEngine(
        ValidationRules(max_position_size_pct=1.0, max_portfolio_exposure_pct=1.0)
    )
    adapter = FakeAdapter()
    outcome = engine.execute_with_adapter(
        adapter,
        {"ticker": "RELIANCE", "side": "buy", "quantity": 5, "order_type": "market"},
        current_price=100.0,
    )
    assert outcome.accepted is True
    assert adapter.place_calls == 1
    assert adapter.fetch_calls >= 2
    assert outcome.account_state_after.held_quantity("RELIANCE") == 5


def test_execution_engine_uses_adapter_state_methods_when_fetch_account_state_missing():
    class LegacyAdapter:
        def __init__(self) -> None:
            self.balance_calls = 0
            self.holdings_calls = 0
            self.positions_calls = 0
            self.open_orders_calls = 0
            self.place_calls = 0

        def get_balance(self) -> dict:
            self.balance_calls += 1
            return {"available_cash": 10000.0, "buying_power": 10000.0, "total_equity": 10000.0}

        def get_holdings(self) -> list[dict]:
            self.holdings_calls += 1
            return []

        def get_positions(self) -> list[dict]:
            self.positions_calls += 1
            return []

        def get_open_orders(self) -> list[dict]:
            self.open_orders_calls += 1
            return []

        def place_order(self, order_intent: dict) -> dict:
            self.place_calls += 1
            return {
                "order_id": "legacy-1",
                "status": "filled",
                "filled_price": order_intent["current_price"],
                "ticker": order_intent["ticker"],
                "quantity": order_intent["quantity"],
            }

    engine = AccountStateExecutionEngine(
        ValidationRules(max_position_size_pct=1.0, max_portfolio_exposure_pct=1.0)
    )
    adapter = LegacyAdapter()
    outcome = engine.execute_with_adapter(
        adapter,
        {"ticker": "INFY", "side": "buy", "quantity": 3, "order_type": "market"},
        current_price=100.0,
    )
    assert outcome.accepted is True
    assert adapter.place_calls == 1
    assert adapter.balance_calls >= 1
    assert adapter.holdings_calls >= 1
    assert adapter.positions_calls >= 1
    assert adapter.open_orders_calls >= 1


def test_adapter_buy_and_sell_enforce_account_state():
    adapter = AngelPaperAdapter(slippage_pct=0.0, option_slippage_pct=0.0)
    buy = adapter.place_order(
        {
            "ticker": "TEST",
            "side": "buy",
            "quantity": 10,
            "order_type": "market",
            "current_price": 100.0,
        }
    )
    assert buy["status"] == "filled"
    sell = adapter.place_order(
        {
            "ticker": "TEST",
            "side": "sell",
            "quantity": 10,
            "order_type": "market",
            "current_price": 101.0,
        }
    )
    assert sell["status"] == "filled"


def test_adapter_rejects_sell_without_holdings():
    adapter = AngelPaperAdapter(slippage_pct=0.0, option_slippage_pct=0.0)
    result = adapter.place_order(
        {
            "ticker": "TEST",
            "side": "sell",
            "quantity": 1,
            "order_type": "market",
            "current_price": 100.0,
        }
    )
    assert result["status"] == "rejected"


def test_trade_execute_route_rejects_duplicate_position(auth_client, monkeypatch):
    from backend.api.routers import trade as trade_router

    class FakeAdapter:
        def fetch_account_state(self) -> AccountState:
            return AccountState(
                account_type="real",
                available_cash=10000.0,
                buying_power=10000.0,
                total_equity=10000.0,
                holdings={"RELIANCE": HoldingState(ticker="RELIANCE", quantity=2, average_price=100.0)},
                open_positions={},
                open_orders=[],
            )

        def get_ltp(self, ticker: str) -> dict:
            return {"ltp": 100.0, "ticker": ticker}

        def place_order(self, order_intent: dict) -> dict:  # pragma: no cover - should never be called
            raise AssertionError("place_order should not be called when account state blocks the trade")

    monkeypatch.setattr(trade_router, "_get_adapter", lambda: FakeAdapter())
    create = auth_client.post(
        "/api/v1/trade_intent",
        json={"ticker": "RELIANCE", "side": "buy", "quantity": 1, "order_type": "market"},
    )
    assert create.status_code == 201
    execute = auth_client.post(
        "/api/v1/execute",
        json={"intent_id": create.json()["intent_id"]},
    )
    assert execute.status_code == 422
    assert "pyramiding" in execute.json()["detail"].lower() or "position already exists" in execute.json()["detail"].lower()
```

### .\stocktrader\backend\tests\test_paper_api.py

```python
from __future__ import annotations

from types import SimpleNamespace


def _mock_price(monkeypatch, price: float = 100.0):
    from backend.services import price_feed

    monkeypatch.setattr(
        price_feed.PriceFeed,
        "get_latest_price",
        lambda self, ticker: SimpleNamespace(price=price, symbol=ticker),
    )


def test_create_and_list_paper_accounts(client):
    create = client.post("/api/v1/paper/accounts", json={"initial_cash": 50000, "label": "demo"})
    assert create.status_code == 201
    account_id = create.json()["account_id"]

    listing = client.get("/api/v1/paper/accounts")
    assert listing.status_code == 200
    assert any(account["account_id"] == account_id for account in listing.json())


def test_paper_buy_updates_state_after_fill(client, monkeypatch):
    _mock_price(monkeypatch, price=100.0)
    create = client.post("/api/v1/paper/accounts", json={"initial_cash": 10000})
    account_id = create.json()["account_id"]

    response = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "RELIANCE", "side": "buy", "quantity": 10, "order_type": "market"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "filled"
    assert payload["account_state_after"]["holdings"]["RELIANCE"]["quantity"] == 10
    assert payload["account_state_after"]["available_cash"] < payload["account_state_before"]["available_cash"]


def test_paper_buy_rejects_insufficient_cash(client, monkeypatch):
    _mock_price(monkeypatch, price=100.0)
    create = client.post("/api/v1/paper/accounts", json={"initial_cash": 100})
    account_id = create.json()["account_id"]

    response = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "RELIANCE", "side": "buy", "quantity": 10, "order_type": "market"},
    )
    assert response.status_code == 422
    assert "insufficient" in response.json()["detail"].lower()


def test_paper_sell_rejects_without_holdings(client, monkeypatch):
    _mock_price(monkeypatch, price=100.0)
    create = client.post("/api/v1/paper/accounts", json={"initial_cash": 10000})
    account_id = create.json()["account_id"]

    response = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "RELIANCE", "side": "sell", "quantity": 1, "order_type": "market"},
    )
    assert response.status_code == 422
    assert "holdings" in response.json()["detail"].lower()


def test_paper_duplicate_buy_is_blocked(client, monkeypatch):
    _mock_price(monkeypatch, price=100.0)
    create = client.post("/api/v1/paper/accounts", json={"initial_cash": 10000})
    account_id = create.json()["account_id"]

    first = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "INFY", "side": "buy", "quantity": 5, "order_type": "market"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "INFY", "side": "buy", "quantity": 1, "order_type": "market"},
    )
    assert second.status_code == 422
    assert "position already exists" in second.json()["detail"].lower() or "pyramiding" in second.json()["detail"].lower()


def test_paper_sell_updates_holdings_and_cash(client, monkeypatch):
    _mock_price(monkeypatch, price=100.0)
    create = client.post("/api/v1/paper/accounts", json={"initial_cash": 10000})
    account_id = create.json()["account_id"]

    buy = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "TCS", "side": "buy", "quantity": 5, "order_type": "market"},
    )
    assert buy.status_code == 200

    _mock_price(monkeypatch, price=110.0)
    sell = client.post(
        f"/api/v1/paper/{account_id}/order_intent",
        json={"ticker": "TCS", "side": "sell", "quantity": 5, "order_type": "market"},
    )
    assert sell.status_code == 200
    payload = sell.json()
    assert "TCS" not in payload["account_state_after"]["holdings"]
    assert payload["account_state_after"]["available_cash"] > payload["account_state_before"]["available_cash"]
```

