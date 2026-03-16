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

import numpy as np
import pandas as pd

from backend.prediction_engine.feature_store import transforms as T

logger = logging.getLogger(__name__)

MANIFEST_PATH = Path(__file__).parent / "manifest.json"

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
]


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


def build_features(
    tickers: list[str],
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    data_dir: str | Path = "storage/raw",
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
    frames: list[pd.DataFrame] = []

    for ticker in tickers:
        try:
            df = _load_ticker_csv(ticker, data_dir)
        except FileNotFoundError:
            logger.warning("Skipping %s – CSV not found in %s", ticker, data_dir)
            continue
        feat = _compute_features(df, ticker)
        frames.append(feat)

    if not frames:
        raise FileNotFoundError("No CSV data files found for any ticker")

    result = pd.concat(frames, ignore_index=True)

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
    data_dir = Path(data_dir)
    df = _load_ticker_csv(ticker, data_dir)
    feat = _compute_features(df, ticker).dropna().reset_index(drop=True)

    if feat.empty:
        raise ValueError(f"No valid feature rows for {ticker}")

    if timestamp is not None:
        ts = pd.Timestamp(timestamp)
        feat = feat[feat["date"] <= ts]
        if feat.empty:
            raise ValueError(f"No feature rows for {ticker} on or before {timestamp}")

    row = feat.iloc[-1]
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
