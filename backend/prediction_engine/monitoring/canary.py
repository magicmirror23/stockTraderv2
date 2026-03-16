"""Canary deployment flow for model promotion.

Implements shadow inference, A/B evaluation, and promotion rules
to safely roll out new model versions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class CanaryStage(str, Enum):
    SHADOW = "shadow"           # New model runs in shadow; not serving
    CANARY = "canary"           # Small traffic split to new model
    PROMOTED = "promoted"       # New model fully promoted
    ROLLED_BACK = "rolled_back" # New model failed; rolled back


@dataclass
class CanaryConfig:
    """Configuration for canary promotion rules."""
    shadow_min_predictions: int = 200
    canary_traffic_pct: float = 0.10
    max_accuracy_drop: float = 0.02       # tolerate at most 2 pp drop
    max_latency_increase_pct: float = 0.30  # tolerate at most 30 % latency rise
    min_economic_ratio: float = 0.90      # new model P&L >= 90 % of champion
    auto_promote_after: int = 1000        # auto-promote after N canary predictions


@dataclass
class ModelMetrics:
    """Collected metrics for a model version during evaluation."""
    version: str
    predictions: int = 0
    correct: int = 0
    total_pnl: float = 0.0
    total_latency_ms: float = 0.0
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def accuracy(self) -> float:
        return self.correct / max(self.predictions, 1)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / max(self.predictions, 1)


# ---------------------------------------------------------------------------
# Canary evaluator
# ---------------------------------------------------------------------------


class CanaryEvaluator:
    """Manages shadow / canary evaluation for a candidate model.

    Workflow
    --------
    1. Register a candidate model version → starts in SHADOW stage.
    2. For each prediction request, call ``shadow_predict()`` to record
       the candidate's output alongside the champion.
    3. After ``shadow_min_predictions``, call ``evaluate_shadow()`` to
       decide whether to promote to CANARY.
    4. In CANARY, call ``record_canary_result()`` for the traffic split.
    5. After ``auto_promote_after`` canary predictions, call
       ``evaluate_canary()`` to promote or roll back.
    """

    def __init__(
        self,
        champion_version: str,
        candidate_version: str,
        config: CanaryConfig | None = None,
    ) -> None:
        self.config = config or CanaryConfig()
        self.champion = ModelMetrics(version=champion_version)
        self.candidate = ModelMetrics(version=candidate_version)
        self.stage: CanaryStage = CanaryStage.SHADOW
        self._decisions: list[dict] = []

    # ------------------------------------------------------------------ #
    # Shadow phase                                                        #
    # ------------------------------------------------------------------ #

    def record_shadow(
        self,
        champion_correct: bool,
        candidate_correct: bool,
        champion_latency_ms: float,
        candidate_latency_ms: float,
        champion_pnl: float = 0.0,
        candidate_pnl: float = 0.0,
    ) -> None:
        """Record a shadow inference pair."""
        self.champion.predictions += 1
        self.champion.correct += int(champion_correct)
        self.champion.total_latency_ms += champion_latency_ms
        self.champion.total_pnl += champion_pnl

        self.candidate.predictions += 1
        self.candidate.correct += int(candidate_correct)
        self.candidate.total_latency_ms += candidate_latency_ms
        self.candidate.total_pnl += candidate_pnl

    def evaluate_shadow(self) -> CanaryStage:
        """Decide whether to promote from SHADOW → CANARY."""
        if self.candidate.predictions < self.config.shadow_min_predictions:
            logger.info(
                "Shadow: %d/%d predictions collected",
                self.candidate.predictions, self.config.shadow_min_predictions,
            )
            return self.stage

        acc_diff = self.champion.accuracy - self.candidate.accuracy
        latency_ratio = (
            self.candidate.avg_latency_ms / max(self.champion.avg_latency_ms, 0.01)
        )

        decision = {
            "phase": "shadow",
            "champion_acc": round(self.champion.accuracy, 4),
            "candidate_acc": round(self.candidate.accuracy, 4),
            "acc_diff": round(acc_diff, 4),
            "latency_ratio": round(latency_ratio, 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if acc_diff > self.config.max_accuracy_drop:
            self.stage = CanaryStage.ROLLED_BACK
            decision["result"] = "rolled_back"
            logger.warning("Shadow FAILED: accuracy drop %.4f > %.4f", acc_diff, self.config.max_accuracy_drop)
        elif latency_ratio > 1 + self.config.max_latency_increase_pct:
            self.stage = CanaryStage.ROLLED_BACK
            decision["result"] = "rolled_back"
            logger.warning("Shadow FAILED: latency ratio %.2f exceeds limit", latency_ratio)
        else:
            self.stage = CanaryStage.CANARY
            decision["result"] = "promoted_to_canary"
            logger.info("Shadow PASSED → promoting to CANARY")

        self._decisions.append(decision)
        return self.stage

    # ------------------------------------------------------------------ #
    # Canary phase                                                        #
    # ------------------------------------------------------------------ #

    def should_use_candidate(self) -> bool:
        """Return True if the current request should be routed to the candidate."""
        if self.stage != CanaryStage.CANARY:
            return False
        return np.random.random() < self.config.canary_traffic_pct

    def record_canary_result(
        self,
        is_candidate: bool,
        correct: bool,
        latency_ms: float,
        pnl: float = 0.0,
    ) -> None:
        """Record a canary-phase prediction result."""
        target = self.candidate if is_candidate else self.champion
        target.predictions += 1
        target.correct += int(correct)
        target.total_latency_ms += latency_ms
        target.total_pnl += pnl

    def evaluate_canary(self) -> CanaryStage:
        """Decide whether to PROMOTE or ROLL BACK from canary."""
        if self.candidate.predictions < self.config.auto_promote_after:
            return self.stage

        acc_diff = self.champion.accuracy - self.candidate.accuracy
        latency_ratio = (
            self.candidate.avg_latency_ms / max(self.champion.avg_latency_ms, 0.01)
        )
        pnl_ratio = (
            self.candidate.total_pnl / max(abs(self.champion.total_pnl), 0.01)
        )

        decision = {
            "phase": "canary",
            "champion_acc": round(self.champion.accuracy, 4),
            "candidate_acc": round(self.candidate.accuracy, 4),
            "pnl_ratio": round(pnl_ratio, 4),
            "latency_ratio": round(latency_ratio, 4),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if acc_diff > self.config.max_accuracy_drop:
            self.stage = CanaryStage.ROLLED_BACK
            decision["result"] = "rolled_back"
            logger.warning("Canary FAILED: accuracy drop %.4f", acc_diff)
        elif latency_ratio > 1 + self.config.max_latency_increase_pct:
            self.stage = CanaryStage.ROLLED_BACK
            decision["result"] = "rolled_back"
            logger.warning("Canary FAILED: latency too high")
        elif pnl_ratio < self.config.min_economic_ratio:
            self.stage = CanaryStage.ROLLED_BACK
            decision["result"] = "rolled_back"
            logger.warning("Canary FAILED: P&L ratio %.4f < %.2f", pnl_ratio, self.config.min_economic_ratio)
        else:
            self.stage = CanaryStage.PROMOTED
            decision["result"] = "promoted"
            logger.info("Canary PASSED → PROMOTED candidate %s", self.candidate.version)

        self._decisions.append(decision)
        return self.stage

    # ------------------------------------------------------------------ #
    # Reporting                                                           #
    # ------------------------------------------------------------------ #

    def get_report(self) -> dict:
        """Return a summary of the canary evaluation."""
        return {
            "stage": self.stage.value,
            "champion": {
                "version": self.champion.version,
                "predictions": self.champion.predictions,
                "accuracy": round(self.champion.accuracy, 4),
                "avg_latency_ms": round(self.champion.avg_latency_ms, 2),
                "total_pnl": round(self.champion.total_pnl, 2),
            },
            "candidate": {
                "version": self.candidate.version,
                "predictions": self.candidate.predictions,
                "accuracy": round(self.candidate.accuracy, 4),
                "avg_latency_ms": round(self.candidate.avg_latency_ms, 2),
                "total_pnl": round(self.candidate.total_pnl, 2),
            },
            "decisions": self._decisions,
        }
