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

    def supports_option_contracts(self) -> bool:
        ...

    def search_instruments(self, exchange: str, search_text: str) -> list[dict]:
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

    def supports_option_contracts(self) -> bool:
        return True

    def search_instruments(self, exchange: str, search_text: str) -> list[dict]:
        del exchange, search_text
        return []

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

    def supports_option_contracts(self) -> bool:
        # Contract lookup is available, but live options stay fail-closed until
        # broker position/order normalization is fully validated end to end.
        return False

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
            "tradingsymbol": order_intent.get("tradingsymbol", order_intent["ticker"]),
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

    def search_instruments(self, exchange: str, search_text: str) -> list[dict]:
        self._ensure_connected()
        try:
            response = self._smart_api.searchScrip(exchange, search_text)
            data = response.get("data", []) if response else []
            return list(data or [])
        except Exception as exc:
            logger.warning("Instrument search failed for %s on %s: %s", search_text, exchange, exc)
            return []

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


_adapter_instance: BrokerAdapter | None = None
_adapter_mode: str | None = None


def reset_adapter_cache() -> None:
    """Reset the shared adapter instance used across trading services."""
    global _adapter_instance, _adapter_mode
    _adapter_instance = None
    _adapter_mode = None


def get_adapter() -> BrokerAdapter:
    """Return a shared broker adapter based on PAPER_MODE env var."""
    global _adapter_instance, _adapter_mode

    mode = "paper" if PAPER_MODE else "live"
    if _adapter_instance is not None and _adapter_mode == mode:
        return _adapter_instance

    if PAPER_MODE:
        logger.info("Using paper-mode adapter")
        _adapter_instance = AngelPaperAdapter()
    else:
        logger.info("Using LIVE AngelOne SmartAPI adapter")
        _adapter_instance = AngelLiveAdapter()
    _adapter_mode = mode
    return _adapter_instance
