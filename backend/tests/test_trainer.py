"""Regression tests for trainer preprocessing."""

import numpy as np
import pandas as pd

from backend.prediction_engine.training.trainer import _normalize_features_per_ticker


def test_normalize_features_keeps_constant_windows_neutral():
    rows = 80
    frame = pd.DataFrame(
        {
            "ticker": ["SAMPLE"] * rows,
            "flat_news_count": [0.0] * rows,
            "varying_feature": np.linspace(1.0, 10.0, rows),
        }
    )

    normalized = _normalize_features_per_ticker(frame, ["flat_news_count", "varying_feature"])

    # Warm-up rows can remain NaN, but once the rolling window is active the
    # constant news feature should be neutral (0.0) rather than invalid.
    assert normalized["flat_news_count"].iloc[59] == 0.0
    assert normalized["flat_news_count"].iloc[79] == 0.0
    assert normalized["flat_news_count"].iloc[19:80].notna().all()
    assert normalized["varying_feature"].iloc[59:80].notna().all()
