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
        self._auto_resume_seconds: int = 300

    def _market_is_open(self) -> bool:
        status = get_market_status()
        return status.phase.value in ("open", "pre_open")

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

        market_open = self._market_is_open()
        if not market_open:
            self._paused_for_market_close = True

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Trading bot started with watchlist: %s", self.watchlist)
        if market_open:
            message = "Bot started"
        else:
            message = (
                "Bot started in standby mode because the market is closed. "
                "It will request consent when the market opens and auto-resume after 5 minutes."
            )
        return {"status": "started", "message": message, "config": self.status}

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
                    if not self._paused_for_market_close:
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
