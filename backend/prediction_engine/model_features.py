"""Shared feature contract for training and inference."""

from __future__ import annotations

MODEL_INPUT_COLUMNS: list[str] = [
    # Normalised price relationships (no raw prices - they don't generalise)
    "rsi_14", "macd", "macd_signal", "macd_hist",
    "volatility_20", "return_1d", "return_5d", "log_return_1d",
    "volume_spike", "volume_ratio",
    # Trend & mean-reversion
    "adx_14", "bb_width", "bb_pct_b", "stoch_k",
    "distance_sma50", "momentum_10", "gap_pct",
    # Additional features for improved accuracy
    "vwap_dist", "obv_slope", "williams_r", "cci_20",
    "roc_10", "ema_crossover", "return_2d", "return_3d",
    "return_10d", "distance_sma200", "price_pos_52w",
    "stoch_d", "rsi_divergence",
    # Demo-strategy features
    "force_index",
    "return_lag_1", "return_lag_5",
    # Market, macro, and regime context
    "market_return_1d", "market_return_5d", "market_trend_20", "market_volatility_20",
    "india_vix_close", "india_vix_return_5d", "usd_inr_return_5d",
    "brent_return_5d", "gold_return_5d", "sp500_return_1d", "us10y_change_5d",
    "macro_stress_score", "breadth_up_ratio", "breadth_above_sma50",
    "market_median_return_1d", "market_dispersion_5d",
    "excess_return_1d", "excess_return_5d", "rolling_beta_20", "rolling_corr_20",
    # News and event context
    "india_market_sentiment_7d", "india_market_sentiment_30d",
    "india_market_headline_count_7d", "india_market_headline_count_30d",
    "india_economy_sentiment_7d", "india_economy_sentiment_30d",
    "india_economy_headline_count_7d", "india_economy_headline_count_30d",
    "central_banks_sentiment_7d", "central_banks_sentiment_30d",
    "central_banks_headline_count_7d", "central_banks_headline_count_30d",
    "capital_flows_sentiment_7d", "capital_flows_sentiment_30d",
    "capital_flows_headline_count_7d", "capital_flows_headline_count_30d",
    "geopolitics_sentiment_7d", "geopolitics_sentiment_30d",
    "geopolitics_headline_count_7d", "geopolitics_headline_count_30d",
    "news_domestic_sentiment_30d",
    "news_global_sentiment_30d",
    "news_sentiment_momentum_30d",
    "news_attention_30d",
    "news_geopolitical_risk_30d",
    # Company-specific news and event context
    "company_sentiment_7d",
    "company_sentiment_30d",
    "company_headline_count_7d",
    "company_headline_count_30d",
    "company_event_score_7d",
    "company_event_score_30d",
    "company_news_attention_shock",
    "company_event_intensity",
]
