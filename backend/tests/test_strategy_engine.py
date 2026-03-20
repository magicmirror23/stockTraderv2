from __future__ import annotations

import pandas as pd

from backend.trading_engine.account_state import AccountState
from backend.trading_engine.strategies import (
    EnsembleStrategy,
    MLPredictionStrategy,
    MovingAverageCrossoverStrategy,
    RSIStrategy,
    StrategyMarketData,
)
from backend.trading_engine.strategies.base import BaseStrategy, StrategySignal


def _portfolio_state() -> AccountState:
    return AccountState(
        account_type="paper",
        available_cash=100000.0,
        buying_power=100000.0,
        total_equity=100000.0,
    )


def test_moving_average_crossover_generates_buy_signal():
    history = pd.DataFrame(
        {
            "Close": [
                100,
                99,
                98,
                97,
                96,
                95,
                94,
                93,
                92,
                91,
                90,
                91,
                92,
                93,
                94,
                95,
                96,
                97,
                98,
                82,
                90,
                130,
            ]
        }
    )
    strategy = MovingAverageCrossoverStrategy(short_window=3, long_window=5)

    signal = strategy.generate_signal(
        StrategyMarketData(ticker="RELIANCE", spot_price=130.0, history=history),
        _portfolio_state(),
    )

    assert signal.action == "buy"
    assert signal.strategy == "moving_average_crossover"
    assert signal.confidence >= 0.55


def test_rsi_strategy_generates_buy_signal_on_oversold_history():
    history = pd.DataFrame({"Close": [120, 118, 116, 114, 112, 110, 108, 106, 104, 102, 100, 98, 96, 94, 92, 91]})
    strategy = RSIStrategy(period=5, oversold=35.0, overbought=70.0)

    signal = strategy.generate_signal(
        StrategyMarketData(ticker="INFY", spot_price=91.0, history=history),
        _portfolio_state(),
    )

    assert signal.action == "buy"
    assert signal.strategy == "rsi"
    assert signal.metadata["rsi"] <= 35.0


def test_ml_prediction_strategy_wraps_prediction_payload():
    class FakeModelManager:
        def predict(self, ticker: str, horizon_days: int = 1) -> dict[str, object]:
            assert ticker == "TCS"
            assert horizon_days == 1
            return {
                "action": "buy",
                "confidence": 0.82,
                "expected_return": 0.021,
                "net_expected_return": 0.018,
                "model_version": "unit-test-model",
                "fallback": False,
                "close": 3500.0,
                "explanation": {"summary": "Momentum and news are aligned."},
            }

    strategy = MLPredictionStrategy(model_manager=FakeModelManager())
    signal = strategy.generate_signal(
        StrategyMarketData(ticker="TCS", spot_price=3500.0),
        _portfolio_state(),
    )

    assert signal.action == "buy"
    assert signal.confidence == 0.82
    assert signal.expected_return == 0.018
    assert signal.reason == "Momentum and news are aligned."
    assert signal.metadata["prediction"]["model_version"] == "unit-test-model"


def test_ensemble_strategy_combines_member_signals():
    class FixedStrategy(BaseStrategy):
        def __init__(self, name: str, signal: StrategySignal) -> None:
            self.name = name
            self._signal = signal

        def generate_signal(self, market_data: StrategyMarketData, portfolio_state: AccountState) -> StrategySignal:
            del market_data, portfolio_state
            return self._signal

    ensemble = EnsembleStrategy(
        members=[
            FixedStrategy("trend", StrategySignal(action="buy", confidence=0.8, expected_return=0.02, strategy="trend")),
            FixedStrategy("ml", StrategySignal(action="buy", confidence=0.75, expected_return=0.015, strategy="ml")),
            FixedStrategy("mean_revert", StrategySignal(action="hold", confidence=0.4, expected_return=0.0, strategy="mean_revert")),
        ]
    )

    signal = ensemble.generate_signal(
        StrategyMarketData(ticker="SBIN", spot_price=750.0),
        _portfolio_state(),
    )

    assert signal.action == "buy"
    assert signal.strategy == "ensemble"
    assert signal.metadata["components"][0]["strategy"] in {"trend", "ml", "mean_revert"}
