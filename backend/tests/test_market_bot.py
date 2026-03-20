from __future__ import annotations

from types import SimpleNamespace

from backend.api.routers.market import OptionsTradingBot, TradingBot


def _fake_market(phase: str):
    return SimpleNamespace(
        phase=SimpleNamespace(value=phase),
        message="",
        ist_now="",
        next_event="",
        next_event_time="",
        seconds_to_next=0,
        is_trading_day=True,
    )


def test_bot_start_closed_market_enters_standby(monkeypatch):
    bot = TradingBot()

    monkeypatch.setattr(
        "backend.api.routers.market.get_market_status",
        lambda: _fake_market("closed"),
    )
    monkeypatch.setattr(
        TradingBot,
        "_refresh_account_state",
        lambda self: setattr(self, "_available_balance", 100000.0) or setattr(self, "_total_equity", 100000.0) or SimpleNamespace(),
    )
    monkeypatch.setattr(TradingBot, "_run_loop", lambda self: None)

    result = bot.start()

    assert result["status"] == "started"
    assert "standby mode" in result["message"].lower()
    assert bot._paused_for_market_close is True
    assert bot._consent_pending is False
    assert bot._auto_resume_seconds == 300
    bot.stop()


def test_bot_reopen_requests_consent():
    bot = TradingBot()
    bot._paused_for_market_close = True
    bot._consent_pending = False

    bot._check_market_reopen()

    assert bot._consent_pending is True
    assert bot._consent_requested_at is not None
    assert bot.status["auto_resume_in"] <= 300


def test_bot_grant_consent_resumes():
    bot = TradingBot()
    bot._paused_for_market_close = True
    bot._consent_pending = True
    bot._consent_requested_at = 1.0

    result = bot.grant_consent()

    assert result["status"] == "resumed"
    assert bot._paused_for_market_close is False
    assert bot._consent_pending is False
    assert bot._consent_requested_at is None


def test_options_bot_starts_in_paper_mode(monkeypatch):
    bot = OptionsTradingBot()

    monkeypatch.setattr(
        "backend.api.routers.market.get_market_status",
        lambda: _fake_market("open"),
    )
    monkeypatch.setattr(
        OptionsTradingBot,
        "_refresh_account_state",
        lambda self: setattr(self, "_available_balance", 100000.0)
        or setattr(self, "_total_equity", 100000.0)
        or SimpleNamespace(account_type="paper"),
    )
    monkeypatch.setattr(OptionsTradingBot, "_run_loop", lambda self: None)

    result = bot.start()

    assert result["status"] == "started"
    assert bot.running is True
    assert bot.status["runtime_health"]["paper_only"] is True
    bot.stop()


def test_options_bot_rejects_live_mode_without_option_support(monkeypatch):
    bot = OptionsTradingBot()

    monkeypatch.setattr(
        "backend.api.routers.market.get_market_status",
        lambda: _fake_market("open"),
    )
    monkeypatch.setattr(
        OptionsTradingBot,
        "_refresh_account_state",
        lambda self: setattr(self, "_available_balance", 100000.0)
        or setattr(self, "_total_equity", 100000.0)
        or SimpleNamespace(account_type="real"),
    )
    monkeypatch.setattr(OptionsTradingBot, "_run_loop", lambda self: None)
    monkeypatch.setattr(OptionsTradingBot, "_supports_live_execution", lambda self: False)

    result = bot.start()

    assert result["status"] == "error"
    assert "paper mode only" in result["message"].lower()
