"""Angel One SmartAPI adapter – paper + live implementations.

This adapter is *pluggable*: the ``BrokerAdapter`` protocol defines the
interface.  Set ``PAPER_MODE=false`` in ``.env`` and provide AngelOne
credentials to trade live via SmartAPI.

Credentials (set in ``.env``):
    ANGEL_API_KEY      – SmartAPI key from https://smartapi.angelone.in/
    ANGEL_CLIENT_ID    – Your Angel One client ID
    ANGEL_MPIN         – 4-digit MPIN for login
    ANGEL_TOTP_SECRET  – TOTP secret for 2FA
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Protocol

import numpy as np

from backend.core.config import settings

logger = logging.getLogger(__name__)

PAPER_MODE = settings.PAPER_MODE
ANGEL_API_KEY = settings.ANGEL_API_KEY or ""
ANGEL_CLIENT_ID = settings.ANGEL_CLIENT_ID or ""
ANGEL_MPIN = settings.ANGEL_CLIENT_PIN or ""
ANGEL_TOTP_SECRET = settings.ANGEL_TOTP_SECRET or ""


# ---------------------------------------------------------------------------
# Protocol (interface)
# ---------------------------------------------------------------------------

class BrokerAdapter(Protocol):
    """Pluggable broker adapter interface."""

    def place_order(self, order_intent: dict) -> dict:
        ...

    def cancel_order(self, order_id: str) -> dict:
        ...

    def get_order_status(self, order_id: str) -> dict:
        ...

    def get_ltp(self, ticker: str) -> dict:
        ...

    def get_balance(self) -> dict:
        """Return available balance / margin.

        Returns dict with at least: available_cash, used_margin, total_equity.
        """
        ...


# ---------------------------------------------------------------------------
# Paper-mode adapter
# ---------------------------------------------------------------------------

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
    # Option fields
    option_type: str | None = None
    strike: float | None = None
    expiry: str | None = None
    strategy: str | None = None


# Default demo capital (can be overridden via PAPER_BALANCE env var)
_DEFAULT_PAPER_BALANCE = 100000.0


class AngelPaperAdapter:
    """Simulates Angel One SmartAPI in paper mode.

    Supports retries and rate-limit backoff.  All fills are simulated
    with configurable slippage.  Option orders have higher slippage.

    The adapter tracks a virtual cash balance.  Set ``PAPER_BALANCE`` in
    ``.env`` to change the starting amount (default ₹1,00,000).
    """

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
        self._orders: dict[str, dict] = {}
        # Balance tracking
        self._initial_balance = initial_balance or _DEFAULT_PAPER_BALANCE
        self._available_cash: float = self._initial_balance
        self._used_margin: float = 0.0  # value locked in open positions

    def place_order(self, order_intent: dict) -> dict:
        """Place a simulated order.

        Parameters
        ----------
        order_intent : dict
            Must contain: ticker, side, quantity, order_type.
            Optional: limit_price, current_price, option_type, strike, expiry, strategy.

        Returns
        -------
        dict
            Simulated fill response.
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                return self._execute(order_intent)
            except Exception as exc:
                logger.warning(
                    "Order attempt %d/%d failed: %s", attempt, self.max_retries, exc
                )
                if attempt < self.max_retries:
                    time.sleep(self.rate_limit_delay * attempt)
        return {"status": "failed", "detail": "Max retries exceeded"}

    def cancel_order(self, order_id: str) -> dict:
        """Cancel a simulated order."""
        if order_id in self._orders:
            self._orders[order_id]["status"] = "cancelled"
            return {"order_id": order_id, "status": "cancelled"}
        return {"order_id": order_id, "status": "not_found"}

    def get_order_status(self, order_id: str) -> dict:
        """Retrieve status of a previously placed order."""
        if order_id in self._orders:
            return self._orders[order_id]
        return {"order_id": order_id, "status": "not_found"}

    def get_ltp(self, ticker: str) -> dict:
        """Return simulated LTP based on last filled price for this ticker."""
        last_price = 100.0
        for order in reversed(list(self._orders.values())):
            if order.get("ticker") == ticker and order.get("status") == "filled":
                last_price = order["filled_price"]
                break
        rng = np.random.default_rng()
        jitter = rng.normal(0, 0.002)
        ltp = round(last_price * (1 + jitter), 2)
        return {"ltp": ltp, "ticker": ticker}

    def get_balance(self) -> dict:
        """Return current paper-mode balance."""
        return {
            "available_cash": round(self._available_cash, 2),
            "used_margin": round(self._used_margin, 2),
            "total_equity": round(self._available_cash + self._used_margin, 2),
        }

    def _execute(self, intent: dict) -> dict:
        order_id = str(uuid.uuid4())
        base_price = intent.get("current_price", 100.0)
        is_option = intent.get("option_type") is not None

        # Options have wider slippage
        slip_pct = self.option_slippage_pct if is_option else self.slippage_pct

        # Add small random variation to slippage
        rng = np.random.default_rng()
        jitter = rng.uniform(0.5, 1.5)
        effective_slip = slip_pct * jitter

        if intent["side"] == "buy":
            filled_price = round(base_price * (1 + effective_slip), 2)
        else:
            filled_price = round(base_price * (1 - effective_slip), 2)

        # Simulated latency with jitter
        latency = round(self.simulated_latency_ms * rng.uniform(0.8, 1.5), 2)

        fill = SimulatedFill(
            order_id=order_id,
            ticker=intent["ticker"],
            side=intent["side"],
            quantity=intent["quantity"],
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

        # Update balance: buy → lock cash, sell → release cash
        order_value = filled_price * intent["quantity"]
        if intent["side"] == "buy":
            self._available_cash -= order_value
            self._used_margin += order_value
        else:
            self._available_cash += order_value
            self._used_margin = max(0.0, self._used_margin - order_value)

        logger.info(
            "Simulated fill: %s %s %d @ %.2f (slip=%.4f, latency=%.1fms, bal=%.2f)",
            intent["side"], intent["ticker"], intent["quantity"],
            filled_price, fill.slippage, latency, self._available_cash,
        )
        return result


# ---------------------------------------------------------------------------
# Live-mode adapter (requires smartapi-python)
# ---------------------------------------------------------------------------

class AngelLiveAdapter:
    """Real Angel One SmartAPI adapter for live trading.

    Requires the ``smartapi-python`` package::

        pip install smartapi-python

    Set these environment variables in ``.env``::

        ANGEL_API_KEY=<your-api-key>
        ANGEL_CLIENT_ID=<your-client-id>
        ANGEL_MPIN=<your-4-digit-mpin>
        ANGEL_TOTP_SECRET=<your-totp-secret>
    """

    def __init__(self) -> None:
        if not all([ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_MPIN, ANGEL_TOTP_SECRET]):
            raise RuntimeError(
                "Missing AngelOne credentials. Set ANGEL_API_KEY, ANGEL_CLIENT_ID, "
                "ANGEL_MPIN, and ANGEL_TOTP_SECRET in your .env file."
            )
        self._smart_api = None
        self._connected = False

    def _ensure_connected(self) -> None:
        """Lazily connect on first use so bad credentials don't crash startup."""
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
            "transactiontype": order_intent["side"].upper(),
            "exchange": order_intent.get("exchange", "NSE"),
            "ordertype": order_intent.get("order_type", "MARKET").upper(),
            "producttype": order_intent.get("product_type", "INTRADAY"),
            "duration": "DAY",
            "quantity": str(order_intent["quantity"]),
        }
        if order_intent.get("limit_price"):
            params["price"] = str(order_intent["limit_price"])

        result = self._smart_api.placeOrder(params)
        logger.info("AngelOne order placed: %s", result)
        return {
            "order_id": result if isinstance(result, str) else str(result),
            "ticker": order_intent["ticker"],
            "side": order_intent["side"],
            "quantity": order_intent["quantity"],
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
                if order.get("orderid") == order_id:
                    return order
        return {"order_id": order_id, "status": "not_found"}

    def get_ltp(self, ticker: str) -> dict:
        """Fetch last traded price from Angel One."""
        self._ensure_connected()
        exchange = "NSE"
        try:
            data = self._smart_api.ltpData(exchange, ticker, "")
            if data and data.get("data"):
                return {
                    "ltp": float(data["data"].get("ltp", 0)),
                    "ticker": ticker,
                }
        except Exception as exc:
            logger.warning("LTP fetch failed for %s: %s", ticker, exc)
        return {"ltp": 0, "ticker": ticker}

    def get_balance(self) -> dict:
        """Fetch available cash, margins, and equity from Angel One."""
        self._ensure_connected()
        try:
            rms = self._smart_api.rmsLimit()
            data = rms.get("data", {}) if rms else {}
            return {
                "available_cash": float(data.get("availablecash", 0)),
                "used_margin": float(data.get("utiliseddebits", 0)),
                "total_equity": float(data.get("net", 0)),
            }
        except Exception as exc:
            logger.warning("Balance fetch failed: %s", exc)
            return {"available_cash": 0, "used_margin": 0, "total_equity": 0}


# ---------------------------------------------------------------------------
# Factory – auto-selects adapter based on PAPER_MODE
# ---------------------------------------------------------------------------

def get_adapter() -> BrokerAdapter:
    """Return the appropriate broker adapter based on PAPER_MODE env var."""
    if PAPER_MODE:
        logger.info("Using paper-mode adapter")
        return AngelPaperAdapter()
    logger.info("Using LIVE AngelOne SmartAPI adapter")
    return AngelLiveAdapter()
