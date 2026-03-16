"""Market status, account verification, and auto-trading bot endpoints."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.core.config import settings
from backend.services.market_hours import get_market_status

logger = logging.getLogger(__name__)

router = APIRouter(tags=["market"])


# ── Market Status ──────────────────────────────────────────────────────────

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


# ── Account Verification ──────────────────────────────────────────────────

def _get_angel_profile() -> dict[str, Any]:
    """Connect to AngelOne SmartAPI and fetch profile + balance.

    Returns dict with keys: name, client_id, email, phone, balance, net, available_margin, status.
    """
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
            "message": "Credentials verified – connected to AngelOne",
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
    except Exception as exc:
        logger.exception("Account verification failed")
        return {
            "status": "error",
            "message": str(exc),
        }


@router.get("/account/profile")
async def account_profile():
    """Verify AngelOne credentials and fetch account name, balance, margin."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _get_angel_profile)
    return result


# ── Auto-Trading Bot ───────────────────────────────────────────────────────

class TradingBot:
    """Automated trading bot that runs predictions and executes trades.

    Flow:
    1. Bot starts with a watchlist of tickers
    2. Every cycle: fetch predictions → filter by confidence → check risk → execute
    3. Manage positions with trailing stop-loss / take-profit
    4. All P&L is computed NET of Angel One brokerage charges
    5. Respects market hours – pauses when closed, resumes with consent flow
    """

    def __init__(self) -> None:
        self.running = False
        self.watchlist: list[str] = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
        self.min_confidence: float = 0.7
        self.max_positions: int = 5
        self.position_size_pct: float = 0.10  # 10% of available balance per trade
        self.stop_loss_pct: float = 0.02  # 2%
        self.take_profit_pct: float = 0.05  # 5%
        self.cycle_interval: int = 60  # seconds between cycles
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.trades_today: list[dict] = []
        self.total_pnl: float = 0.0
        self.total_charges: float = 0.0
        self.positions: dict[str, dict] = {}
        self.cycle_count: int = 0
        self.last_cycle: str | None = None
        self.errors: list[str] = []
        # Balance from broker (refreshed each cycle)
        self._available_balance: float = 0.0
        self._total_equity: float = 0.0
        # Risk manager (initialised lazily with actual capital)
        self._risk_mgr: Any = None
        # Adapter singleton (kept alive for balance tracking in paper mode)
        self._adapter: Any = None
        # Market session tracking – consent flow
        self._paused_for_market_close: bool = False
        self._consent_pending: bool = False
        self._consent_requested_at: float | None = None
        self._auto_resume_seconds: int = 600  # 10 minutes

    def _get_risk_manager(self):
        if self._risk_mgr is None:
            from backend.services.risk_manager import RiskManager, RiskConfig
            config = RiskConfig(
                max_position_pct=self.position_size_pct,
                max_daily_loss=5_000.0,
                max_daily_loss_pct=0.02,
                trailing_stop_pct=0.015,
                min_risk_reward_ratio=2.0,
                max_open_positions=self.max_positions,
                cooldown_after_loss=2,
            )
            # Use real balance from the adapter
            capital = self._available_balance or 100_000.0
            self._risk_mgr = RiskManager(capital, config)
        return self._risk_mgr

    def _get_adapter(self):
        """Return a persistent adapter instance (paper mode needs it for balance tracking)."""
        if self._adapter is None:
            from backend.trading_engine.angel_adapter import get_adapter
            self._adapter = get_adapter()
        return self._adapter

    def _refresh_balance(self) -> None:
        """Fetch balance from the broker adapter and update risk manager capital."""
        try:
            adapter = self._get_adapter()
            bal = adapter.get_balance()
            self._available_balance = bal.get("available_cash", 0)
            self._total_equity = bal.get("total_equity", self._available_balance)
            # Keep risk manager in sync
            risk = self._get_risk_manager()
            risk.update_capital(self._available_balance)
            logger.debug("Balance refreshed: available=₹%.2f, equity=₹%.2f",
                         self._available_balance, self._total_equity)
        except Exception as exc:
            logger.warning("Balance refresh failed: %s", exc)
        return self._risk_mgr

    @property
    def status(self) -> dict:
        risk = self._get_risk_manager().status if self._risk_mgr else {}
        # Compute auto-resume countdown
        auto_resume_in = None
        if self._consent_pending and self._consent_requested_at:
            elapsed = time.time() - self._consent_requested_at
            remaining = max(0, self._auto_resume_seconds - elapsed)
            auto_resume_in = int(remaining)
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
            "active_positions": len(self.positions),
            "positions": self.positions,
            "trades_today": self.trades_today[-20:],  # last 20
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
            if "watchlist" in config:
                self.watchlist = config["watchlist"]
            if "min_confidence" in config:
                self.min_confidence = config["min_confidence"]
            if "max_positions" in config:
                self.max_positions = config["max_positions"]
            if "position_size_pct" in config:
                self.position_size_pct = config["position_size_pct"]
            if "stop_loss_pct" in config:
                self.stop_loss_pct = config["stop_loss_pct"]
            if "take_profit_pct" in config:
                self.take_profit_pct = config["take_profit_pct"]
            if "cycle_interval" in config:
                self.cycle_interval = config["cycle_interval"]

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
        self._risk_mgr = None  # re-init with fresh state
        self._adapter = None   # fresh adapter for balance tracking

        # Fetch initial balance before first cycle
        self._refresh_balance()
        if self._available_balance <= 0:
            self.running = False
            return {
                "status": "error",
                "message": "Cannot start bot: available balance is ₹0. "
                           "Check your broker account or PAPER_BALANCE env var.",
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
        """Main bot loop – runs in background thread.

        When market closes, the bot pauses (doesn't stop).
        When market reopens, it requests user consent and auto-resumes
        after 10 minutes if no response.
        """
        was_market_open = False

        while not self._stop_event.is_set():
            try:
                market = get_market_status()
                is_open = market.phase.value in ("open", "pre_open")

                if is_open and self._paused_for_market_close:
                    # Market just reopened after being closed — trigger consent
                    self._check_market_reopen()

                if is_open:
                    if self._consent_pending:
                        # Check if auto-resume timer expired
                        elapsed = time.time() - (self._consent_requested_at or 0)
                        if elapsed >= self._auto_resume_seconds:
                            logger.info("Auto-resuming bot after %ds (no user response)",
                                        self._auto_resume_seconds)
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
                    # Market is closed
                    if was_market_open and not self._paused_for_market_close:
                        self._paused_for_market_close = True
                        logger.info("Market closed — bot paused, waiting for next session")
                    was_market_open = False
                    self._stop_event.wait(30)
                    continue

            except Exception as exc:
                msg = f"Bot cycle error: {exc}"
                logger.exception(msg)
                self.errors.append(msg)

            self._stop_event.wait(self.cycle_interval)

    def _check_market_reopen(self) -> None:
        """Called when market transitions from closed to open."""
        if self._paused_for_market_close and not self._consent_pending:
            self._consent_pending = True
            self._consent_requested_at = time.time()
            logger.info("Market reopened — requesting user consent (auto-resume in %ds)",
                        self._auto_resume_seconds)

    def grant_consent(self) -> dict:
        """User grants consent to resume trading."""
        if not self._consent_pending:
            return {"status": "no_consent_needed", "message": "No consent request pending"}
        self._consent_pending = False
        self._paused_for_market_close = False
        self._consent_requested_at = None
        logger.info("User granted consent — bot resuming")
        return {"status": "resumed", "message": "Trading resumed with user consent"}

    def decline_consent(self) -> dict:
        """User declines to resume — stop the bot."""
        if not self._consent_pending:
            return {"status": "no_consent_needed", "message": "No consent request pending"}
        self._consent_pending = False
        self._paused_for_market_close = False
        self._consent_requested_at = None
        return self.stop()

    def _run_cycle(self) -> None:
        """Single trading cycle: predict → risk check → trade → manage exits."""
        from backend.services.model_manager import ModelManager
        from backend.services.brokerage_calculator import (
            estimate_breakeven_move, net_pnl_after_charges, TradeType,
        )

        self.cycle_count += 1
        self.last_cycle = datetime.now(timezone.utc).isoformat()

        adapter = self._get_adapter()
        mgr = ModelManager()
        risk = self._get_risk_manager()
        risk.tick_cycle()

        # Refresh balance from broker every cycle
        self._refresh_balance()

        # --- Check exits on existing positions first ---
        for ticker in list(self.positions.keys()):
            self._check_exit(ticker, adapter)

        # --- New entries ---
        for ticker in self.watchlist:
            if len(self.positions) >= self.max_positions:
                break

            if ticker in self.positions:
                continue

            try:
                prediction = mgr.predict(ticker, horizon_days=1)
                if prediction is None:
                    continue

                action = prediction.get("action", "hold")
                confidence = prediction.get("confidence", 0)

                if action == "hold" or confidence < self.min_confidence:
                    continue

                price = prediction.get("predicted_price", 100)
                if price <= 0:
                    continue

                # Size position based on available balance
                max_trade_value = self._available_balance * self.position_size_pct
                if max_trade_value < price:
                    logger.debug(
                        "Skipping %s: insufficient balance for even 1 share "
                        "(need %.2f, max %.2f)", ticker, price, max_trade_value,
                    )
                    continue
                qty = max(1, int(max_trade_value / price))

                # Check if trade is worth it after charges
                breakeven_move = estimate_breakeven_move(price, qty, TradeType.INTRADAY)
                expected_profit = price * prediction.get("expected_return", 0.02)
                if expected_profit < breakeven_move:
                    logger.debug("Skipping %s: expected profit ₹%.2f < breakeven ₹%.2f",
                                 ticker, expected_profit, breakeven_move)
                    continue

                # Risk manager gate
                allowed, reason = risk.can_open_position(ticker, price, qty)
                if not allowed:
                    logger.debug("Risk blocked %s: %s", ticker, reason)
                    continue

                intent = {
                    "ticker": ticker,
                    "side": "buy" if action == "buy" else "sell",
                    "quantity": qty,
                    "order_type": "market",
                    "current_price": price,
                }

                result = adapter.place_order(intent)
                filled_price = result.get("filled_price", price)

                # Register with risk manager
                risk.register_entry(ticker, intent["side"], filled_price, qty)

                self.positions[ticker] = {
                    "side": intent["side"],
                    "quantity": qty,
                    "entry_price": filled_price,
                    "current_price": filled_price,
                    "pnl": 0.0,
                    "net_pnl": 0.0,
                    "charges_estimate": round(estimate_breakeven_move(filled_price, qty, TradeType.INTRADAY) * qty, 2),
                    "order_id": result.get("order_id", ""),
                    "entered_at": datetime.now(timezone.utc).isoformat(),
                }

                trade_record = {
                    "ticker": ticker,
                    "action": "ENTRY",
                    "side": intent["side"],
                    "quantity": qty,
                    "price": filled_price,
                    "confidence": confidence,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                self.trades_today.append(trade_record)
                logger.info("Bot entered %s %s @ ₹%.2f (conf=%.2f)", intent["side"], ticker, filled_price, confidence)

            except Exception as exc:
                self.errors.append(f"Predict/trade {ticker}: {exc}")

    def _check_exit(self, ticker: str, adapter: Any) -> None:
        """Check if a position should be exited (trailing stop, stop-loss, or take-profit).

        Uses the adapter's LTP method for real/paper prices instead of random simulation.
        All P&L is calculated NET of Angel One charges.
        """
        from backend.services.brokerage_calculator import net_pnl_after_charges, TradeType

        pos = self.positions.get(ticker)
        if not pos:
            return

        # Fetch live/paper price from the adapter
        try:
            ltp_data = adapter.get_ltp(ticker)
            current = ltp_data.get("ltp", pos["entry_price"])
        except Exception:
            # Fallback: use entry price (no action taken on price fetch failure)
            current = pos["current_price"]

        pos["current_price"] = round(current, 2)

        entry = pos["entry_price"]
        qty = pos["quantity"]

        # Gross P&L
        if pos["side"] == "buy":
            gross_pnl = (current - entry) * qty
            pnl_pct = (current - entry) / entry
        else:
            gross_pnl = (entry - current) * qty
            pnl_pct = (entry - current) / entry

        # Net P&L after charges
        if pos["side"] == "buy":
            net_pnl = net_pnl_after_charges(entry, current, qty, TradeType.INTRADAY)
        else:
            net_pnl = net_pnl_after_charges(current, entry, qty, TradeType.INTRADAY)

        pos["pnl"] = round(gross_pnl, 2)
        pos["net_pnl"] = round(net_pnl, 2)

        # Check exit conditions
        risk = self._get_risk_manager()
        exit_reason = None

        # 1. Trailing stop (from risk manager)
        should_trail, trail_reason = risk.check_exit(ticker, current)
        if should_trail:
            exit_reason = trail_reason

        # 2. Hard stop-loss
        if exit_reason is None and pnl_pct <= -self.stop_loss_pct:
            exit_reason = "STOP_LOSS"

        # 3. Take-profit
        if exit_reason is None and pnl_pct >= self.take_profit_pct:
            exit_reason = "TAKE_PROFIT"

        if exit_reason:
            exit_side = "sell" if pos["side"] == "buy" else "buy"
            adapter.place_order({
                "ticker": ticker,
                "side": exit_side,
                "quantity": qty,
                "order_type": "market",
                "current_price": current,
            })

            charges = gross_pnl - net_pnl
            self.total_pnl += gross_pnl
            self.total_charges += charges
            risk.register_exit(ticker, net_pnl, exit_reason)

            trade_record = {
                "ticker": ticker,
                "action": exit_reason,
                "side": exit_side,
                "quantity": qty,
                "price": round(current, 2),
                "gross_pnl": round(gross_pnl, 2),
                "charges": round(charges, 2),
                "net_pnl": round(net_pnl, 2),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self.trades_today.append(trade_record)
            logger.info(
                "Bot exited %s (%s) @ ₹%.2f, Gross: ₹%.2f, Charges: ₹%.2f, Net: ₹%.2f",
                ticker, exit_reason, current, gross_pnl, charges, net_pnl,
            )
            del self.positions[ticker]


# Singleton bot instance
_bot = TradingBot()


@router.post("/bot/start")
async def bot_start(config: dict | None = None):
    """Start the auto-trading bot with optional configuration."""
    result = _bot.start(config)
    return result


@router.post("/bot/stop")
async def bot_stop():
    """Stop the auto-trading bot."""
    result = _bot.stop()
    return result


@router.get("/bot/status")
async def bot_status():
    """Get current bot status, positions, and trade log."""
    return _bot.status


@router.put("/bot/config")
async def bot_config(config: dict):
    """Update bot configuration without restarting."""
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
    return {"status": "updated", "config": _bot.status}


@router.post("/bot/consent")
async def bot_consent(action: dict | None = None):
    """User responds to the consent prompt when market reopens.

    Body: {"resume": true} to resume, {"resume": false} to stop.
    """
    resume = True
    if action and "resume" in action:
        resume = action["resume"]
    if resume:
        return _bot.grant_consent()
    else:
        return _bot.decline_consent()
