"""Regression tests for trainer preprocessing."""

import numpy as np
import pandas as pd

from backend.prediction_engine.training.trainer import (
    _normalize_features_per_ticker,
    _prepare_training_frame,
)


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


def test_prepare_training_frame_drops_infinite_feature_rows():
    rows = 100
    dates = pd.date_range("2024-01-01", periods=rows, freq="D")
    base = np.linspace(100.0, 150.0, rows)

    frame = pd.DataFrame(
        {
            "ticker": ["SAMPLE"] * rows,
            "date": dates,
            "close": base,
            "volatility_20": np.linspace(0.1, 0.2, rows),
        }
    )

    feature_columns = [
        "rsi_14", "macd", "macd_signal", "macd_hist", "volatility_20",
        "return_1d", "return_5d", "log_return_1d", "volume_spike", "volume_ratio",
        "adx_14", "bb_width", "bb_pct_b", "stoch_k", "distance_sma50", "momentum_10", "gap_pct",
        "vwap_dist", "obv_slope", "williams_r", "cci_20", "roc_10", "ema_crossover", "return_2d",
        "return_3d", "return_10d", "distance_sma200", "price_pos_52w", "stoch_d", "rsi_divergence",
        "force_index", "high_low_ratio", "return_mean_5", "return_mean_10", "return_skew_10",
        "volume_change", "close_to_ma20", "close_to_ma50", "return_lag_1", "return_lag_5", "day_of_week",
        "market_return_1d", "market_return_5d", "market_trend_20", "market_volatility_20",
        "india_vix_close", "india_vix_return_5d", "usd_inr_return_5d", "brent_return_5d",
        "gold_return_5d", "sp500_return_1d", "us10y_change_5d", "macro_stress_score",
        "breadth_up_ratio", "breadth_above_sma50", "market_median_return_1d", "market_dispersion_5d",
        "excess_return_1d", "excess_return_5d", "rolling_beta_20", "rolling_corr_20",
        "india_market_sentiment_7d", "india_market_sentiment_30d", "india_market_headline_count_7d",
        "india_market_headline_count_30d", "india_economy_sentiment_7d", "india_economy_sentiment_30d",
        "india_economy_headline_count_7d", "india_economy_headline_count_30d",
        "central_banks_sentiment_7d", "central_banks_sentiment_30d", "central_banks_headline_count_7d",
        "central_banks_headline_count_30d", "capital_flows_sentiment_7d", "capital_flows_sentiment_30d",
        "capital_flows_headline_count_7d", "capital_flows_headline_count_30d", "geopolitics_sentiment_7d",
        "geopolitics_sentiment_30d", "geopolitics_headline_count_7d", "geopolitics_headline_count_30d",
        "news_domestic_sentiment_30d", "news_global_sentiment_30d", "news_sentiment_momentum_30d",
        "news_attention_30d", "news_geopolitical_risk_30d",
    ]
    for column in feature_columns:
        if column not in frame.columns:
            frame[column] = np.linspace(0.01, 1.0, rows)

    frame.loc[80, "market_dispersion_5d"] = np.inf

    prepared = _prepare_training_frame(frame, horizon=1)

    assert not prepared.empty
    assert np.isfinite(prepared["market_dispersion_5d"]).all()
