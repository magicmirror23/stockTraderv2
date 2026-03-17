"""Versioned Feature Store.

Builds a feature matrix from raw OHLCV data using the transforms defined in
``transforms.py``.  Supports both bulk build (for training) and single-row
inference lookups.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from backend.core.config import settings
from backend.prediction_engine.data_pipeline.connector_news import topic_feature_columns, topic_queries
from backend.prediction_engine.feature_store.normalization import normalize_features_per_ticker
from backend.prediction_engine.model_features import MODEL_INPUT_COLUMNS
from backend.prediction_engine.feature_store import transforms as T

logger = logging.getLogger(__name__)

MANIFEST_PATH = Path(__file__).parent / "manifest.json"
NEWS_FEATURE_COLUMNS: list[str] = topic_feature_columns()
NEWS_AGGREGATE_FEATURE_COLUMNS: list[str] = [
    "news_domestic_sentiment_30d",
    "news_global_sentiment_30d",
    "news_sentiment_momentum_30d",
    "news_attention_30d",
    "news_geopolitical_risk_30d",
]
ALL_NEWS_FEATURE_COLUMNS: list[str] = NEWS_FEATURE_COLUMNS + NEWS_AGGREGATE_FEATURE_COLUMNS

# Ordered list of feature columns produced by build_features.
FEATURE_COLUMNS: list[str] = [
    "ticker",
    "date",
    "close",
    "sma_10",
    "sma_20",
    "sma_50",
    "ema_10",
    "ema_20",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "atr_14",
    "volatility_20",
    "return_1d",
    "return_5d",
    "log_return_1d",
    "volume_spike",
    "volume_ratio",
    # Trend & mean-reversion
    "adx_14",
    "bb_width",
    "bb_pct_b",
    "stoch_k",
    "distance_sma50",
    "momentum_10",
    "gap_pct",
    # Additional features for 55-60% accuracy
    "vwap_dist",
    "obv_slope",
    "williams_r",
    "cci_20",
    "roc_10",
    "ema_crossover",
    "return_2d",
    "return_3d",
    "return_10d",
    "distance_sma200",
    "price_pos_52w",
    "stoch_d",
    "rsi_divergence",
    # Demo-strategy features
    "force_index",
    "high_low_ratio",
    "return_mean_5",
    "return_mean_10",
    "return_skew_10",
    "volume_change",
    "close_to_ma20",
    "close_to_ma50",
    "return_lag_1",
    "return_lag_5",
    "day_of_week",
    # Market, macro, and regime context
    "market_return_1d",
    "market_return_5d",
    "market_trend_20",
    "market_volatility_20",
    "india_vix_close",
    "india_vix_return_5d",
    "usd_inr_return_5d",
    "brent_return_5d",
    "gold_return_5d",
    "sp500_return_1d",
    "us10y_change_5d",
    "macro_stress_score",
    "breadth_up_ratio",
    "breadth_above_sma50",
    "market_median_return_1d",
    "market_dispersion_5d",
    "excess_return_1d",
    "excess_return_5d",
    "rolling_beta_20",
    "rolling_corr_20",
    # News and event context
    *topic_feature_columns(),
    *NEWS_AGGREGATE_FEATURE_COLUMNS,
]

CONTEXT_FEATURE_COLUMNS: list[str] = [
    "market_return_1d",
    "market_return_5d",
    "market_trend_20",
    "market_volatility_20",
    "india_vix_close",
    "india_vix_return_5d",
    "usd_inr_return_5d",
    "brent_return_5d",
    "gold_return_5d",
    "sp500_return_1d",
    "us10y_change_5d",
]

BREADTH_FEATURE_COLUMNS: list[str] = [
    "breadth_up_ratio",
    "breadth_above_sma50",
    "market_median_return_1d",
    "market_dispersion_5d",
]

RELATIVE_FEATURE_COLUMNS: list[str] = [
    "macro_stress_score",
    "excess_return_1d",
    "excess_return_5d",
    "rolling_beta_20",
    "rolling_corr_20",
]


def _derive_news_aggregate_features(news: pd.DataFrame) -> pd.DataFrame:
    domestic_sentiment = [
        "india_market_sentiment_30d",
        "india_economy_sentiment_30d",
        "capital_flows_sentiment_30d",
    ]
    global_sentiment = [
        "central_banks_sentiment_30d",
        "geopolitics_sentiment_30d",
    ]
    momentum_columns = [f"{topic}_sentiment_7d" for topic in topic_queries()]
    baseline_columns = [f"{topic}_sentiment_30d" for topic in topic_queries()]
    count_columns = [f"{topic}_headline_count_30d" for topic in topic_queries()]

    news["news_domestic_sentiment_30d"] = news[domestic_sentiment].mean(axis=1)
    news["news_global_sentiment_30d"] = news[global_sentiment].mean(axis=1)
    news["news_sentiment_momentum_30d"] = (
        news[momentum_columns].mean(axis=1) - news[baseline_columns].mean(axis=1)
    )
    news["news_attention_30d"] = news[count_columns].sum(axis=1)
    news["news_geopolitical_risk_30d"] = (
        (-news["geopolitics_sentiment_30d"]).clip(lower=0.0)
        + (-news["central_banks_sentiment_30d"]).clip(lower=0.0)
    ) / 2.0
    news[NEWS_AGGREGATE_FEATURE_COLUMNS] = news[NEWS_AGGREGATE_FEATURE_COLUMNS].replace(
        [np.inf, -np.inf],
        np.nan,
    ).fillna(0.0)
    return news


def _load_ticker_csv(ticker: str, data_dir: Path) -> pd.DataFrame:
    path = data_dir / f"{ticker}.csv"
    if not path.exists():
        raise FileNotFoundError(f"No data file for {ticker} at {path}")
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    return df


def _compute_features(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Compute all feature columns for a single-ticker DataFrame."""
    close = df["Close"]
    feat = pd.DataFrame()

    feat["date"] = df["Date"].values
    feat["close"] = close.values
    feat["ticker"] = ticker

    # Moving averages
    feat["sma_10"] = T.sma(close, 10).values
    feat["sma_20"] = T.sma(close, 20).values
    feat["sma_50"] = T.sma(close, 50).values
    feat["ema_10"] = T.ema(close, 10).values
    feat["ema_20"] = T.ema(close, 20).values

    # Momentum
    feat["rsi_14"] = T.rsi(close, 14).values
    macd_df = T.macd(close)
    feat["macd"] = macd_df["macd"].values
    feat["macd_signal"] = macd_df["macd_signal"].values
    feat["macd_hist"] = macd_df["macd_hist"].values

    # Volatility
    feat["atr_14"] = T.atr(df, 14).values
    feat["volatility_20"] = T.volatility(close, 20).values

    # Returns
    feat["return_1d"] = T.returns(close, 1).values
    feat["return_5d"] = T.returns(close, 5).values
    feat["log_return_1d"] = T.log_returns(close, 1).values

    # Volume
    feat["volume_spike"] = T.volume_spike(df["Volume"]).values
    feat["volume_ratio"] = T.volume_ratio(df["Volume"]).values

    # Trend strength & mean-reversion (new features)
    feat["adx_14"] = T.adx(df, 14).values
    feat["bb_width"] = T.bollinger_band_width(close, 20).values
    feat["bb_pct_b"] = T.bollinger_pct_b(close, 20).values
    feat["stoch_k"] = T.stochastic_k(df, 14).values
    feat["distance_sma50"] = T.price_distance_from_sma(close, 50).values
    feat["momentum_10"] = T.return_momentum(close, 10).values
    if "Open" in df.columns:
        feat["gap_pct"] = T.gap_pct(df).values
    else:
        feat["gap_pct"] = 0.0

    # Additional features for improved accuracy
    feat["vwap_dist"] = T.vwap_distance(df, 20).values
    feat["obv_slope"] = T.obv_slope(df, 10).values
    feat["williams_r"] = T.williams_r(df, 14).values
    feat["cci_20"] = T.cci(df, 20).values
    feat["roc_10"] = T.roc(close, 10).values
    feat["ema_crossover"] = T.ema_crossover(close, 10, 20).values
    feat["return_2d"] = T.lagged_return(close, 2).values
    feat["return_3d"] = T.lagged_return(close, 3).values
    feat["return_10d"] = T.lagged_return(close, 10).values
    sma200 = T.sma_long(close, 200)
    feat["distance_sma200"] = ((close - sma200) / sma200.replace(0, np.nan)).values
    feat["price_pos_52w"] = T.price_position_52w(df, 252).values
    feat["stoch_d"] = T.stochastic_d(df, 14, 3).values
    feat["rsi_divergence"] = T.rsi_divergence(close, 14, 10).values

    # Demo-strategy features
    feat["force_index"] = T.force_index(df, 13).values
    feat["high_low_ratio"] = T.high_low_ratio(df).values
    feat["return_mean_5"] = T.return_mean(close, 5).values
    feat["return_mean_10"] = T.return_mean(close, 10).values
    feat["return_skew_10"] = T.return_skew(close, 10).values
    feat["volume_change"] = T.volume_change(df["Volume"]).values
    feat["close_to_ma20"] = T.close_to_sma(close, 20).values
    feat["close_to_ma50"] = T.close_to_sma(close, 50).values
    feat["return_lag_1"] = T.lagged_return_shift(close, 1).values
    feat["return_lag_5"] = T.lagged_return_shift(close, 5).values
    feat["day_of_week"] = T.day_of_week(df).values

    return feat


def _load_context_features(context_dir: Path) -> pd.DataFrame:
    """Build market and macro context features from external Yahoo datasets."""
    if not settings.ENABLE_MARKET_CONTEXT_FEATURES:
        return pd.DataFrame(columns=["date"] + CONTEXT_FEATURE_COLUMNS)

    frames: list[pd.DataFrame] = []
    for symbol in settings.market_context_symbols:
        path = context_dir / f"{symbol}.csv"
        if not path.exists():
            logger.warning("Missing market context CSV for %s in %s", symbol, context_dir)
            continue

        df = pd.read_csv(path, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
        if df.empty:
            logger.warning("Market context CSV for %s is empty", symbol)
            continue

        close = df["Close"]
        frame = pd.DataFrame({"date": df["Date"].values})

        if symbol == "NIFTY50":
            frame["market_return_1d"] = T.returns(close, 1).values
            frame["market_return_5d"] = T.returns(close, 5).values
            frame["market_trend_20"] = T.price_distance_from_sma(close, 20).values
            frame["market_volatility_20"] = T.volatility(close, 20).values
        elif symbol == "INDIAVIX":
            frame["india_vix_close"] = close.values
            frame["india_vix_return_5d"] = T.returns(close, 5).values
        elif symbol == "USDINR":
            frame["usd_inr_return_5d"] = T.returns(close, 5).values
        elif symbol == "BRENT":
            frame["brent_return_5d"] = T.returns(close, 5).values
        elif symbol == "GOLD":
            frame["gold_return_5d"] = T.returns(close, 5).values
        elif symbol == "SP500":
            frame["sp500_return_1d"] = T.returns(close, 1).values
        elif symbol == "US10Y":
            frame["us10y_change_5d"] = close.diff(5).values
        else:
            continue

        frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=["date"] + CONTEXT_FEATURE_COLUMNS)

    context = frames[0]
    for frame in frames[1:]:
        context = context.merge(frame, on="date", how="outer")

    context = context.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    for column in CONTEXT_FEATURE_COLUMNS:
        if column not in context.columns:
            context[column] = np.nan
    return context[["date"] + CONTEXT_FEATURE_COLUMNS]


def _merge_context_features(features: pd.DataFrame, context_dir: Path) -> pd.DataFrame:
    context = _load_context_features(context_dir)
    if context.empty:
        for column in CONTEXT_FEATURE_COLUMNS:
            if column not in features.columns:
                features[column] = 0.0
        return features

    merged = pd.merge_asof(
        features.sort_values("date"),
        context.sort_values("date"),
        on="date",
        direction="backward",
    )
    merged = merged.sort_values(["ticker", "date"]).reset_index(drop=True)
    merged[CONTEXT_FEATURE_COLUMNS] = merged[CONTEXT_FEATURE_COLUMNS].fillna(0.0)
    return merged


def _load_news_features(
    news_dir: Path,
    news_mode: Literal["training", "inference"] = "training",
) -> pd.DataFrame:
    """Load topic-level rolling news sentiment features."""
    if not settings.ENABLE_NEWS_FEATURES:
        return pd.DataFrame(columns=["date"] + ALL_NEWS_FEATURE_COLUMNS)

    frames: list[pd.DataFrame] = []
    for topic in topic_queries():
        path = news_dir / f"{topic}.csv"
        if not path.exists():
            logger.warning("Missing news topic CSV for %s in %s", topic, news_dir)
            continue

        frame = pd.read_csv(path, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
        if frame.empty:
            continue

        renamed = frame.rename(
            columns={
                "sentiment_7d": f"{topic}_sentiment_7d",
                "sentiment_30d": f"{topic}_sentiment_30d",
                "headline_count_7d": f"{topic}_headline_count_7d",
                "headline_count_30d": f"{topic}_headline_count_30d",
            }
        )
        keep_columns = [
            "date",
            f"{topic}_sentiment_7d",
            f"{topic}_sentiment_30d",
            f"{topic}_headline_count_7d",
            f"{topic}_headline_count_30d",
        ]
        frames.append(renamed[keep_columns])

    if not frames:
        return pd.DataFrame(columns=["date"] + ALL_NEWS_FEATURE_COLUMNS)

    news = frames[0]
    for frame in frames[1:]:
        news = news.merge(frame, on="date", how="outer")
    news = news.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    for column in NEWS_FEATURE_COLUMNS:
        if column not in news.columns:
            news[column] = 0.0
    news[NEWS_FEATURE_COLUMNS] = news[NEWS_FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan).ffill()
    if news_mode == "training":
        news[NEWS_FEATURE_COLUMNS] = news[NEWS_FEATURE_COLUMNS].shift(1)
    news[NEWS_FEATURE_COLUMNS] = news[NEWS_FEATURE_COLUMNS].fillna(0.0)
    news = _derive_news_aggregate_features(news)
    return news[["date"] + ALL_NEWS_FEATURE_COLUMNS]


def _merge_news_features(
    features: pd.DataFrame,
    news_dir: Path,
    news_mode: Literal["training", "inference"] = "training",
) -> pd.DataFrame:
    news = _load_news_features(news_dir, news_mode=news_mode)
    if news.empty:
        for column in ALL_NEWS_FEATURE_COLUMNS:
            if column not in features.columns:
                features[column] = 0.0
        return features

    merged = pd.merge_asof(
        features.sort_values("date"),
        news.sort_values("date"),
        on="date",
        direction="backward",
    )
    merged = merged.sort_values(["ticker", "date"]).reset_index(drop=True)
    merged[ALL_NEWS_FEATURE_COLUMNS] = merged[ALL_NEWS_FEATURE_COLUMNS].fillna(0.0)
    return merged


def _latest_news_snapshot(news_dir: Path) -> dict[str, float]:
    news = _load_news_features(news_dir, news_mode="inference")
    if news.empty:
        return {column: 0.0 for column in ALL_NEWS_FEATURE_COLUMNS}
    row = news.iloc[-1]
    return {
        column: float(row[column]) if pd.notna(row[column]) else 0.0
        for column in ALL_NEWS_FEATURE_COLUMNS
    }


def _add_breadth_and_relative_features(features: pd.DataFrame) -> pd.DataFrame:
    features = features.sort_values(["ticker", "date"]).reset_index(drop=True)

    features["breadth_up_ratio"] = features.groupby("date")["return_1d"].transform(
        lambda values: float((values > 0).mean())
    )
    features["breadth_above_sma50"] = features.groupby("date")["distance_sma50"].transform(
        lambda values: float((values > 0).mean())
    )
    features["market_median_return_1d"] = features.groupby("date")["return_1d"].transform("median")
    features["market_dispersion_5d"] = features.groupby("date")["return_5d"].transform("std").fillna(0.0)

    features["excess_return_1d"] = features["return_1d"] - features["market_return_1d"]
    features["excess_return_5d"] = features["return_5d"] - features["market_return_5d"]
    features["macro_stress_score"] = (
        features["india_vix_return_5d"].fillna(0.0) * 2.0
        + features["usd_inr_return_5d"].fillna(0.0) * 1.5
        + features["brent_return_5d"].fillna(0.0)
        + features["gold_return_5d"].fillna(0.0) * 0.5
        - features["market_return_5d"].fillna(0.0) * 1.5
        - features["sp500_return_1d"].fillna(0.0) * 0.5
    )

    beta_values = pd.Series(index=features.index, dtype=float)
    corr_values = pd.Series(index=features.index, dtype=float)
    for _, group in features.groupby("ticker", sort=False):
        market = group["market_return_1d"].fillna(0.0)
        stock = group["return_1d"].fillna(0.0)
        beta_values.loc[group.index] = T.rolling_beta(stock, market, window=20, min_periods=10).values
        corr_values.loc[group.index] = T.rolling_correlation(stock, market, window=20, min_periods=10).values

    features["rolling_beta_20"] = beta_values
    features["rolling_corr_20"] = corr_values

    fill_columns = CONTEXT_FEATURE_COLUMNS + BREADTH_FEATURE_COLUMNS + RELATIVE_FEATURE_COLUMNS
    features[fill_columns] = features[fill_columns].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return features


def build_features(
    tickers: list[str],
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    data_dir: str | Path = "storage/raw",
    context_dir: str | Path | None = None,
    news_dir: str | Path | None = None,
    news_mode: Literal["training", "inference"] = "training",
) -> pd.DataFrame:
    """Build the full feature matrix for a list of tickers.

    Parameters
    ----------
    tickers : list[str]
        Ticker symbols whose CSV files exist in *data_dir*.
    start, end : optional
        Filter resulting rows to this date range.
    data_dir : str or Path
        Directory containing ``{TICKER}.csv`` files.

    Returns
    -------
    pd.DataFrame
        Concatenated features with columns matching ``FEATURE_COLUMNS``.
    """
    data_dir = Path(data_dir)
    resolved_context_dir = Path(context_dir) if context_dir is not None else settings.context_data_path
    resolved_news_dir = Path(news_dir) if news_dir is not None else settings.news_data_path / "topics"
    frames: list[pd.DataFrame] = []

    for ticker in tickers:
        try:
            df = _load_ticker_csv(ticker, data_dir)
        except FileNotFoundError:
            logger.warning("Skipping %s – CSV not found in %s", ticker, data_dir)
            continue
        feat = _compute_features(df, ticker)
        if not feat.empty:
            frames.append(feat)

    if not frames:
        raise FileNotFoundError("No CSV data files found for any ticker")

    result = pd.concat(frames, ignore_index=True)
    result = _merge_context_features(result, resolved_context_dir)
    result = _merge_news_features(result, resolved_news_dir, news_mode=news_mode)
    result = _add_breadth_and_relative_features(result)

    # Date filtering
    if start is not None:
        result = result[result["date"] >= pd.Timestamp(start)]
    if end is not None:
        result = result[result["date"] <= pd.Timestamp(end)]

    # Drop warm-up NaN rows
    result = result.dropna().reset_index(drop=True)

    # Write manifest
    _write_manifest(tickers, result)

    return result[FEATURE_COLUMNS]


def get_features_for_inference(
    ticker: str,
    timestamp: str | datetime | None = None,
    data_dir: str | Path = "storage/raw",
    context_dir: str | Path | None = None,
    news_dir: str | Path | None = None,
) -> dict:
    """Return the latest feature vector for a single ticker.

    Parameters
    ----------
    ticker : str
        Ticker symbol.
    timestamp : optional
        If provided, return the feature row closest to (but not after) this time.
    data_dir : str or Path
        Directory containing ``{TICKER}.csv`` files.

    Returns
    -------
    dict
        Feature dictionary matching the model input schema.
    """
    from backend.services.news_context import get_news_context_manager
    from backend.services.training_data import load_training_tickers

    ticker = ticker.upper()
    try:
        universe = load_training_tickers()
    except Exception:
        universe = [ticker]

    if ticker not in universe:
        universe.append(ticker)

    if settings.ENABLE_NEWS_FEATURES:
        try:
            get_news_context_manager().ensure_recent(force=False)
        except Exception as exc:
            logger.warning("News context refresh skipped during inference: %s", exc)

    resolved_news_dir = Path(news_dir) if news_dir is not None else settings.news_data_path / "topics"
    feat = build_features(
        universe,
        data_dir=data_dir,
        context_dir=context_dir,
        news_dir=resolved_news_dir,
        news_mode="inference",
    )
    feat = feat[feat["ticker"] == ticker].reset_index(drop=True)
    if feat.empty:
        raise ValueError(f"No valid feature rows for {ticker}")

    if timestamp is not None:
        ts = pd.Timestamp(timestamp)
        feat = feat[feat["date"] <= ts]
        if feat.empty:
            raise ValueError(f"No feature rows for {ticker} on or before {timestamp}")

    latest_news = _latest_news_snapshot(resolved_news_dir)
    latest_index = feat.index[-1]
    for column, value in latest_news.items():
        feat.loc[latest_index, column] = value

    # Keep inference numerically aligned with training by reusing the same
    # per-ticker normalization contract before selecting the latest row.
    feat = normalize_features_per_ticker(feat, MODEL_INPUT_COLUMNS)
    feat = feat.dropna(subset=MODEL_INPUT_COLUMNS).reset_index(drop=True)
    if feat.empty:
        raise ValueError(f"No normalized feature rows for {ticker}")

    row = feat.iloc[-1].copy()
    return {col: row[col] for col in FEATURE_COLUMNS}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def _write_manifest(tickers: list[str], df: pd.DataFrame) -> None:
    manifest = {
        "version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tickers": tickers,
        "feature_columns": FEATURE_COLUMNS,
        "row_count": len(df),
        "date_range": {
            "start": str(df["date"].min()),
            "end": str(df["date"].max()),
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    logger.info("Feature manifest written → %s", MANIFEST_PATH)


# ---------------------------------------------------------------------------
# Option features
# ---------------------------------------------------------------------------

OPTION_FEATURE_COLUMNS: list[str] = [
    "underlying", "strike", "expiry", "option_type", "date",
    "underlying_close", "iv", "iv_rank", "oi_change",
    "delta", "gamma", "theta", "vega",
    "moneyness", "days_to_expiry",
    "underlying_rsi_14", "underlying_atr_14", "underlying_volatility_20",
]


def build_option_features(
    underlying: str,
    strike: float,
    expiry: str,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    data_dir: str | Path = "storage/raw",
) -> pd.DataFrame:
    """Build option-specific feature matrix.

    Combines underlying equity features with option greeks and IV data.
    """
    data_dir = Path(data_dir)

    # Load underlying equity data
    df = _load_ticker_csv(underlying, data_dir)
    equity_feat = _compute_features(df, underlying).dropna().reset_index(drop=True)

    # Build option-specific columns
    opt = pd.DataFrame()
    opt["underlying"] = underlying
    opt["strike"] = strike
    opt["expiry"] = expiry
    opt["option_type"] = "CE"  # default; caller should specify
    opt["date"] = equity_feat["date"]
    opt["underlying_close"] = equity_feat["close"].values

    # Moneyness
    opt["moneyness"] = equity_feat["close"].values / strike

    # Days to expiry
    expiry_dt = pd.Timestamp(expiry)
    opt["days_to_expiry"] = (expiry_dt - equity_feat["date"]).dt.days

    # Underlying indicators
    opt["underlying_rsi_14"] = equity_feat["rsi_14"].values
    opt["underlying_atr_14"] = equity_feat["atr_14"].values
    opt["underlying_volatility_20"] = equity_feat["volatility_20"].values

    # Placeholder greeks (computed from underlying volatility as approximation)
    for _, row in opt.iterrows():
        dte = max(row["days_to_expiry"], 1)
        vol = row.get("underlying_volatility_20", 0.3) or 0.3
        greeks = T.greeks_estimate(
            row["underlying_close"], strike, dte, vol
        )
        opt.loc[_, "delta"] = greeks["delta"]
        opt.loc[_, "gamma"] = greeks["gamma"]
        opt.loc[_, "theta"] = greeks["theta"]
        opt.loc[_, "vega"] = greeks["vega"]

    # IV placeholder (use underlying volatility as proxy)
    opt["iv"] = equity_feat["volatility_20"].values
    opt["iv_rank"] = T.implied_volatility_rank(opt["iv"]).values
    opt["oi_change"] = 0  # requires option chain data

    # Date filtering
    if start is not None:
        opt = opt[opt["date"] >= pd.Timestamp(start)]
    if end is not None:
        opt = opt[opt["date"] <= pd.Timestamp(end)]

    return opt.dropna().reset_index(drop=True)
