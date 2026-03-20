"""Factory helpers for bot strategy configuration."""

from __future__ import annotations

from typing import Any

from backend.services.model_manager import ModelManager
from backend.trading_engine.strategies.base import BaseStrategy
from backend.trading_engine.strategies.ml import EnsembleStrategy, MLPredictionStrategy
from backend.trading_engine.strategies.technical import (
    BreakoutStrategy,
    MovingAverageCrossoverStrategy,
    RSIStrategy,
)


def available_strategies() -> list[str]:
    return [
        "ml_prediction",
        "moving_average_crossover",
        "rsi",
        "breakout",
        "ensemble",
    ]


def create_strategy(
    name: str,
    *,
    model_manager: ModelManager | None = None,
    params: dict[str, Any] | None = None,
) -> BaseStrategy:
    params = dict(params or {})
    normalized = str(name or "ml_prediction").strip().lower()

    if normalized in {"ml", "ml_prediction", "prediction"}:
        return MLPredictionStrategy(
            model_manager=model_manager,
            horizon_days=int(params.get("horizon_days", 1)),
        )
    if normalized in {"moving_average_crossover", "ma_crossover", "moving_average"}:
        return MovingAverageCrossoverStrategy(
            short_window=int(params.get("short_window", 5)),
            long_window=int(params.get("long_window", 20)),
        )
    if normalized == "rsi":
        return RSIStrategy(
            period=int(params.get("period", 14)),
            oversold=float(params.get("oversold", 30.0)),
            overbought=float(params.get("overbought", 70.0)),
        )
    if normalized == "breakout":
        return BreakoutStrategy(
            lookback=int(params.get("lookback", 20)),
            breakout_buffer=float(params.get("breakout_buffer", 0.005)),
        )
    if normalized == "ensemble":
        members = params.get("members") or ["ml_prediction", "moving_average_crossover", "rsi"]
        if isinstance(members, str):
            members = [item.strip() for item in members.split(",") if item.strip()]
        weights = params.get("weights")
        return EnsembleStrategy(
            [create_strategy(member, model_manager=model_manager, params={}) for member in members],
            weights=weights,
        )
    raise ValueError(f"Unsupported strategy '{name}'. Available: {', '.join(available_strategies())}")
