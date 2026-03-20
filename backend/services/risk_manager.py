"""Reusable portfolio risk engine for bots, paper trading, and live execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

from backend.trading_engine.account_state import AccountState


logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """Configurable portfolio-level risk parameters."""

    max_position_pct: float = 0.10
    max_portfolio_risk_pct: float = 0.30
    max_symbol_exposure_pct: float = 0.20
    max_daily_loss: float = 5_000.0
    max_daily_loss_pct: float = 0.02
    max_drawdown_pct: float = 0.10
    min_cash_buffer_pct: float = 0.05
    trailing_stop_pct: float = 0.015
    min_risk_reward_ratio: float = 2.0
    max_open_positions: int = 5
    cooldown_after_loss: int = 2
    default_stop_loss_pct: float = 0.02


@dataclass
class PositionRisk:
    """Live risk state for a single position."""

    ticker: str
    side: str
    entry_price: float
    quantity: int
    highest_price: float = 0.0
    lowest_price: float = 1e9
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
        return current_price >= self.trailing_stop


@dataclass
class RiskDecision:
    """Outcome of a risk check."""

    allowed: bool
    code: str
    reason: str
    suggested_quantity: int = 0
    requested_quantity: int = 0
    projected_position_value: float = 0.0
    projected_symbol_exposure: float = 0.0
    projected_portfolio_exposure: float = 0.0
    current_drawdown_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "code": self.code,
            "reason": self.reason,
            "suggested_quantity": self.suggested_quantity,
            "requested_quantity": self.requested_quantity,
            "projected_position_value": round(self.projected_position_value, 2),
            "projected_symbol_exposure": round(self.projected_symbol_exposure, 2),
            "projected_portfolio_exposure": round(self.projected_portfolio_exposure, 2),
            "current_drawdown_pct": round(self.current_drawdown_pct, 4),
        }


class RiskManager:
    """Portfolio-level risk manager with reusable order validation."""

    def __init__(self, capital: float, config: RiskConfig | None = None) -> None:
        self.capital = capital
        self._initial_capital = capital
        self.config = config or RiskConfig()
        self.daily_pnl: float = 0.0
        self.current_equity: float = capital
        self.peak_equity: float = capital
        self.drawdown_pct: float = 0.0
        self.positions: dict[str, PositionRisk] = {}
        self.loss_cooldown: int = 0
        self.last_rejections: list[dict[str, Any]] = []

    def update_capital(self, available_cash: float) -> None:
        self.capital = available_cash
        logger.debug("RiskManager capital updated to ₹%.2f", available_cash)

    def record_equity_snapshot(self, equity: float) -> None:
        if equity <= 0:
            return
        self.current_equity = equity
        if self.peak_equity <= 0:
            self.peak_equity = equity
        self.peak_equity = max(self.peak_equity, equity)
        if self.peak_equity > 0:
            self.drawdown_pct = max((self.peak_equity - equity) / self.peak_equity, 0.0)

    def sync_account_state(self, account_state: AccountState) -> None:
        self.capital = max(account_state.buying_power, account_state.available_cash, 0.0)
        self.record_equity_snapshot(max(account_state.total_equity, 0.0))
        synced_positions: dict[str, PositionRisk] = {}
        for position in account_state.combined_positions().values():
            if position.sellable_quantity <= 0:
                continue
            current_price = position.market_price or position.average_price
            synced = PositionRisk(
                ticker=position.key,
                side="buy",
                entry_price=position.average_price,
                quantity=position.sellable_quantity,
                highest_price=current_price,
                lowest_price=current_price,
            )
            synced.update_trailing_stop(current_price, self.config.trailing_stop_pct)
            synced_positions[position.key] = synced
        self.positions = synced_positions
        logger.debug(
            "RiskManager synced from account state: capital=₹%.2f, positions=%d, drawdown=%.4f",
            self.capital,
            len(self.positions),
            self.drawdown_pct,
        )

    def size_position(
        self,
        *,
        price: float,
        account_state: AccountState,
        stop_loss_pct: float | None = None,
        signal_strength: float = 1.0,
        existing_symbol_exposure: float = 0.0,
    ) -> int:
        if price <= 0:
            return 0
        base_equity = max(account_state.total_equity, account_state.buying_power, account_state.available_cash, self.capital, 0.0)
        if base_equity <= 0:
            return 0

        trade_budget = base_equity * self.config.max_position_pct
        symbol_budget = max((base_equity * self.config.max_symbol_exposure_pct) - existing_symbol_exposure, 0.0)
        portfolio_budget = max((base_equity * self.config.max_portfolio_risk_pct) - account_state.total_exposure(), 0.0)
        cash_budget = max(account_state.available_cash - (base_equity * self.config.min_cash_buffer_pct), 0.0)

        strength_scale = min(max(signal_strength, 0.35), 1.0)
        raw_budget = min(trade_budget, symbol_budget, portfolio_budget, cash_budget)
        sized_budget = raw_budget * strength_scale

        stop_loss = stop_loss_pct or self.config.default_stop_loss_pct
        if stop_loss > 0:
            per_share_risk = max(price * stop_loss, 0.01)
            risk_budget = base_equity * self.config.max_position_pct * max(strength_scale, 0.5)
            risk_qty = int(risk_budget / per_share_risk)
        else:
            risk_qty = int(sized_budget / price)

        qty = min(int(sized_budget / price), risk_qty) if risk_qty > 0 else int(sized_budget / price)
        return max(qty, 0)

    def validate_order(
        self,
        order_intent: Mapping[str, Any],
        account_state: AccountState,
        *,
        current_price: float,
        expected_return_pct: float | None = None,
        stop_loss_pct: float | None = None,
    ) -> RiskDecision:
        side = str(order_intent.get("side") or "").lower()
        ticker = str(order_intent.get("ticker") or "").upper()
        quantity = int(order_intent.get("quantity") or 0)

        if quantity <= 0 or current_price <= 0:
            return self._reject("invalid_order", "Quantity and current price must be positive.", quantity)

        self.sync_account_state(account_state)

        if side == "sell":
            return RiskDecision(
                allowed=True,
                code="ok",
                reason="Sell order reduces risk exposure.",
                suggested_quantity=quantity,
                requested_quantity=quantity,
                projected_position_value=current_price * quantity,
                projected_symbol_exposure=self._symbol_exposure(account_state, ticker),
                projected_portfolio_exposure=account_state.total_exposure(),
                current_drawdown_pct=self.drawdown_pct,
            )

        if self.loss_cooldown > 0:
            return self._reject(
                "cooldown_active",
                f"Cooldown active ({self.loss_cooldown} cycles remaining after a loss event).",
                quantity,
            )

        daily_limit = min(self.config.max_daily_loss, max(self.current_equity, self.capital, 0.0) * self.config.max_daily_loss_pct)
        if self.daily_pnl <= -daily_limit:
            return self._reject("daily_loss_limit", f"Daily loss cap reached at ₹{daily_limit:.2f}.", quantity)

        if self.drawdown_pct >= self.config.max_drawdown_pct:
            return self._reject(
                "drawdown_limit",
                f"Portfolio drawdown {self.drawdown_pct:.2%} exceeds limit {self.config.max_drawdown_pct:.2%}.",
                quantity,
            )

        if account_state.position_count() >= self.config.max_open_positions and not account_state.has_position(ticker):
            return self._reject(
                "max_open_positions",
                f"Maximum open positions ({self.config.max_open_positions}) reached.",
                quantity,
            )

        position_value = current_price * quantity
        base_equity = max(account_state.total_equity, account_state.buying_power, account_state.available_cash, self.capital, 0.0)
        trade_budget = base_equity * self.config.max_position_pct
        current_symbol_exposure = self._symbol_exposure(account_state, ticker)
        projected_symbol_exposure = current_symbol_exposure + position_value
        projected_portfolio_exposure = account_state.total_exposure() + position_value
        remaining_cash = account_state.available_cash - position_value
        min_cash_buffer = base_equity * self.config.min_cash_buffer_pct
        sized_quantity = self.size_position(
            price=current_price,
            account_state=account_state,
            stop_loss_pct=stop_loss_pct,
            signal_strength=float(order_intent.get("signal_strength") or 1.0),
            existing_symbol_exposure=current_symbol_exposure,
        )

        if position_value > trade_budget:
            return self._reject(
                "capital_allocation_limit",
                f"Trade value ₹{position_value:.2f} exceeds per-trade allocation ₹{trade_budget:.2f}.",
                quantity,
                suggested_quantity=sized_quantity,
                projected_position_value=position_value,
                projected_symbol_exposure=projected_symbol_exposure,
                projected_portfolio_exposure=projected_portfolio_exposure,
            )

        symbol_limit = base_equity * self.config.max_symbol_exposure_pct
        if projected_symbol_exposure > symbol_limit:
            return self._reject(
                "symbol_exposure_limit",
                f"Symbol exposure ₹{projected_symbol_exposure:.2f} would exceed limit ₹{symbol_limit:.2f}.",
                quantity,
                suggested_quantity=sized_quantity,
                projected_position_value=position_value,
                projected_symbol_exposure=projected_symbol_exposure,
                projected_portfolio_exposure=projected_portfolio_exposure,
            )

        portfolio_limit = base_equity * self.config.max_portfolio_risk_pct
        if projected_portfolio_exposure > portfolio_limit:
            return self._reject(
                "portfolio_exposure_limit",
                f"Portfolio exposure ₹{projected_portfolio_exposure:.2f} would exceed limit ₹{portfolio_limit:.2f}.",
                quantity,
                suggested_quantity=sized_quantity,
                projected_position_value=position_value,
                projected_symbol_exposure=projected_symbol_exposure,
                projected_portfolio_exposure=projected_portfolio_exposure,
            )

        if remaining_cash < min_cash_buffer:
            return self._reject(
                "cash_buffer_limit",
                f"Cash buffer would fall below ₹{min_cash_buffer:.2f}.",
                quantity,
                suggested_quantity=sized_quantity,
                projected_position_value=position_value,
                projected_symbol_exposure=projected_symbol_exposure,
                projected_portfolio_exposure=projected_portfolio_exposure,
            )

        if sized_quantity > 0 and quantity > sized_quantity:
            return self._reject(
                "position_size_limit",
                f"Requested quantity {quantity} exceeds risk-sized quantity {sized_quantity}.",
                quantity,
                suggested_quantity=sized_quantity,
                projected_position_value=position_value,
                projected_symbol_exposure=projected_symbol_exposure,
                projected_portfolio_exposure=projected_portfolio_exposure,
            )

        stop_loss = stop_loss_pct or self.config.default_stop_loss_pct
        if expected_return_pct is not None and stop_loss > 0 and not self.meets_risk_reward(expected_return_pct, stop_loss):
            return self._reject(
                "risk_reward_limit",
                "Expected reward does not justify the configured stop-loss risk.",
                quantity,
                suggested_quantity=sized_quantity,
                projected_position_value=position_value,
                projected_symbol_exposure=projected_symbol_exposure,
                projected_portfolio_exposure=projected_portfolio_exposure,
            )

        return RiskDecision(
            allowed=True,
            code="ok",
            reason="Risk checks passed.",
            suggested_quantity=quantity,
            requested_quantity=quantity,
            projected_position_value=position_value,
            projected_symbol_exposure=projected_symbol_exposure,
            projected_portfolio_exposure=projected_portfolio_exposure,
            current_drawdown_pct=self.drawdown_pct,
        )

    def _reject(
        self,
        code: str,
        reason: str,
        quantity: int,
        *,
        suggested_quantity: int = 0,
        projected_position_value: float = 0.0,
        projected_symbol_exposure: float = 0.0,
        projected_portfolio_exposure: float = 0.0,
    ) -> RiskDecision:
        decision = RiskDecision(
            allowed=False,
            code=code,
            reason=reason,
            suggested_quantity=suggested_quantity,
            requested_quantity=quantity,
            projected_position_value=projected_position_value,
            projected_symbol_exposure=projected_symbol_exposure,
            projected_portfolio_exposure=projected_portfolio_exposure,
            current_drawdown_pct=self.drawdown_pct,
        )
        self.last_rejections.append(decision.to_dict())
        if len(self.last_rejections) > 50:
            self.last_rejections = self.last_rejections[-50:]
        logger.info("Risk rejected order: %s", reason, extra={"risk_code": code})
        return decision

    def can_open_position(self, ticker: str, price: float, quantity: int) -> tuple[bool, str]:
        synthetic_state = AccountState(
            account_type="paper",
            available_cash=self.capital,
            buying_power=self.capital,
            total_equity=max(self.current_equity, self.capital, 0.0),
        )
        decision = self.validate_order(
            {"ticker": ticker, "side": "buy", "quantity": quantity},
            synthetic_state,
            current_price=price,
        )
        return decision.allowed, decision.reason if not decision.allowed else "OK"

    def optimal_quantity(self, price: float, stop_loss_pct: float) -> int:
        state = AccountState(
            account_type="paper",
            available_cash=self.capital,
            buying_power=self.capital,
            total_equity=max(self.current_equity, self.capital, 0.0),
        )
        return self.size_position(price=price, account_state=state, stop_loss_pct=stop_loss_pct)

    def register_entry(self, ticker: str, side: str, price: float, quantity: int) -> None:
        pos = PositionRisk(
            ticker=ticker,
            side=side,
            entry_price=price,
            quantity=quantity,
            highest_price=price,
            lowest_price=price,
        )
        pos.update_trailing_stop(price, self.config.trailing_stop_pct)
        self.positions[ticker] = pos

    def check_exit(self, ticker: str, current_price: float) -> tuple[bool, str]:
        pos = self.positions.get(ticker)
        if not pos:
            return False, ""

        pos.update_trailing_stop(current_price, self.config.trailing_stop_pct)
        if pos.should_exit_trailing(current_price):
            return True, "TRAILING_STOP"
        return False, ""

    def register_exit(self, ticker: str, pnl: float, reason: str) -> None:
        self.daily_pnl += pnl
        if ticker in self.positions:
            del self.positions[ticker]

        if reason in {"STOP_LOSS", "TRAILING_STOP"}:
            self.loss_cooldown = self.config.cooldown_after_loss
            logger.info("Stop-loss hit on %s, cooldown for %d cycles", ticker, self.loss_cooldown)

    def tick_cycle(self) -> None:
        if self.loss_cooldown > 0:
            self.loss_cooldown -= 1

    def reset_daily(self) -> None:
        self.daily_pnl = 0.0
        self.loss_cooldown = 0

    def meets_risk_reward(self, expected_return_pct: float, stop_loss_pct: float) -> bool:
        if stop_loss_pct <= 0:
            return False
        ratio = expected_return_pct / stop_loss_pct
        return ratio >= self.config.min_risk_reward_ratio

    @staticmethod
    def _symbol_exposure(account_state: AccountState, ticker: str) -> float:
        total = 0.0
        for position in account_state.combined_positions().values():
            if position.ticker.upper() == ticker.upper():
                total += position.exposure
        return total

    @property
    def status(self) -> dict[str, Any]:
        return {
            "daily_pnl": round(self.daily_pnl, 2),
            "open_positions": len(self.positions),
            "loss_cooldown": self.loss_cooldown,
            "capital": round(self.capital, 2),
            "current_equity": round(self.current_equity, 2),
            "peak_equity": round(self.peak_equity, 2),
            "drawdown_pct": round(self.drawdown_pct, 4),
            "portfolio_exposure": round(sum(p.entry_price * p.quantity for p in self.positions.values()), 2),
            "recent_rejections": self.last_rejections[-5:],
        }
