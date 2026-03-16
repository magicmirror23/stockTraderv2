"""Tests for individual feature transforms."""

import numpy as np
import pandas as pd
import pytest

from backend.prediction_engine.feature_store.transforms import (
    sma,
    ema,
    rsi,
    macd,
    atr,
    volatility,
    returns,
    log_returns,
    volume_spike,
    volume_ratio,
)


@pytest.fixture()
def price_series() -> pd.Series:
    """Synthetic upward-trending price series (100 points)."""
    np.random.seed(42)
    base = 100.0 + np.cumsum(np.random.randn(100) * 0.5)
    return pd.Series(base)


@pytest.fixture()
def ohlcv_df(price_series) -> pd.DataFrame:
    close = price_series
    return pd.DataFrame({
        "Open": close - 0.5,
        "High": close + 1.0,
        "Low": close - 1.0,
        "Close": close,
        "Volume": np.random.randint(100_000, 500_000, size=len(close)),
    })


# --- SMA / EMA ---

def test_sma_length(price_series):
    result = sma(price_series, 20)
    assert len(result) == len(price_series)
    assert result.iloc[:19].isna().all()
    assert result.iloc[19:].notna().all()


def test_ema_length(price_series):
    result = ema(price_series, 20)
    assert len(result) == len(price_series)
    assert result.notna().all()  # EMA fills from start


# --- RSI ---

def test_rsi_range(price_series):
    result = rsi(price_series, 14).dropna()
    assert (result >= 0).all() and (result <= 100).all()


# --- MACD ---

def test_macd_columns(price_series):
    result = macd(price_series)
    assert set(result.columns) == {"macd", "macd_signal", "macd_hist"}
    assert len(result) == len(price_series)


# --- ATR ---

def test_atr_positive(ohlcv_df):
    result = atr(ohlcv_df, 14).dropna()
    assert (result > 0).all()


# --- Volatility ---

def test_volatility_non_negative(price_series):
    result = volatility(price_series, 20).dropna()
    assert (result >= 0).all()


# --- Returns ---

def test_returns_first_nan(price_series):
    result = returns(price_series, 1)
    assert pd.isna(result.iloc[0])
    assert result.iloc[1:].notna().all()


def test_log_returns_first_nan(price_series):
    result = log_returns(price_series, 1)
    assert pd.isna(result.iloc[0])


# --- Volume ---

def test_volume_spike_binary(ohlcv_df):
    result = volume_spike(ohlcv_df["Volume"], 20, 2.0).dropna()
    assert set(result.unique()).issubset({0, 1})


def test_volume_ratio_positive(ohlcv_df):
    result = volume_ratio(ohlcv_df["Volume"], 20).dropna()
    assert (result > 0).all()
