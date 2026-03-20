"""Open-source technical strategies used by automation bots and research."""

from __future__ import annotations

import pandas as pd

from backend.trading_engine.account_state import AccountState
from backend.trading_engine.strategies.base import BaseStrategy, StrategyMarketData, StrategySignal, hold_signal


def _close_series(history: pd.DataFrame | None) -> pd.Series | None:
    if history is None or history.empty or "Close" not in history.columns:
        return None
    closes = pd.to_numeric(history["Close"], errors="coerce").dropna()
    if closes.empty:
        return None
    return closes.reset_index(drop=True)


def _signal_confidence(edge: float, floor: float = 0.55) -> float:
    edge = max(edge, 0.0)
    return round(min(0.95, floor + edge), 4)


class MovingAverageCrossoverStrategy(BaseStrategy):
    name = "moving_average_crossover"
    description = "Short/long moving average crossover trend strategy"

    def __init__(self, short_window: int = 5, long_window: int = 20) -> None:
        self.short_window = short_window
        self.long_window = long_window

    def generate_signal(self, market_data: StrategyMarketData, portfolio_state: AccountState) -> StrategySignal:
        del portfolio_state
        closes = _close_series(market_data.history)
        if closes is None or len(closes) < max(self.short_window, self.long_window) + 1:
            return hold_signal(self.name, "Not enough history for moving averages.")

        short_ma = closes.rolling(self.short_window).mean()
        long_ma = closes.rolling(self.long_window).mean()
        prev_short = float(short_ma.iloc[-2])
        prev_long = float(long_ma.iloc[-2])
        curr_short = float(short_ma.iloc[-1])
        curr_long = float(long_ma.iloc[-1])
        gap_pct = abs(curr_short - curr_long) / max(market_data.spot_price, 1.0)
        confidence = _signal_confidence(min(gap_pct * 8, 0.35))

        if curr_short > curr_long and prev_short <= prev_long:
            return StrategySignal(
                action="buy",
                confidence=confidence,
                expected_return=round(min(gap_pct * 2.5, 0.03), 4),
                signal_strength=round(gap_pct, 4),
                reason=f"Short MA {curr_short:.2f} crossed above long MA {curr_long:.2f}.",
                strategy=self.name,
                metadata={"short_ma": round(curr_short, 2), "long_ma": round(curr_long, 2)},
            )
        if curr_short < curr_long and prev_short >= prev_long:
            return StrategySignal(
                action="sell",
                confidence=confidence,
                expected_return=round(min(gap_pct * 2.5, 0.03), 4),
                signal_strength=round(gap_pct, 4),
                reason=f"Short MA {curr_short:.2f} crossed below long MA {curr_long:.2f}.",
                strategy=self.name,
                metadata={"short_ma": round(curr_short, 2), "long_ma": round(curr_long, 2)},
            )
        return hold_signal(self.name, "No crossover signal.", {"short_ma": round(curr_short, 2), "long_ma": round(curr_long, 2)})


class RSIStrategy(BaseStrategy):
    name = "rsi"
    description = "RSI mean-reversion strategy"

    def __init__(self, period: int = 14, oversold: float = 30.0, overbought: float = 70.0) -> None:
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def generate_signal(self, market_data: StrategyMarketData, portfolio_state: AccountState) -> StrategySignal:
        del portfolio_state
        closes = _close_series(market_data.history)
        if closes is None or len(closes) < self.period + 1:
            return hold_signal(self.name, "Not enough history for RSI.")

        delta = closes.diff().dropna()
        gain = delta.clip(lower=0).rolling(self.period).mean()
        loss = (-delta.clip(upper=0)).rolling(self.period).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))
        current_rsi = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50.0

        if current_rsi <= self.oversold:
            edge = (self.oversold - current_rsi) / max(self.oversold, 1.0)
            return StrategySignal(
                action="buy",
                confidence=_signal_confidence(min(edge * 0.6, 0.3)),
                expected_return=round(min(edge * 0.03, 0.025), 4),
                signal_strength=round(edge, 4),
                reason=f"RSI dropped to {current_rsi:.1f}, indicating oversold conditions.",
                strategy=self.name,
                metadata={"rsi": round(current_rsi, 2)},
            )
        if current_rsi >= self.overbought:
            edge = (current_rsi - self.overbought) / max(100 - self.overbought, 1.0)
            return StrategySignal(
                action="sell",
                confidence=_signal_confidence(min(edge * 0.6, 0.3)),
                expected_return=round(min(edge * 0.03, 0.025), 4),
                signal_strength=round(edge, 4),
                reason=f"RSI rose to {current_rsi:.1f}, indicating overbought conditions.",
                strategy=self.name,
                metadata={"rsi": round(current_rsi, 2)},
            )
        return hold_signal(self.name, "RSI is neutral.", {"rsi": round(current_rsi, 2)})


class BreakoutStrategy(BaseStrategy):
    name = "breakout"
    description = "Price breakout strategy based on rolling highs and lows"

    def __init__(self, lookback: int = 20, breakout_buffer: float = 0.005) -> None:
        self.lookback = lookback
        self.breakout_buffer = breakout_buffer

    def generate_signal(self, market_data: StrategyMarketData, portfolio_state: AccountState) -> StrategySignal:
        del portfolio_state
        closes = _close_series(market_data.history)
        if closes is None or len(closes) < self.lookback + 1:
            return hold_signal(self.name, "Not enough history for breakout detection.")

        window = closes.iloc[-(self.lookback + 1):-1]
        if window.empty:
            return hold_signal(self.name, "Not enough prior bars for breakout detection.")

        prior_high = float(window.max())
        prior_low = float(window.min())
        price = float(market_data.spot_price or closes.iloc[-1])

        if price >= prior_high * (1 + self.breakout_buffer):
            edge = (price - prior_high) / max(price, 1.0)
            return StrategySignal(
                action="buy",
                confidence=_signal_confidence(min(edge * 12, 0.35)),
                expected_return=round(min(edge * 4, 0.035), 4),
                signal_strength=round(edge, 4),
                reason=f"Price broke above the {self.lookback}-bar high of {prior_high:.2f}.",
                strategy=self.name,
                metadata={"prior_high": round(prior_high, 2)},
            )

        if price <= prior_low * (1 - self.breakout_buffer):
            edge = (prior_low - price) / max(price, 1.0)
            return StrategySignal(
                action="sell",
                confidence=_signal_confidence(min(edge * 12, 0.35)),
                expected_return=round(min(edge * 4, 0.035), 4),
                signal_strength=round(edge, 4),
                reason=f"Price broke below the {self.lookback}-bar low of {prior_low:.2f}.",
                strategy=self.name,
                metadata={"prior_low": round(prior_low, 2)},
            )

        range_width = (prior_high - prior_low) / max(price, 1.0)
        return hold_signal(
            self.name,
            "Price is still inside the breakout range.",
            {"prior_high": round(prior_high, 2), "prior_low": round(prior_low, 2), "range_width": round(range_width, 4)},
        )
