"""Drift detection for features and label distributions.

Implements KS test and PSI (Population Stability Index) for detecting
data and concept drift, with configurable alerting thresholds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_KS_THRESHOLD = 0.1   # p-value below this → drift detected
DEFAULT_PSI_THRESHOLD = 0.2  # PSI above this → significant drift


@dataclass
class DriftConfig:
    ks_p_value_threshold: float = DEFAULT_KS_THRESHOLD
    psi_threshold: float = DEFAULT_PSI_THRESHOLD
    n_bins: int = 10
    min_samples: int = 30


@dataclass
class DriftResult:
    feature: str
    test_type: str          # "ks" | "psi"
    statistic: float
    p_value: float | None
    drifted: bool
    threshold: float
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Core detection functions
# ---------------------------------------------------------------------------


def ks_test(
    reference: np.ndarray,
    current: np.ndarray,
    threshold: float = DEFAULT_KS_THRESHOLD,
) -> DriftResult:
    """Two-sample KS test between reference and current distributions."""
    stat, p_value = stats.ks_2samp(reference, current)
    return DriftResult(
        feature="",
        test_type="ks",
        statistic=round(float(stat), 6),
        p_value=round(float(p_value), 6),
        drifted=p_value < threshold,
        threshold=threshold,
    )


def psi(
    reference: np.ndarray,
    current: np.ndarray,
    n_bins: int = 10,
    threshold: float = DEFAULT_PSI_THRESHOLD,
) -> DriftResult:
    """Population Stability Index between reference and current."""
    eps = 1e-6
    breakpoints = np.linspace(
        min(reference.min(), current.min()),
        max(reference.max(), current.max()),
        n_bins + 1,
    )
    ref_counts = np.histogram(reference, bins=breakpoints)[0].astype(float)
    cur_counts = np.histogram(current, bins=breakpoints)[0].astype(float)

    ref_pct = ref_counts / ref_counts.sum() + eps
    cur_pct = cur_counts / cur_counts.sum() + eps

    psi_value = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))

    return DriftResult(
        feature="",
        test_type="psi",
        statistic=round(psi_value, 6),
        p_value=None,
        drifted=psi_value > threshold,
        threshold=threshold,
    )


# ---------------------------------------------------------------------------
# Multi-feature drift scan
# ---------------------------------------------------------------------------


def detect_feature_drift(
    reference_df,
    current_df,
    config: DriftConfig | None = None,
) -> list[DriftResult]:
    """Run KS and PSI tests on each numeric column.

    Parameters
    ----------
    reference_df : pd.DataFrame
        Historical / training feature set.
    current_df : pd.DataFrame
        Recent / production feature set.
    config : DriftConfig, optional

    Returns
    -------
    list[DriftResult]
        One entry per feature per test type.
    """
    cfg = config or DriftConfig()
    results: list[DriftResult] = []

    common_cols = sorted(
        set(reference_df.select_dtypes(include="number").columns)
        & set(current_df.select_dtypes(include="number").columns)
    )

    for col in common_cols:
        ref = reference_df[col].dropna().values
        cur = current_df[col].dropna().values

        if len(ref) < cfg.min_samples or len(cur) < cfg.min_samples:
            logger.debug("Skipping %s: insufficient samples", col)
            continue

        ks_result = ks_test(ref, cur, threshold=cfg.ks_p_value_threshold)
        ks_result.feature = col
        results.append(ks_result)

        psi_result = psi(ref, cur, n_bins=cfg.n_bins, threshold=cfg.psi_threshold)
        psi_result.feature = col
        results.append(psi_result)

    return results


def detect_label_drift(
    reference_labels: np.ndarray,
    current_labels: np.ndarray,
    config: DriftConfig | None = None,
) -> DriftResult:
    """Detect drift in label / prediction distribution."""
    cfg = config or DriftConfig()
    result = ks_test(reference_labels, current_labels, threshold=cfg.ks_p_value_threshold)
    result.feature = "label_distribution"
    return result


# ---------------------------------------------------------------------------
# Alert helpers
# ---------------------------------------------------------------------------


def summarize_drift(results: list[DriftResult]) -> dict:
    """Produce a summary dict suitable for logging / alerting."""
    drifted = [r for r in results if r.drifted]
    return {
        "total_checked": len(results),
        "total_drifted": len(drifted),
        "drifted_features": [r.feature for r in drifted],
        "details": [
            {
                "feature": r.feature,
                "test": r.test_type,
                "statistic": r.statistic,
                "p_value": r.p_value,
                "threshold": r.threshold,
            }
            for r in drifted
        ],
    }
