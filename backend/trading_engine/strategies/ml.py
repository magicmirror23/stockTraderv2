"""ML-backed and ensemble strategies."""

from __future__ import annotations

from typing import Any, Iterable

from backend.services.model_manager import ModelManager
from backend.trading_engine.account_state import AccountState
from backend.trading_engine.strategies.base import BaseStrategy, StrategyMarketData, StrategySignal, hold_signal


class MLPredictionStrategy(BaseStrategy):
    name = "ml_prediction"
    description = "Use the trained model or demo fallback prediction as the signal source"

    def __init__(self, model_manager: ModelManager | None = None, horizon_days: int = 1) -> None:
        self._model_manager = model_manager or ModelManager()
        self.horizon_days = horizon_days

    def generate_signal(self, market_data: StrategyMarketData, portfolio_state: AccountState) -> StrategySignal:
        del portfolio_state
        prediction = market_data.prediction or self._model_manager.predict(market_data.ticker, horizon_days=self.horizon_days)
        if not prediction:
            return hold_signal(self.name, "Model prediction was unavailable.")

        action = str(prediction.get("action", "hold")).lower()
        confidence = float(prediction.get("confidence", 0.0) or 0.0)
        expected_return = float(
            prediction.get("net_expected_return", prediction.get("expected_return", 0.0)) or 0.0
        )
        signal_strength = abs(confidence - 0.5) * 2
        reason = prediction.get("explanation", {}).get("summary") or f"Model recommended {action}."

        return StrategySignal(
            action=action if action in {"buy", "sell", "hold"} else "hold",
            confidence=round(confidence, 4),
            expected_return=round(expected_return, 6),
            signal_strength=round(signal_strength, 4),
            reason=reason,
            strategy=self.name,
            metadata={
                "model_version": prediction.get("model_version"),
                "fallback": bool(prediction.get("fallback")),
                "prediction": prediction,
            },
        )


class EnsembleStrategy(BaseStrategy):
    name = "ensemble"
    description = "Blend several strategies into one weighted signal"

    def __init__(self, members: Iterable[BaseStrategy], weights: Iterable[float] | None = None) -> None:
        self.members = list(members)
        raw_weights = list(weights or [])
        if raw_weights and len(raw_weights) == len(self.members):
            total = sum(raw_weights) or 1.0
            self.weights = [weight / total for weight in raw_weights]
        else:
            equal = 1.0 / max(len(self.members), 1)
            self.weights = [equal for _ in self.members]

    def generate_signal(self, market_data: StrategyMarketData, portfolio_state: AccountState) -> StrategySignal:
        if not self.members:
            return hold_signal(self.name, "No member strategies configured.")

        member_signals: list[StrategySignal] = [
            member.generate_signal(market_data, portfolio_state)
            for member in self.members
        ]

        score = 0.0
        confidence = 0.0
        expected_return = 0.0
        components: list[dict[str, Any]] = []
        for signal, weight in zip(member_signals, self.weights):
            direction = 1 if signal.action == "buy" else -1 if signal.action == "sell" else 0
            weighted_score = direction * signal.confidence * weight
            score += weighted_score
            confidence += signal.confidence * weight
            expected_return += signal.expected_return * weight
            components.append(
                {
                    "strategy": signal.strategy or "unknown",
                    "action": signal.action,
                    "confidence": signal.confidence,
                    "expected_return": signal.expected_return,
                    "weight": round(weight, 4),
                }
            )

        if score > 0.12:
            action = "buy"
        elif score < -0.12:
            action = "sell"
        else:
            action = "hold"

        return StrategySignal(
            action=action,
            confidence=round(min(max(abs(score) + confidence * 0.35, 0.0), 0.95), 4),
            expected_return=round(expected_return, 6),
            signal_strength=round(abs(score), 4),
            reason=f"Ensemble score {score:.3f} from {len(self.members)} strategies.",
            strategy=self.name,
            metadata={"components": components, "raw_score": round(score, 6)},
        )
