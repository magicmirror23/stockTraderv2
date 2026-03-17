"""Shared normalization helpers for model training and live inference."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.prediction_engine.data_pipeline.connector_news import (
    company_feature_columns,
    topic_feature_columns,
)

NEWS_AGGREGATE_FEATURE_COLUMNS = [
    "news_domestic_sentiment_30d",
    "news_global_sentiment_30d",
    "news_sentiment_momentum_30d",
    "news_attention_30d",
    "news_geopolitical_risk_30d",
]

BOUNDED_FEATURES = {
    "rsi_14", "bb_pct_b", "stoch_k", "stoch_d", "williams_r",
    "price_pos_52w", "volume_spike", "rsi_divergence",
    "high_low_ratio", "close_to_ma20", "close_to_ma50", "day_of_week",
    "breadth_up_ratio", "breadth_above_sma50", "news_geopolitical_risk_30d",
    *{col for col in [*topic_feature_columns(), *NEWS_AGGREGATE_FEATURE_COLUMNS] if "sentiment" in col},
    *{col for col in company_feature_columns() if "sentiment" in col or "event_score" in col},
}


def rolling_zscore_or_zero(series: pd.Series, window: int = 60, min_periods: int = 20) -> pd.Series:
    """Rolling z-score that keeps flat windows neutral instead of invalid."""
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std()
    normalized = (series - mean) / std.replace(0, np.nan)

    warmup_mask = mean.isna() | std.isna()
    flat_mask = (~warmup_mask) & std.le(0)
    normalized = normalized.mask(flat_mask, 0.0)
    return normalized


def normalize_features_per_ticker(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """Z-score unbounded features per ticker while keeping bounded features intact."""
    df = df.copy()
    for col in feature_cols:
        if col in df.columns and col not in BOUNDED_FEATURES:
            df[col] = df.groupby("ticker")[col].transform(rolling_zscore_or_zero)
    return df
