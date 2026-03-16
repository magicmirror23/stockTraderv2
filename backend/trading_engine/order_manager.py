"""Order Manager – converts equity and option predictions to order intents
with risk controls, option strategy support, and calibrated sizing."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class RiskConfig:
    """Per-account risk constraints."""

    max_position_pct: float = 0.10          # max 10 % of capital per position
    max_total_exposure_pct: float = 0.80    # max 80 % of capital deployed
    default_stop_loss_pct: float = 0.03     # 3 % stop-loss
    default_take_profit_pct: float = 0.06   # 6 % take-profit
    min_confidence: float = 0.55            # ignore signals below this

    # Option-specific limits
    max_option_exposure_pct: float = 0.20   # max 20 % capital in options
    max_single_option_pct: float = 0.05     # max 5 % capital per option leg
    option_lot_size: int = 1                # minimum lot multiplier


# ---------------------------------------------------------------------------
# Order intent (supports equity + options)
# ---------------------------------------------------------------------------


@dataclass
class OrderIntent:
    ticker: str
    side: str           # "buy" | "sell"
    quantity: int
    order_type: str     # "market" | "limit"
    limit_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None

    # Option fields (None for plain equity)
    option_type: str | None = None      # "CE" | "PE"
    strike: float | None = None
    expiry: str | None = None           # ISO date
    strategy: str | None = None         # "single" | "vertical_spread" | ...


@dataclass
class StrategyLeg:
    """Single leg inside a multi-leg option strategy."""
    side: str
    option_type: str
    strike: float
    quantity: int


@dataclass
class OptionStrategyIntent:
    """Multi-leg option strategy mapped to a list of OrderIntents."""
    strategy: str
    ticker: str
    expiry: str
    legs: list[StrategyLeg] = field(default_factory=list)
    net_debit: float = 0.0
    max_loss: float = 0.0
    max_profit: float = 0.0


# ---------------------------------------------------------------------------
# Slippage log entry
# ---------------------------------------------------------------------------


@dataclass
class SlippageRecord:
    ticker: str
    side: str
    expected_price: float
    filled_price: float
    slippage: float
    timestamp: str


# ---------------------------------------------------------------------------
# Sizing helpers
# ---------------------------------------------------------------------------


def _calibrated_size_factor(confidence: float) -> float:
    """Map calibrated confidence ∈ [0, 1] to a sizing factor ∈ (0, 1].

    Uses a concave (square-root) mapping so that marginal confidence
    gains shrink position size increases.
    """
    return math.sqrt(max(confidence, 0.0))


def _risk_adjusted_utility(
    expected_return: float,
    confidence: float,
    risk_aversion: float = 2.0,
) -> float:
    """Simple risk-adjusted utility: E[r] * conf - Î» * Var proxy.

    Higher values → larger allocation.
    """
    variance_proxy = (1 - confidence) ** 2
    return expected_return * confidence - risk_aversion * variance_proxy


# ---------------------------------------------------------------------------
# Order manager
# ---------------------------------------------------------------------------


class OrderManager:
    """Converts model predictions into sized order intents with risk limits.

    Supports equity positions, single-leg CE/PE options, vertical spreads,
    iron condors, and covered calls.
    """

    def __init__(
        self,
        capital: float = 100_000.0,
        risk_config: RiskConfig | None = None,
    ) -> None:
        self.capital = capital
        self.risk = risk_config or RiskConfig()
        self.current_exposure: float = 0.0
        self.option_exposure: float = 0.0
        self.positions: dict[str, int] = {}
        self.slippage_log: list[SlippageRecord] = []

    # ------------------------------------------------------------------ #
    #  Equity prediction → intent                                         #
    # ------------------------------------------------------------------ #

    def prediction_to_intent(
        self,
        ticker: str,
        action: str,
        confidence: float,
        current_price: float,
        expected_return: float = 0.0,
    ) -> OrderIntent | None:
        """Map a single equity prediction to an order intent."""
        if confidence < self.risk.min_confidence:
            logger.debug(
                "Skipping %s: confidence %.2f < %.2f",
                ticker, confidence, self.risk.min_confidence,
            )
            return None

        if action == "hold":
            return None

        side = "buy" if action == "buy" else "sell"

        if side == "buy":
            size_factor = _calibrated_size_factor(confidence)
            max_alloc = self.capital * self.risk.max_position_pct * size_factor
            remaining_budget = (
                self.capital * self.risk.max_total_exposure_pct
                - self.current_exposure
            )
            alloc = min(max_alloc, remaining_budget)
            if alloc <= 0 or current_price <= 0:
                return None
            quantity = max(1, int(alloc / current_price))

            stop_loss = round(
                current_price * (1 - self.risk.default_stop_loss_pct), 2,
            )
            take_profit = round(
                current_price * (1 + self.risk.default_take_profit_pct), 2,
            )
        else:
            quantity = self.positions.get(ticker, 0)
            if quantity <= 0:
                return None
            stop_loss = None
            take_profit = None

        return OrderIntent(
            ticker=ticker,
            side=side,
            quantity=quantity,
            order_type="market",
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    # ------------------------------------------------------------------ #
    #  Option prediction → intent (single-leg CE / PE)                    #
    # ------------------------------------------------------------------ #

    def option_prediction_to_intent(
        self,
        ticker: str,
        action: str,
        confidence: float,
        option_price: float,
        option_type: str,
        strike: float,
        expiry: str,
        expected_return: float = 0.0,
    ) -> OrderIntent | None:
        """Map an option signal to a single-leg order intent."""
        if confidence < self.risk.min_confidence:
            return None
        if action == "hold":
            return None

        side = "buy" if action == "buy" else "sell"

        if side == "buy":
            remaining_opt = (
                self.capital * self.risk.max_option_exposure_pct
                - self.option_exposure
            )
            size_factor = _calibrated_size_factor(confidence)
            max_alloc = self.capital * self.risk.max_single_option_pct * size_factor
            alloc = min(max_alloc, remaining_opt)
            if alloc <= 0 or option_price <= 0:
                return None
            quantity = max(
                self.risk.option_lot_size,
                int(alloc / option_price),
            )
        else:
            key = f"{ticker}_{option_type}_{strike}_{expiry}"
            quantity = self.positions.get(key, 0)
            if quantity <= 0:
                return None

        return OrderIntent(
            ticker=ticker,
            side=side,
            quantity=quantity,
            order_type="market",
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            strategy="single",
        )

    # ------------------------------------------------------------------ #
    #  Multi-leg option strategies                                        #
    # ------------------------------------------------------------------ #

    def build_vertical_spread(
        self,
        ticker: str,
        option_type: str,
        long_strike: float,
        short_strike: float,
        expiry: str,
        confidence: float,
        long_price: float,
        short_price: float,
    ) -> list[OrderIntent]:
        """Build a vertical (bull/bear) spread as two order intents."""
        if confidence < self.risk.min_confidence:
            return []

        net_debit = long_price - short_price
        if net_debit <= 0:
            return []

        size_factor = _calibrated_size_factor(confidence)
        max_alloc = self.capital * self.risk.max_single_option_pct * size_factor
        remaining = (
            self.capital * self.risk.max_option_exposure_pct - self.option_exposure
        )
        alloc = min(max_alloc, remaining)
        if alloc <= 0:
            return []

        quantity = max(self.risk.option_lot_size, int(alloc / net_debit))

        return [
            OrderIntent(
                ticker=ticker, side="buy", quantity=quantity, order_type="market",
                option_type=option_type, strike=long_strike, expiry=expiry,
                strategy="vertical_spread",
            ),
            OrderIntent(
                ticker=ticker, side="sell", quantity=quantity, order_type="market",
                option_type=option_type, strike=short_strike, expiry=expiry,
                strategy="vertical_spread",
            ),
        ]

    def build_iron_condor(
        self,
        ticker: str,
        expiry: str,
        put_long_strike: float,
        put_short_strike: float,
        call_short_strike: float,
        call_long_strike: float,
        confidence: float,
        net_credit: float,
    ) -> list[OrderIntent]:
        """Build an iron condor (4-leg) as order intents."""
        if confidence < self.risk.min_confidence:
            return []

        max_loss = max(
            call_long_strike - call_short_strike,
            put_short_strike - put_long_strike,
        ) - net_credit
        if max_loss <= 0:
            return []

        size_factor = _calibrated_size_factor(confidence)
        max_alloc = self.capital * self.risk.max_single_option_pct * size_factor
        remaining = (
            self.capital * self.risk.max_option_exposure_pct - self.option_exposure
        )
        alloc = min(max_alloc, remaining)
        if alloc <= 0:
            return []

        quantity = max(self.risk.option_lot_size, int(alloc / max_loss))

        return [
            # Put spread (bull put)
            OrderIntent(
                ticker=ticker, side="buy", quantity=quantity, order_type="market",
                option_type="PE", strike=put_long_strike, expiry=expiry,
                strategy="iron_condor",
            ),
            OrderIntent(
                ticker=ticker, side="sell", quantity=quantity, order_type="market",
                option_type="PE", strike=put_short_strike, expiry=expiry,
                strategy="iron_condor",
            ),
            # Call spread (bear call)
            OrderIntent(
                ticker=ticker, side="sell", quantity=quantity, order_type="market",
                option_type="CE", strike=call_short_strike, expiry=expiry,
                strategy="iron_condor",
            ),
            OrderIntent(
                ticker=ticker, side="buy", quantity=quantity, order_type="market",
                option_type="CE", strike=call_long_strike, expiry=expiry,
                strategy="iron_condor",
            ),
        ]

    def build_covered_call(
        self,
        ticker: str,
        current_price: float,
        call_strike: float,
        expiry: str,
        confidence: float,
        call_price: float,
    ) -> list[OrderIntent]:
        """Build a covered call: long equity + short call."""
        if confidence < self.risk.min_confidence:
            return []
        if current_price <= 0 or call_price <= 0:
            return []

        size_factor = _calibrated_size_factor(confidence)
        max_alloc = self.capital * self.risk.max_position_pct * size_factor
        remaining = (
            self.capital * self.risk.max_total_exposure_pct - self.current_exposure
        )
        alloc = min(max_alloc, remaining)
        if alloc <= 0:
            return []

        equity_qty = max(1, int(alloc / current_price))

        return [
            OrderIntent(
                ticker=ticker, side="buy", quantity=equity_qty,
                order_type="market",
            ),
            OrderIntent(
                ticker=ticker, side="sell", quantity=equity_qty,
                order_type="market", option_type="CE", strike=call_strike,
                expiry=expiry, strategy="covered_call",
            ),
        ]

    # ------------------------------------------------------------------ #
    #  Batch processing                                                   #
    # ------------------------------------------------------------------ #

    def batch_predictions_to_intents(
        self,
        predictions: list[dict],
        prices: dict[str, float],
    ) -> list[OrderIntent]:
        """Convert a batch of prediction dicts to order intents.

        Each dict may contain ``option_type``, ``strike``, ``expiry``
        to route through the option path.
        """
        intents: list[OrderIntent] = []
        for pred in predictions:
            price = prices.get(pred["ticker"])
            if price is None:
                continue

            if pred.get("option_type"):
                intent = self.option_prediction_to_intent(
                    ticker=pred["ticker"],
                    action=pred["action"],
                    confidence=pred["confidence"],
                    option_price=price,
                    option_type=pred["option_type"],
                    strike=pred["strike"],
                    expiry=pred["expiry"],
                    expected_return=pred.get("expected_return", 0.0),
                )
            else:
                intent = self.prediction_to_intent(
                    ticker=pred["ticker"],
                    action=pred["action"],
                    confidence=pred["confidence"],
                    current_price=price,
                    expected_return=pred.get("expected_return", 0.0),
                )
            if intent:
                intents.append(intent)
        return intents

    # ------------------------------------------------------------------ #
    #  Fill recording + slippage logging                                  #
    # ------------------------------------------------------------------ #

    def record_fill(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        expected_price: float | None = None,
        option_type: str | None = None,
        strike: float | None = None,
        expiry: str | None = None,
    ) -> None:
        """Update internal state after a fill and log slippage."""
        # Determine position key
        if option_type and strike and expiry:
            key = f"{ticker}_{option_type}_{strike}_{expiry}"
        else:
            key = ticker

        if side == "buy":
            self.positions[key] = self.positions.get(key, 0) + quantity
            cost = quantity * price
            if option_type:
                self.option_exposure += cost
            else:
                self.current_exposure += cost
        else:
            self.positions[key] = max(0, self.positions.get(key, 0) - quantity)
            proceeds = quantity * price
            if option_type:
                self.option_exposure = max(0, self.option_exposure - proceeds)
            else:
                self.current_exposure = max(0, self.current_exposure - proceeds)

        # Log slippage
        if expected_price is not None:
            slip = abs(price - expected_price)
            self.slippage_log.append(
                SlippageRecord(
                    ticker=key,
                    side=side,
                    expected_price=expected_price,
                    filled_price=price,
                    slippage=round(slip, 4),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            )
            logger.info(
                "Fill %s %s %d @ %.2f (expected %.2f, slip %.4f)",
                side, key, quantity, price, expected_price, slip,
            )
