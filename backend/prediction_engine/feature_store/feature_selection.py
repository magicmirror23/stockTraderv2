"""Feature selection and importance utilities.

Provides correlation filtering, mutual information scoring,
recursive feature elimination, and SHAP-based importance ranking.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def correlation_filter(df: pd.DataFrame, threshold: float = 0.95) -> list[str]:
    """Remove highly correlated features. Returns list of columns to keep."""
    corr = df.corr().abs()
    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    to_drop = [col for col in upper.columns if any(upper[col] > threshold)]
    keep = [c for c in df.columns if c not in to_drop]
    logger.info("Correlation filter: keeping %d / %d features", len(keep), len(df.columns))
    return keep


def mutual_information_ranking(X: pd.DataFrame, y: pd.Series, top_k: int | None = None) -> pd.Series:
    """Rank features by mutual information with target."""
    from sklearn.feature_selection import mutual_info_classif
    mi = mutual_info_classif(X.fillna(0), y, random_state=42)
    scores = pd.Series(mi, index=X.columns).sort_values(ascending=False)
    if top_k:
        return scores.head(top_k)
    return scores


def recursive_feature_elimination(
    X: pd.DataFrame,
    y: pd.Series,
    n_features: int = 15,
    estimator: Any = None,
) -> list[str]:
    """Select features via RFE. Returns list of selected column names."""
    from sklearn.feature_selection import RFE
    if estimator is None:
        from sklearn.ensemble import GradientBoostingClassifier
        estimator = GradientBoostingClassifier(n_estimators=50, max_depth=3, random_state=42)

    selector = RFE(estimator, n_features_to_select=n_features, step=1)
    selector.fit(X.fillna(0), y)
    selected = X.columns[selector.support_].tolist()
    logger.info("RFE selected %d features: %s", len(selected), selected)
    return selected


def shap_importance(model: Any, X: pd.DataFrame, top_k: int = 10) -> dict[str, float]:
    """Compute SHAP feature importance and return top-k features with mean |SHAP| values."""
    try:
        import shap
    except ImportError:
        logger.warning("shap not installed; returning empty importance dict")
        return {}

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X.fillna(0))

    # Handle multi-class (list of arrays)
    if isinstance(shap_values, list):
        shap_values = np.abs(np.array(shap_values)).mean(axis=0)
    else:
        shap_values = np.abs(shap_values)

    mean_abs = shap_values.mean(axis=0)
    importance = pd.Series(mean_abs, index=X.columns).sort_values(ascending=False)
    return importance.head(top_k).to_dict()


def generate_importance_report(
    model: Any,
    X: pd.DataFrame,
    y: pd.Series,
    output_path: str | None = None,
) -> dict:
    """Generate a comprehensive feature importance report."""
    report = {
        "n_features": len(X.columns),
        "n_samples": len(X),
        "mutual_information": mutual_information_ranking(X, y, top_k=20).to_dict(),
        "shap_importance": shap_importance(model, X, top_k=20),
    }

    if output_path:
        import json
        from pathlib import Path
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("Feature importance report saved to %s", output_path)

    return report
