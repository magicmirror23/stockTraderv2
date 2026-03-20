"""Market status, account verification, and production-grade bot endpoints."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from backend.core.config import settings
from backend.services.audit_service import record_audit_event
from backend.services.market_hours import get_market_status
from backend.services.risk_manager import RiskConfig, RiskManager
from backend.services.strategy_market_data import StrategyMarketDataLoader
from backend.trading_engine.account_state import (
    ValidationRules,
    fetch_real_account_state,
    validate_trade_against_account_state,
)
from backend.trading_engine.execution_engine import AccountStateExecutionEngine
from backend.trading_engine.options_contracts import (
    OptionContractResolver,
    days_to_expiry,
    estimate_option_premium,
)
from backend.trading_engine.strategies import StrategySignal, available_strategies, create_strategy

logger = logging.getLogger(__name__)

router = APIRouter(tags=["market"])

DEFAULT_EQUITY_WATCHLIST = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
DEFAULT_OPTIONS_WATCHLIST = ["NIFTY50", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK"]


def _coerce_watchlist(value: Any, fallback: list[str]) -> list[str]:
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list):
        items = value
    else:
        return list(fallback)
    normalized = [str(item).strip().upper() for item in items if str(item).strip()]
    return normalized or list(fallback)


def _default_equity_watchlist() -> list[str]:
    configured = [symbol for symbol in settings.watchlist_symbols if symbol not in {"NIFTY50", "BANKNIFTY", "SENSEX"}]
    return configured[:5] or list(DEFAULT_EQUITY_WATCHLIST)


def _default_options_watchlist() -> list[str]:
    preferred = ["NIFTY50", "BANKNIFTY", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN"]
    configured = [symbol for symbol in settings.watchlist_symbols if symbol in preferred]
    return configured[:6] or list(DEFAULT_OPTIONS_WATCHLIST)


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


@router.get("/account/profile")
async def account_profile():
    """Verify AngelOne credentials and fetch account name, balance, margin."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_angel_profile)


class BaseTradingBot:
    """Shared production-grade bot runtime with fresh account-state refreshes."""

    bot_type = "base"
    bot_label = "Trading Bot"
    paper_only = False

    def __init__(
        self,
        *,
        watchlist: list[str],
        min_confidence: float,
        max_positions: int,
        position_size_pct: float,
        stop_loss_pct: float,
        take_profit_pct: float,
        cycle_interval: int,
        strategy_name: str = "ml_prediction",
        strategy_params: dict[str, Any] | None = None,
    ) -> None:
        self.running = False
        self.watchlist = list(watchlist)
        self.min_confidence = min_confidence
        self.max_positions = max_positions
        self.position_size_pct = position_size_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.cycle_interval = cycle_interval
        self.strategy_name = strategy_name
        self.strategy_params = dict(strategy_params or {})
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
        self._strategy = None
        self._market_data_loader = StrategyMarketDataLoader()
        self._execution_engine = AccountStateExecutionEngine(self._validation_rules())
        self._paused_for_market_close: bool = False
        self._consent_pending: bool = False
        self._consent_requested_at: float | None = None
        self._auto_resume_seconds: int = 300
        self._last_signal_scan: str | None = None
        self._last_trade_at: str | None = None
        self._last_account_refresh_error: str | None = None
        self._last_cycle_error: str | None = None
        self._pending_position_size_amount: float | None = None

    def _market_is_open(self) -> bool:
        status = get_market_status()
        return status.phase.value in ("open", "pre_open")

    def _validation_rules(self) -> ValidationRules:
        config = RiskConfig(
            max_position_pct=self.position_size_pct,
            max_portfolio_risk_pct=0.30,
            max_symbol_exposure_pct=0.20,
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

    def _risk_config(self) -> RiskConfig:
        return RiskConfig(
            max_position_pct=self.position_size_pct,
            max_symbol_exposure_pct=min(max(self.position_size_pct * 1.5, self.position_size_pct), 0.25),
            max_daily_loss=5000.0,
            max_daily_loss_pct=0.02,
            max_drawdown_pct=0.10,
            min_cash_buffer_pct=0.05,
            trailing_stop_pct=max(self.stop_loss_pct * 0.75, 0.01),
            min_risk_reward_ratio=2.0,
            max_open_positions=self.max_positions,
            cooldown_after_loss=2,
            default_stop_loss_pct=self.stop_loss_pct,
        )

    def _get_risk_manager(self) -> RiskManager:
        if self._risk_mgr is None:
            capital = self._available_balance or 100000.0
            self._risk_mgr = RiskManager(capital, self._risk_config())
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
        self._last_account_refresh_error = None
        self._get_risk_manager().sync_account_state(state)
        return state

    def _sync_bot_positions(self, account_state) -> None:
        for key in list(self.positions.keys()):
            position = self.positions[key]
            ticker = position.get("ticker", key)
            option_type = position.get("option_type")
            strike = position.get("strike")
            expiry = position.get("expiry")
            if not account_state.has_position(ticker, option_type, strike, expiry) and not account_state.has_open_order(
                ticker, None, option_type, strike, expiry
            ):
                del self.positions[key]
                continue
            held_qty = account_state.held_quantity(ticker, option_type, strike, expiry)
            if held_qty > 0:
                self.positions[key]["quantity"] = held_qty
                avg_price = account_state.average_buy_price(ticker, option_type, strike, expiry)
                if avg_price > 0:
                    self.positions[key]["entry_price"] = avg_price

    def _record_trade(self, trade: dict[str, Any]) -> None:
        trade["timestamp"] = trade.get("timestamp") or _timestamp_now()
        self._last_trade_at = trade["timestamp"]
        self.trades_today.append(trade)
        if len(self.trades_today) > 100:
            self.trades_today = self.trades_today[-100:]

    def _record_error(self, message: str) -> None:
        self._last_cycle_error = message
        self.errors.append(message)
        if len(self.errors) > 50:
            self.errors = self.errors[-50:]

    def _supports_live_execution(self) -> bool:
        return True

    def _current_mode_supported(self, account_state=None) -> bool:
        return True

    def _validate_start_mode(self, account_state) -> str | None:
        del account_state
        return None

    def _config_payload(self) -> dict[str, Any]:
        capital_reference = max(self._available_balance, self._total_equity, 0.0)
        return {
            "watchlist": self.watchlist,
            "min_confidence": self.min_confidence,
            "max_positions": self.max_positions,
            "position_size_pct": self.position_size_pct,
            "position_budget": round(capital_reference * self.position_size_pct, 2),
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "cycle_interval": self.cycle_interval,
            "strategy_name": self.strategy_name,
            "strategy_params": self.strategy_params,
        }

    def _runtime_health_snapshot(self) -> dict[str, Any]:
        market = get_market_status()
        account_mode = self._latest_account_state.account_type if self._latest_account_state else ("paper" if settings.PAPER_MODE else "real")
        return {
            "bot_type": self.bot_type,
            "bot_label": self.bot_label,
            "service_mode": settings.service_mode,
            "run_mode": settings.run_mode,
            "paper_mode": settings.PAPER_MODE,
            "live_broker_enabled": settings.live_broker_enabled,
            "market_phase": market.phase.value,
            "market_message": market.message,
            "account_mode": account_mode,
            "paper_only": self.paper_only,
            "live_execution_supported": self._supports_live_execution(),
            "current_mode_supported": self._current_mode_supported(self._latest_account_state),
            "last_signal_scan": self._last_signal_scan,
            "last_trade_at": self._last_trade_at,
            "last_account_refresh_error": self._last_account_refresh_error,
            "last_cycle_error": self._last_cycle_error,
            "strategy_name": self.strategy_name,
            "available_strategies": available_strategies(),
        }

    @property
    def status(self) -> dict[str, Any]:
        risk = self._get_risk_manager().status if self._risk_mgr else {}
        auto_resume_in = None
        if self._consent_pending and self._consent_requested_at:
            elapsed = time.time() - self._consent_requested_at
            auto_resume_in = int(max(0, self._auto_resume_seconds - elapsed))
        return {
            "bot_type": self.bot_type,
            "bot_label": self.bot_label,
            "running": self.running,
            "paused": self._paused_for_market_close,
            "consent_pending": self._consent_pending,
            "auto_resume_in": auto_resume_in,
            "watchlist": self.watchlist,
            "watchlist_count": len(self.watchlist),
            "min_confidence": self.min_confidence,
            "max_positions": self.max_positions,
            "position_size_pct": self.position_size_pct,
            "position_budget": round(max(self._available_balance, self._total_equity, 0.0) * self.position_size_pct, 2),
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
            "runtime_health": self._runtime_health_snapshot(),
            **self._config_payload(),
        }

    def _apply_config(self, config: dict[str, Any] | None) -> None:
        if not config:
            return
        if "watchlist" in config:
            self.watchlist = _coerce_watchlist(config.get("watchlist"), self.watchlist)
        if config.get("min_confidence") is not None:
            self.min_confidence = float(config["min_confidence"])
        if config.get("max_positions") is not None:
            self.max_positions = int(config["max_positions"])
        if config.get("position_size_pct") is not None:
            self.position_size_pct = float(config["position_size_pct"])
            self._pending_position_size_amount = None
        elif config.get("position_size") is not None:
            raw_position_size = float(config["position_size"])
            if raw_position_size <= 1:
                self.position_size_pct = raw_position_size
                self._pending_position_size_amount = None
            elif self._total_equity > 0:
                self.position_size_pct = min(max(raw_position_size / self._total_equity, 0.01), 1.0)
                self._pending_position_size_amount = None
            else:
                self._pending_position_size_amount = raw_position_size
        if config.get("stop_loss_pct") is not None:
            self.stop_loss_pct = float(config["stop_loss_pct"])
        if config.get("take_profit_pct") is not None:
            self.take_profit_pct = float(config["take_profit_pct"])
        if config.get("cycle_interval") is not None:
            self.cycle_interval = int(config["cycle_interval"])
        if config.get("strategy_name") is not None:
            self.strategy_name = str(config["strategy_name"]).strip().lower()
        if config.get("strategy_params") is not None and isinstance(config["strategy_params"], dict):
            self.strategy_params = dict(config["strategy_params"])

    def _finalize_config_after_refresh(self) -> None:
        if self._pending_position_size_amount and max(self._available_balance, self._total_equity, 0.0) > 0:
            capital_reference = max(self._available_balance, self._total_equity, 0.0)
            self.position_size_pct = min(max(self._pending_position_size_amount / capital_reference, 0.01), 1.0)
            self._pending_position_size_amount = None

    def _refresh_runtime_dependencies(self) -> None:
        self._execution_engine = AccountStateExecutionEngine(self._validation_rules())
        if self._risk_mgr is not None:
            self._risk_mgr.config = self._risk_config()
        try:
            self._strategy = create_strategy(
                self.strategy_name,
                model_manager=None,
                params=self.strategy_params,
            )
        except Exception as exc:
            logger.warning("Failed to initialize strategy '%s': %s. Falling back to ml_prediction.", self.strategy_name, exc)
            self._strategy = create_strategy("ml_prediction", model_manager=None, params={})

    def _get_strategy(self):
        if self._strategy is None:
            self._refresh_runtime_dependencies()
        return self._strategy

    def _build_market_data(self, ticker: str, adapter: Any, prediction: dict[str, Any] | None = None):
        return self._market_data_loader.load(ticker, adapter=adapter, prediction=prediction)

    def _generate_signal(
        self,
        *,
        ticker: str,
        adapter: Any,
        account_state,
    ) -> StrategySignal:
        strategy = self._get_strategy()
        market_data = self._build_market_data(ticker, adapter)
        try:
            signal = strategy.generate_signal(market_data, account_state)
        except Exception as exc:
            logger.warning("Strategy '%s' failed for %s: %s", self.strategy_name, ticker, exc)
            fallback_strategy = create_strategy("ml_prediction", model_manager=None, params={})
            signal = fallback_strategy.generate_signal(market_data, account_state)
        if not signal.strategy:
            signal.strategy = self.strategy_name
        return signal

    def start(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.running:
            return {"status": "already_running", "message": f"{self.bot_label} is already running"}

        self._apply_config(config)
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
        self._last_signal_scan = None
        self._last_trade_at = None
        self._last_account_refresh_error = None
        self._last_cycle_error = None
        self._risk_mgr = None
        self._adapter = None
        self._refresh_runtime_dependencies()

        try:
            account_state = self._refresh_account_state()
            self._finalize_config_after_refresh()
            self._refresh_runtime_dependencies()
        except Exception as exc:
            self.running = False
            self._last_account_refresh_error = str(exc)
            return {"status": "error", "message": f"Cannot start {self.bot_label.lower()}: {exc}"}

        mode_error = self._validate_start_mode(account_state)
        if mode_error:
            self.running = False
            return {"status": "error", "message": mode_error, "config": self.status}

        if self._available_balance <= 0:
            self.running = False
            return {
                "status": "error",
                "message": f"Cannot start {self.bot_label.lower()}: available balance is Rs0. Check broker or paper account funding.",
            }

        market_open = self._market_is_open()
        if not market_open:
            self._paused_for_market_close = True

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("%s started with watchlist: %s", self.bot_label, self.watchlist)
        record_audit_event(
            "BOT_START",
            entity_type="bot",
            entity_id=self.bot_type,
            data={
                "bot_label": self.bot_label,
                "watchlist": self.watchlist,
                "paper_only": self.paper_only,
                "market_open": market_open,
                "config": self._config_payload(),
            },
            source="market_router",
        )
        if market_open:
            message = f"{self.bot_label} started"
        else:
            message = (
                f"{self.bot_label} started in standby mode because the market is closed. "
                "It will request consent when the market opens and auto-resume after 5 minutes."
            )
        return {"status": "started", "message": message, "config": self.status}

    def stop(self) -> dict[str, Any]:
        if not self.running:
            return {"status": "not_running", "message": f"{self.bot_label} is not running"}
        self._stop_event.set()
        self.running = False
        self._paused_for_market_close = False
        self._consent_pending = False
        self._consent_requested_at = None
        logger.info("%s stopped. Cycles: %d, PnL: %.2f", self.bot_label, self.cycle_count, self.total_pnl)
        record_audit_event(
            "BOT_STOP",
            entity_type="bot",
            entity_id=self.bot_type,
            data={
                "bot_label": self.bot_label,
                "cycles": self.cycle_count,
                "total_pnl": round(self.total_pnl, 2),
                "trades": len(self.trades_today),
            },
            source="market_router",
        )
        return {
            "status": "stopped",
            "message": f"{self.bot_label} stopped",
            "cycles": self.cycle_count,
            "total_pnl": round(self.total_pnl, 2),
            "trades": len(self.trades_today),
        }

    def _run_loop(self) -> None:
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
                            logger.info("Auto-resuming %s after %ds", self.bot_label, self._auto_resume_seconds)
                            self._consent_pending = False
                            self._paused_for_market_close = False
                        else:
                            self._stop_event.wait(5)
                            continue
                    if self._paused_for_market_close:
                        self._stop_event.wait(5)
                        continue
                    self._run_cycle()
                else:
                    if not self._paused_for_market_close:
                        self._paused_for_market_close = True
                        logger.info("Market closed - %s paused, waiting for next session", self.bot_label)
                    self._stop_event.wait(30)
                    continue
            except Exception as exc:  # pragma: no cover - long-running path
                message = f"{self.bot_label} cycle error: {exc}"
                logger.exception(message)
                self._record_error(message)
            self._stop_event.wait(self.cycle_interval)

    def _check_market_reopen(self) -> None:
        if self._paused_for_market_close and not self._consent_pending:
            self._consent_pending = True
            self._consent_requested_at = time.time()
            logger.info("Market reopened - requesting user consent for %s", self.bot_label)

    def grant_consent(self) -> dict[str, Any]:
        if not self._consent_pending:
            return {"status": "no_consent_needed", "message": "No consent request pending"}
        self._consent_pending = False
        self._paused_for_market_close = False
        self._consent_requested_at = None
        logger.info("User granted consent - %s resuming", self.bot_label)
        record_audit_event(
            "BOT_CONSENT_GRANTED",
            entity_type="bot",
            entity_id=self.bot_type,
            data={"bot_label": self.bot_label},
            source="market_router",
        )
        return {"status": "resumed", "message": f"{self.bot_label} resumed with user consent"}

    def decline_consent(self) -> dict[str, Any]:
        if not self._consent_pending:
            return {"status": "no_consent_needed", "message": "No consent request pending"}
        self._consent_pending = False
        self._paused_for_market_close = False
        self._consent_requested_at = None
        record_audit_event(
            "BOT_CONSENT_DECLINED",
            entity_type="bot",
            entity_id=self.bot_type,
            data={"bot_label": self.bot_label},
            source="market_router",
        )
        return self.stop()

    def _run_cycle(self) -> None:  # pragma: no cover - subclass responsibility
        raise NotImplementedError


class TradingBot(BaseTradingBot):
    """Equity trading bot with account-aware risk management."""

    bot_type = "equity"
    bot_label = "Equity Bot"

    def __init__(self) -> None:
        super().__init__(
            watchlist=_default_equity_watchlist(),
            min_confidence=0.7,
            max_positions=5,
            position_size_pct=0.10,
            stop_loss_pct=0.02,
            take_profit_pct=0.05,
            cycle_interval=60,
            strategy_name="ml_prediction",
        )

    def _run_cycle(self) -> None:
        from backend.services.brokerage_calculator import TradeType, estimate_breakeven_move

        self.cycle_count += 1
        self.last_cycle = _timestamp_now()
        adapter = self._get_adapter()
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
                signal = self._generate_signal(
                    ticker=ticker,
                    adapter=adapter,
                    account_state=account_state,
                )
                self._last_signal_scan = _timestamp_now()
                if not signal:
                    continue
                action = signal.action
                confidence = float(signal.confidence or 0.0)
                if action != "buy" or confidence < self.min_confidence:
                    continue

                price = 0.0
                prediction = signal.metadata.get("prediction") if isinstance(signal.metadata, dict) else None
                if isinstance(prediction, dict):
                    price = float(prediction.get("close", prediction.get("predicted_price", 0)) or 0)
                if price <= 0:
                    price = float(adapter.get_ltp(ticker).get("ltp") or 0)
                if price <= 0:
                    continue

                quantity = risk.size_position(
                    price=price,
                    account_state=account_state,
                    stop_loss_pct=self.stop_loss_pct,
                    signal_strength=max(signal.signal_strength, confidence),
                    existing_symbol_exposure=account_state.get_position(ticker).exposure if account_state.get_position(ticker) else 0.0,
                )
                if quantity <= 0:
                    continue

                breakeven_move = estimate_breakeven_move(price, quantity, TradeType.INTRADAY)
                signal_return = abs(signal.expected_return)
                expected_profit = price * signal_return
                if expected_profit < breakeven_move:
                    continue

                outcome = self._execution_engine.execute_with_adapter(
                    adapter=adapter,
                    order_intent={
                        "ticker": ticker,
                        "side": "buy",
                        "quantity": quantity,
                        "order_type": "market",
                        "strategy": signal.strategy,
                        "signal_strength": signal.signal_strength or confidence,
                    },
                    current_price=price,
                    risk_manager=risk,
                    expected_return_pct=signal.expected_return,
                    stop_loss_pct=self.stop_loss_pct,
                )
                if not outcome.accepted:
                    self._record_error(outcome.reason or f"Entry rejected for {ticker}")
                    continue

                result = outcome.broker_result or {}
                filled_price = float(result.get("filled_price") or price)
                account_state = outcome.account_state_after
                self._sync_bot_positions(account_state)
                held_qty = account_state.held_quantity(ticker)
                if held_qty > 0:
                    self.positions[ticker] = {
                        "ticker": ticker,
                        "side": "buy",
                        "quantity": held_qty,
                        "entry_price": account_state.average_buy_price(ticker) or filled_price,
                        "current_price": filled_price,
                        "pnl": 0.0,
                        "net_pnl": 0.0,
                        "order_id": result.get("order_id", ""),
                        "entered_at": _timestamp_now(),
                        "strategy": signal.strategy,
                        "entry_reason": signal.reason,
                        "confidence": confidence,
                        "signal_strength": signal.signal_strength,
                        "expected_return": signal.expected_return,
                    }
                    risk.register_entry(ticker, "buy", self.positions[ticker]["entry_price"], held_qty)

                self._record_trade(
                    {
                        "ticker": ticker,
                        "action": "ENTRY",
                        "side": "buy",
                        "quantity": quantity,
                        "price": filled_price,
                        "confidence": confidence,
                        "signal_strength": round(signal.signal_strength, 4),
                        "expected_return": round(signal.expected_return, 6),
                        "strategy": signal.strategy,
                        "entry_reason": signal.reason,
                        "status": result.get("status", "placed"),
                    }
                )
                logger.info("Equity bot entered buy %s @ Rs%.2f (conf=%.2f)", ticker, filled_price, confidence)
            except Exception as exc:  # pragma: no cover - long-running path
                self._record_error(f"Predict/trade {ticker}: {exc}")

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
            self._record_error(validation.reason)
            return

        outcome = self._execution_engine.execute_with_adapter(
            adapter=adapter,
            order_intent={"ticker": ticker, "side": "sell", "quantity": held_qty, "order_type": "market"},
            current_price=current,
            risk_manager=risk,
            stop_loss_pct=self.stop_loss_pct,
        )
        if not outcome.accepted:
            self._record_error(outcome.reason or f"Exit rejected for {ticker}")
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
        self._record_trade(
            {
                "ticker": ticker,
                "action": exit_reason,
                "side": "sell",
                "quantity": held_qty,
                "price": round(current, 2),
                "gross_pnl": round(gross_pnl, 2),
                "charges": round(charges, 2),
                "net_pnl": round(net_pnl, 2),
                "strategy": position.get("strategy", self.strategy_name),
                "exit_reason": exit_reason,
                "status": outcome.status,
            }
        )

        if not outcome.account_state_after.has_position(ticker):
            del self.positions[ticker]
        else:
            self.positions[ticker]["quantity"] = outcome.account_state_after.held_quantity(ticker)
            self.positions[ticker]["entry_price"] = outcome.account_state_after.average_buy_price(ticker) or self.positions[ticker]["entry_price"]
            self.positions[ticker].pop("pending_exit", None)
            self.positions[ticker].pop("exit_order_id", None)


class OptionsTradingBot(BaseTradingBot):
    """Paper-safe options bot using underlying signals plus contract selection."""

    bot_type = "options"
    bot_label = "Options Bot"
    paper_only = True

    def __init__(self) -> None:
        super().__init__(
            watchlist=_default_options_watchlist(),
            min_confidence=0.72,
            max_positions=3,
            position_size_pct=0.05,
            stop_loss_pct=0.25,
            take_profit_pct=0.40,
            cycle_interval=90,
            strategy_name="ml_prediction",
        )
        self.option_bias = "both"
        self.expiry_days = 7
        self.strike_steps_from_atm = 0
        self.min_days_to_expiry = 2
        self._contract_resolver = OptionContractResolver()

    def _risk_config(self) -> RiskConfig:
        config = super()._risk_config()
        config.trailing_stop_pct = 0.18
        return config

    def _supports_live_execution(self) -> bool:
        adapter = self._adapter
        if adapter is None:
            return False
        return bool(getattr(adapter, "supports_option_contracts", lambda: False)())

    def _current_mode_supported(self, account_state=None) -> bool:
        if account_state is None and settings.PAPER_MODE:
            return True
        if account_state is None:
            account_state = self._latest_account_state
        if account_state and account_state.account_type == "paper":
            return True
        return self._supports_live_execution()

    def _validate_start_mode(self, account_state) -> str | None:
        if self._current_mode_supported(account_state):
            return None
        return (
            "Options bot currently runs in paper mode only. "
            "Live option contract mapping is not configured yet."
        )

    def _apply_config(self, config: dict[str, Any] | None) -> None:
        super()._apply_config(config)
        if not config:
            return
        if config.get("option_bias") is not None:
            self.option_bias = str(config["option_bias"]).strip().lower()
        if config.get("expiry_days") is not None:
            self.expiry_days = max(1, int(config["expiry_days"]))
        if config.get("strike_steps_from_atm") is not None:
            self.strike_steps_from_atm = max(0, int(config["strike_steps_from_atm"]))
        if config.get("min_days_to_expiry") is not None:
            self.min_days_to_expiry = max(0, int(config["min_days_to_expiry"]))

    def _config_payload(self) -> dict[str, Any]:
        payload = super()._config_payload()
        payload.update(
            {
                "option_bias": self.option_bias,
                "expiry_days": self.expiry_days,
                "strike_steps_from_atm": self.strike_steps_from_atm,
                "min_days_to_expiry": self.min_days_to_expiry,
                "strategy": "single_leg_long_options",
            }
        )
        return payload

    def _has_underlying_exposure(self, account_state, ticker: str) -> bool:
        for position in account_state.combined_positions().values():
            if position.ticker == ticker and position.option_type:
                return True
        for position in self.positions.values():
            if position.get("ticker") == ticker:
                return True
        return False

    def _select_option_contract(
        self,
        *,
        ticker: str,
        action: str,
        confidence: float,
        expected_return: float,
        spot: float,
    ) -> dict[str, Any] | None:
        contract = self._contract_resolver.resolve_for_signal(
            ticker=ticker,
            action=action,
            confidence=confidence,
            expected_return=expected_return,
            spot=spot,
            expiry_days=self.expiry_days,
            strike_steps_from_atm=self.strike_steps_from_atm,
            min_days_to_expiry=self.min_days_to_expiry,
            option_bias=self.option_bias,
            adapter=self._adapter,
        )
        return contract.as_dict() if contract is not None else None

    def _estimate_live_option_price(self, position: dict[str, Any], adapter: Any) -> float:
        ticker = position["ticker"]
        try:
            spot = float(adapter.get_ltp(ticker).get("ltp") or position.get("underlying_spot") or 0)
        except Exception:
            spot = float(position.get("underlying_spot") or 0)
        if spot <= 0:
            return float(position.get("current_price") or position["entry_price"])
        position["underlying_spot"] = spot
        premium = _estimate_option_premium(
            spot=spot,
            strike=float(position["strike"]),
            option_type=str(position["option_type"]),
            days_to_expiry=max(days_to_expiry(str(position["expiry"])), 1),
            confidence=float(position.get("confidence") or self.min_confidence),
            expected_return=float(position.get("expected_return") or 0.0),
        )
        return premium

    def _run_cycle(self) -> None:
        self.cycle_count += 1
        self.last_cycle = _timestamp_now()
        adapter = self._get_adapter()
        risk = self._get_risk_manager()
        risk.tick_cycle()

        account_state = self._refresh_account_state()
        self._sync_bot_positions(account_state)

        for position_key in list(self.positions.keys()):
            self._check_exit(position_key, adapter)

        account_state = self._refresh_account_state()
        self._sync_bot_positions(account_state)

        for ticker in self.watchlist:
            if len(self.positions) >= self.max_positions:
                break
            if self._has_underlying_exposure(account_state, ticker):
                continue

            try:
                signal = self._generate_signal(
                    ticker=ticker,
                    adapter=adapter,
                    account_state=account_state,
                )
                self._last_signal_scan = _timestamp_now()
                if not signal:
                    continue

                action = signal.action
                confidence = float(signal.confidence or 0.0)
                if action not in {"buy", "sell"} or confidence < self.min_confidence:
                    continue

                spot = 0.0
                prediction = signal.metadata.get("prediction") if isinstance(signal.metadata, dict) else None
                if isinstance(prediction, dict):
                    spot = float(prediction.get("close") or 0)
                if spot <= 0:
                    spot = float(adapter.get_ltp(ticker).get("ltp") or 0)
                if spot <= 0:
                    continue

                contract = self._select_option_contract(
                    ticker=ticker,
                    action=action,
                    confidence=confidence,
                    expected_return=float(signal.expected_return),
                    spot=spot,
                )
                if not contract:
                    continue

                if account_state.has_position(
                    ticker,
                    contract["option_type"],
                    contract["strike"],
                    contract["expiry"],
                ) or account_state.has_open_order(
                    ticker,
                    None,
                    contract["option_type"],
                    contract["strike"],
                    contract["expiry"],
                ):
                    continue

                quantity = risk.size_position(
                    price=float(contract["premium"]),
                    account_state=account_state,
                    stop_loss_pct=self.stop_loss_pct,
                    signal_strength=max(signal.signal_strength, confidence),
                    existing_symbol_exposure=0.0,
                )
                if quantity <= 0:
                    continue
                risk_key = contract["contract_key"]

                outcome = self._execution_engine.execute_with_adapter(
                    adapter=adapter,
                    order_intent={
                        "ticker": ticker,
                        "side": "buy",
                        "quantity": quantity,
                        "order_type": "market",
                        "option_type": contract["option_type"],
                        "strike": contract["strike"],
                        "expiry": contract["expiry"],
                        "strategy": "single",
                        "signal_strength": signal.signal_strength or confidence,
                    },
                    current_price=contract["premium"],
                    risk_manager=risk,
                    expected_return_pct=signal.expected_return,
                    stop_loss_pct=self.stop_loss_pct,
                )
                if not outcome.accepted:
                    self._record_error(outcome.reason or f"Options entry rejected for {contract['contract_label']}")
                    continue

                result = outcome.broker_result or {}
                filled_price = float(result.get("filled_price") or contract["premium"])
                account_state = outcome.account_state_after
                self._sync_bot_positions(account_state)
                held_qty = account_state.held_quantity(
                    ticker,
                    contract["option_type"],
                    contract["strike"],
                    contract["expiry"],
                )
                if held_qty > 0:
                    entry_price = account_state.average_buy_price(
                        ticker,
                        contract["option_type"],
                        contract["strike"],
                        contract["expiry"],
                    ) or filled_price
                    self.positions[risk_key] = {
                        "ticker": ticker,
                        "contract_label": contract["contract_label"],
                        "side": "buy",
                        "quantity": held_qty,
                        "entry_price": entry_price,
                        "current_price": filled_price,
                        "option_type": contract["option_type"],
                        "strike": contract["strike"],
                        "expiry": contract["expiry"],
                        "underlying_spot": spot,
                        "confidence": confidence,
                        "signal_strength": signal.signal_strength,
                        "expected_return": float(signal.expected_return),
                        "strategy": signal.strategy,
                        "entry_reason": signal.reason,
                        "pnl": 0.0,
                        "net_pnl": 0.0,
                        "order_id": result.get("order_id", ""),
                        "entered_at": _timestamp_now(),
                    }
                    risk.register_entry(risk_key, "buy", entry_price, held_qty)

                self._record_trade(
                    {
                        "ticker": ticker,
                        "contract": contract["contract_label"],
                        "action": "ENTRY",
                        "side": "buy",
                        "quantity": quantity,
                        "price": filled_price,
                        "confidence": confidence,
                        "signal_strength": round(signal.signal_strength, 4),
                        "expected_return": round(signal.expected_return, 6),
                        "strategy": signal.strategy,
                        "entry_reason": signal.reason,
                        "status": result.get("status", "placed"),
                    }
                )
                logger.info(
                    "Options bot entered %s @ Rs%.2f (conf=%.2f)",
                    contract["contract_label"],
                    filled_price,
                    confidence,
                )
            except Exception as exc:  # pragma: no cover - long-running path
                self._record_error(f"Option scan {ticker}: {exc}")

    def _check_exit(self, position_key: str, adapter: Any) -> None:
        position = self.positions.get(position_key)
        if not position:
            return

        ticker = position["ticker"]
        option_type = position["option_type"]
        strike = position["strike"]
        expiry = position["expiry"]
        account_state = self._refresh_account_state()
        if not account_state.has_position(ticker, option_type, strike, expiry):
            del self.positions[position_key]
            return

        held_qty = account_state.held_quantity(ticker, option_type, strike, expiry)
        if held_qty <= 0:
            del self.positions[position_key]
            return

        current = float(self._estimate_live_option_price(position, adapter))
        position["current_price"] = round(current, 2)
        position["quantity"] = held_qty
        entry = float(position["entry_price"])
        gross_pnl = (current - entry) * held_qty
        pnl_pct = (current - entry) / entry if entry > 0 else 0.0
        position["pnl"] = round(gross_pnl, 2)
        position["net_pnl"] = round(gross_pnl, 2)

        risk = self._get_risk_manager()
        exit_reason = None
        should_trail, trail_reason = risk.check_exit(position_key, current)
        if should_trail:
            exit_reason = trail_reason
        if exit_reason is None and pnl_pct <= -self.stop_loss_pct:
            exit_reason = "STOP_LOSS"
        if exit_reason is None and pnl_pct >= self.take_profit_pct:
            exit_reason = "TAKE_PROFIT"
        if exit_reason is None and days_to_expiry(str(expiry)) <= self.min_days_to_expiry:
            exit_reason = "EXPIRY_RISK"
        if exit_reason is None:
            return

        validation = validate_trade_against_account_state(
            {
                "ticker": ticker,
                "side": "sell",
                "quantity": held_qty,
                "option_type": option_type,
                "strike": strike,
                "expiry": expiry,
                "strategy": "single",
            },
            account_state,
            current_price=current,
            rules=self._validation_rules(),
        )
        if not validation.allowed:
            self._record_error(validation.reason)
            return

        outcome = self._execution_engine.execute_with_adapter(
            adapter=adapter,
            order_intent={
                "ticker": ticker,
                "side": "sell",
                "quantity": held_qty,
                "order_type": "market",
                "option_type": option_type,
                "strike": strike,
                "expiry": expiry,
                "strategy": "single",
            },
            current_price=current,
            risk_manager=risk,
            stop_loss_pct=self.stop_loss_pct,
        )
        if not outcome.accepted:
            self._record_error(outcome.reason or f"Options exit rejected for {position['contract_label']}")
            return

        remaining_qty = outcome.account_state_after.held_quantity(ticker, option_type, strike, expiry)
        if remaining_qty >= held_qty and outcome.account_state_after.has_open_order(ticker, "sell", option_type, strike, expiry):
            position["pending_exit"] = True
            position["exit_order_id"] = outcome.broker_result.get("order_id", "") if outcome.broker_result else ""
            logger.info("Options exit order placed for %s; waiting for broker confirmation", position["contract_label"])
            return

        self.total_pnl += gross_pnl
        risk.register_exit(position_key, gross_pnl, exit_reason)
        self._record_trade(
            {
                "ticker": ticker,
                "contract": position["contract_label"],
                "action": exit_reason,
                "side": "sell",
                "quantity": held_qty,
                "price": round(current, 2),
                "gross_pnl": round(gross_pnl, 2),
                "charges": 0.0,
                "net_pnl": round(gross_pnl, 2),
                "strategy": position.get("strategy", self.strategy_name),
                "exit_reason": exit_reason,
                "status": outcome.status,
            }
        )

        if not outcome.account_state_after.has_position(ticker, option_type, strike, expiry):
            del self.positions[position_key]
        else:
            position["quantity"] = outcome.account_state_after.held_quantity(ticker, option_type, strike, expiry)
            position["entry_price"] = outcome.account_state_after.average_buy_price(ticker, option_type, strike, expiry) or position["entry_price"]
            position.pop("pending_exit", None)
            position.pop("exit_order_id", None)


_bot = TradingBot()
_options_bot = OptionsTradingBot()


def _runtime_health_payload() -> dict[str, Any]:
    market = get_market_status()
    equity_status = _bot.status
    options_status = _options_bot.status
    return {
        "service_mode": settings.service_mode,
        "run_mode": settings.run_mode,
        "paper_mode": settings.PAPER_MODE,
        "live_broker_enabled": settings.live_broker_enabled,
        "market": {
            "phase": market.phase.value,
            "message": market.message,
            "next_event": market.next_event,
            "next_event_time": market.next_event_time,
        },
        "bots": {
            "equity": {
                "running": equity_status["running"],
                "paused": equity_status["paused"],
                "active_positions": equity_status["active_positions"],
                "last_cycle": equity_status["last_cycle"],
                "errors": len(equity_status["errors"]),
                "runtime_health": equity_status["runtime_health"],
            },
            "options": {
                "running": options_status["running"],
                "paused": options_status["paused"],
                "active_positions": options_status["active_positions"],
                "last_cycle": options_status["last_cycle"],
                "errors": len(options_status["errors"]),
                "runtime_health": options_status["runtime_health"],
            },
        },
    }


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
    _bot._apply_config(config)
    _bot._refresh_runtime_dependencies()
    record_audit_event(
        "BOT_CONFIG_UPDATED",
        entity_type="bot",
        entity_id=_bot.bot_type,
        data={"bot_label": _bot.bot_label, "config": config},
        source="market_router",
    )
    return {"status": "updated", "config": _bot.status}


@router.post("/bot/consent")
async def bot_consent(action: dict | None = None):
    resume = True
    if action and "resume" in action:
        resume = action["resume"]
    if resume:
        return _bot.grant_consent()
    return _bot.decline_consent()


@router.post("/bot/options/start")
async def options_bot_start(config: dict | None = None):
    return _options_bot.start(config)


@router.post("/bot/options/stop")
async def options_bot_stop():
    return _options_bot.stop()


@router.get("/bot/options/status")
async def options_bot_status():
    return _options_bot.status


@router.put("/bot/options/config")
async def options_bot_config(config: dict):
    _options_bot._apply_config(config)
    _options_bot._refresh_runtime_dependencies()
    record_audit_event(
        "BOT_CONFIG_UPDATED",
        entity_type="bot",
        entity_id=_options_bot.bot_type,
        data={"bot_label": _options_bot.bot_label, "config": config},
        source="market_router",
    )
    return {"status": "updated", "config": _options_bot.status}


@router.post("/bot/options/consent")
async def options_bot_consent(action: dict | None = None):
    resume = True
    if action and "resume" in action:
        resume = action["resume"]
    if resume:
        return _options_bot.grant_consent()
    return _options_bot.decline_consent()


@router.get("/bot/runtime-health")
async def bot_runtime_health():
    return _runtime_health_payload()
