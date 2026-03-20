"""Base abstractions for pluggable trading strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from backend.trading_engine.account_state import AccountState


SignalAction = Literal["buy", "sell", "hold"]


@dataclass(slots=True)
class StrategyMarketData:
    """Normalized strategy input bundle for a single symbol."""

    ticker: str
    spot_price: float
    history: pd.DataFrame | None = None
    features: dict[str, Any] = field(default_factory=dict)
    prediction: dict[str, Any] | None = None
    timestamp: str | None = None


@dataclass(slots=True)
class StrategySignal:
    """Normalized strategy output shared by all bots."""

    action: SignalAction
    confidence: float
    expected_return: float = 0.0
    signal_strength: float = 0.0
    reason: str = ""
    strategy: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def hold_signal(strategy: str, reason: str, metadata: dict[str, Any] | None = None) -> StrategySignal:
    return StrategySignal(
        action="hold",
        confidence=0.0,
        expected_return=0.0,
        signal_strength=0.0,
        reason=reason,
        strategy=strategy,
        metadata=metadata or {},
    )


class BaseStrategy(ABC):
    """Common interface for all trading strategies."""

    name = "base"
    description = "Base strategy"

    @abstractmethod
    def generate_signal(
        self,
        market_data: StrategyMarketData,
        portfolio_state: AccountState,
    ) -> StrategySignal:
        """Return a normalized signal for the provided market + portfolio state."""

