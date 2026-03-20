"""Strategy plug-ins for StockTrader bots and research flows."""

from backend.trading_engine.strategies.base import BaseStrategy, StrategyMarketData, StrategySignal, hold_signal
from backend.trading_engine.strategies.ml import EnsembleStrategy, MLPredictionStrategy
from backend.trading_engine.strategies.registry import available_strategies, create_strategy
from backend.trading_engine.strategies.technical import (
    BreakoutStrategy,
    MovingAverageCrossoverStrategy,
    RSIStrategy,
)

__all__ = [
    "BaseStrategy",
    "StrategyMarketData",
    "StrategySignal",
    "hold_signal",
    "MLPredictionStrategy",
    "EnsembleStrategy",
    "MovingAverageCrossoverStrategy",
    "RSIStrategy",
    "BreakoutStrategy",
    "available_strategies",
    "create_strategy",
]
