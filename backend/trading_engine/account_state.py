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
