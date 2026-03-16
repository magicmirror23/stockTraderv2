"""Technical indicator and derived-feature transforms.

All functions accept a pandas DataFrame with at minimum the columns
``Close``, ``High``, ``Low``, ``Volume`` and return a Series (or DataFrame)
of the same length, filled with ``NaN`` for the warm-up period.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------

def sma(series: pd.Series, window: int = 20) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int = 20) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=span, adjust=False).mean()


# ---------------------------------------------------------------------------
# Momentum / oscillators
# ---------------------------------------------------------------------------

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD line, signal line and histogram."""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({
        "macd": macd_line,
        "macd_signal": signal_line,
        "macd_hist": histogram,
    })


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    return tr.rolling(window=period, min_periods=period).mean()


def volatility(series: pd.Series, window: int = 20) -> pd.Series:
    """Rolling standard deviation of returns (annualised)."""
    log_ret = np.log(series / series.shift(1))
    return log_ret.rolling(window=window, min_periods=window).std() * np.sqrt(252)


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------

def returns(series: pd.Series, period: int = 1) -> pd.Series:
    """Simple percentage returns."""
    return series.pct_change(periods=period)


def log_returns(series: pd.Series, period: int = 1) -> pd.Series:
    """Logarithmic returns."""
    return np.log(series / series.shift(period))


# ---------------------------------------------------------------------------
# Volume features
# ---------------------------------------------------------------------------

def volume_spike(volume: pd.Series, window: int = 20, threshold: float = 2.0) -> pd.Series:
    """Binary flag: 1 when volume exceeds *threshold* × rolling mean."""
    vol_ma = volume.rolling(window=window, min_periods=window).mean()
    return (volume > threshold * vol_ma).astype(int)


def volume_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    """Current volume / rolling mean volume."""
    vol_ma = volume.rolling(window=window, min_periods=window).mean()
    return volume / vol_ma.replace(0, np.nan)


# ---------------------------------------------------------------------------
# Trend strength & mean-reversion features
# ---------------------------------------------------------------------------

def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index – trend strength indicator (0-100)."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)

    # When +DM > -DM keep +DM, else 0 (and vice versa)
    plus_dm[plus_dm <= minus_dm] = 0
    minus_dm[minus_dm <= plus_dm] = 0

    tr = pd.concat([
        (high - low),
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr_val = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_val
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_val

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    return dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def bollinger_band_width(series: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.Series:
    """Bollinger Band width as a percentage of the middle band."""
    mid = series.rolling(window=window, min_periods=window).mean()
    std = series.rolling(window=window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return ((upper - lower) / mid.replace(0, np.nan))


def bollinger_pct_b(series: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.Series:
    """Bollinger %B – where price sits within the bands (0 = lower, 1 = upper)."""
    mid = series.rolling(window=window, min_periods=window).mean()
    std = series.rolling(window=window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return (series - lower) / (upper - lower).replace(0, np.nan)


def stochastic_k(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Stochastic %K oscillator."""
    low_min = df["Low"].rolling(window=period, min_periods=period).min()
    high_max = df["High"].rolling(window=period, min_periods=period).max()
    return (df["Close"] - low_min) / (high_max - low_min).replace(0, np.nan) * 100


def price_distance_from_sma(series: pd.Series, window: int = 50) -> pd.Series:
    """Normalised distance of price from SMA (mean-reversion signal)."""
    ma = series.rolling(window=window, min_periods=window).mean()
    return (series - ma) / ma.replace(0, np.nan)


def return_momentum(series: pd.Series, window: int = 10) -> pd.Series:
    """Sum of daily returns over the last *window* days (momentum score)."""
    daily_ret = series.pct_change()
    return daily_ret.rolling(window=window, min_periods=window).sum()


def higher_highs(df: pd.DataFrame, window: int = 5) -> pd.Series:
    """Rolling count of consecutive higher highs – trend continuation signal."""
    high = df["High"]
    hh = (high > high.shift(1)).astype(int)
    # Count consecutive 1s
    groups = hh.ne(hh.shift()).cumsum()
    return hh.groupby(groups).cumsum()


def gap_pct(df: pd.DataFrame) -> pd.Series:
    """Overnight gap as a percentage of previous close."""
    return (df["Open"] - df["Close"].shift(1)) / df["Close"].shift(1).replace(0, np.nan)


# ---------------------------------------------------------------------------
# Additional features for improved accuracy
# ---------------------------------------------------------------------------

def vwap(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Volume Weighted Average Price (rolling)."""
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    vwap_val = (typical_price * df["Volume"]).rolling(window, min_periods=window).sum() / \
               df["Volume"].rolling(window, min_periods=window).sum().replace(0, np.nan)
    return vwap_val


def vwap_distance(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """Normalised distance of price from VWAP."""
    v = vwap(df, window)
    return (df["Close"] - v) / v.replace(0, np.nan)


def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume — cumulative volume weighted by price direction."""
    direction = np.sign(df["Close"].diff())
    return (direction * df["Volume"]).cumsum()


def obv_slope(df: pd.DataFrame, window: int = 10) -> pd.Series:
    """Slope of OBV over a rolling window (normalised)."""
    obv_val = obv(df)
    obv_ma = obv_val.rolling(window, min_periods=window).mean()
    return (obv_val - obv_ma) / obv_ma.abs().replace(0, np.nan)


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Williams %R oscillator (-100 to 0)."""
    high_max = df["High"].rolling(window=period, min_periods=period).max()
    low_min = df["Low"].rolling(window=period, min_periods=period).min()
    return -100 * (high_max - df["Close"]) / (high_max - low_min).replace(0, np.nan)


def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Commodity Channel Index."""
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    tp_sma = typical_price.rolling(window=period, min_periods=period).mean()
    tp_mad = typical_price.rolling(window=period, min_periods=period).apply(
        lambda x: np.abs(x - x.mean()).mean(), raw=True
    )
    return (typical_price - tp_sma) / (0.015 * tp_mad).replace(0, np.nan)


def roc(series: pd.Series, period: int = 10) -> pd.Series:
    """Rate of Change."""
    return (series - series.shift(period)) / series.shift(period).replace(0, np.nan) * 100


def ema_crossover(series: pd.Series, fast: int = 10, slow: int = 20) -> pd.Series:
    """EMA crossover signal: (fast_ema - slow_ema) / slow_ema."""
    fast_ema = series.ewm(span=fast, adjust=False).mean()
    slow_ema = series.ewm(span=slow, adjust=False).mean()
    return (fast_ema - slow_ema) / slow_ema.replace(0, np.nan)


def lagged_return(series: pd.Series, lag: int = 1) -> pd.Series:
    """Return lagged by *lag* periods."""
    return series.pct_change(periods=lag)


def sma_long(series: pd.Series, window: int = 200) -> pd.Series:
    """Long-term SMA (e.g., 200-day)."""
    return series.rolling(window=window, min_periods=window).mean()


def price_position_52w(df: pd.DataFrame, window: int = 252) -> pd.Series:
    """Where price sits between 52-week low and high (0 to 1)."""
    low_min = df["Low"].rolling(window=window, min_periods=60).min()
    high_max = df["High"].rolling(window=window, min_periods=60).max()
    return (df["Close"] - low_min) / (high_max - low_min).replace(0, np.nan)


def stochastic_d(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.Series:
    """Stochastic %D (smoothed %K)."""
    k = stochastic_k(df, k_period)
    return k.rolling(window=d_period, min_periods=d_period).mean()


def rsi_divergence(series: pd.Series, period: int = 14, lookback: int = 10) -> pd.Series:
    """Simple RSI-price divergence indicator.
    Positive = bullish divergence (price down, RSI up).
    Negative = bearish divergence (price up, RSI down).
    """
    rsi_val = rsi(series, period)
    price_change = series.diff(lookback)
    rsi_change = rsi_val.diff(lookback)
    # Normalise to [-1, 1] range
    price_dir = np.sign(price_change)
    rsi_dir = np.sign(rsi_change)
    return rsi_dir - price_dir  # +2 bullish div, -2 bearish div, 0 agreement


# ---------------------------------------------------------------------------
# Demo-strategy features (force_index, high_low_ratio, rolling stats, etc.)
# ---------------------------------------------------------------------------

def force_index(df: pd.DataFrame, period: int = 13) -> pd.Series:
    """Force Index — volume-weighted price change."""
    fi = df["Close"].diff() * df["Volume"]
    return fi.ewm(span=period, adjust=False).mean()


def high_low_ratio(df: pd.DataFrame) -> pd.Series:
    """High / Low price ratio — intraday volatility proxy."""
    return df["High"] / df["Low"].replace(0, np.nan)


def return_mean(series: pd.Series, window: int = 5) -> pd.Series:
    """Rolling mean of percentage returns."""
    ret = series.pct_change()
    return ret.rolling(window=window, min_periods=window).mean()


def return_skew(series: pd.Series, window: int = 10) -> pd.Series:
    """Rolling skewness of percentage returns."""
    ret = series.pct_change()
    return ret.rolling(window=window, min_periods=window).skew()


def volume_change(volume: pd.Series) -> pd.Series:
    """Percentage change in volume."""
    return volume.pct_change()


def close_to_sma(series: pd.Series, window: int = 20) -> pd.Series:
    """Close / SMA ratio — mean-reversion signal."""
    ma = series.rolling(window=window, min_periods=window).mean()
    return series / ma.replace(0, np.nan)


def day_of_week(df: pd.DataFrame) -> pd.Series:
    """Day of week (0=Mon … 4=Fri) from the Date column."""
    if "Date" in df.columns:
        return pd.to_datetime(df["Date"]).dt.dayofweek
    return pd.Series(0, index=df.index)


def lagged_return_shift(series: pd.Series, lag: int = 1) -> pd.Series:
    """Lagged returns — returns shifted by *lag* periods (look-back)."""
    ret = series.pct_change()
    return ret.shift(lag)


# ---------------------------------------------------------------------------
# Option-specific features
# ---------------------------------------------------------------------------

def implied_volatility_rank(iv_series: pd.Series, window: int = 252) -> pd.Series:
    """IV rank: percentile of current IV within rolling window."""
    rolling_min = iv_series.rolling(window=window, min_periods=20).min()
    rolling_max = iv_series.rolling(window=window, min_periods=20).max()
    range_ = rolling_max - rolling_min
    return ((iv_series - rolling_min) / range_.replace(0, np.nan)).clip(0, 1)


def open_interest_change(oi_series: pd.Series) -> pd.Series:
    """Daily change in open interest."""
    return oi_series.diff()


def put_call_ratio(put_oi: pd.Series, call_oi: pd.Series) -> pd.Series:
    """Put/Call open interest ratio."""
    return put_oi / call_oi.replace(0, np.nan)


def greeks_estimate(
    spot: float,
    strike: float,
    days_to_expiry: float,
    iv: float,
    risk_free_rate: float = 0.065,
    option_type: str = "CE",
) -> dict[str, float]:
    """Approximate Black-Scholes Greeks for a European option.

    Returns dict with delta, gamma, theta, vega.
    """
    from scipy.stats import norm
    import math

    if days_to_expiry <= 0 or iv <= 0:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}

    T = days_to_expiry / 365.0
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * iv ** 2) * T) / (iv * math.sqrt(T))
    d2 = d1 - iv * math.sqrt(T)

    if option_type == "CE":
        delta = norm.cdf(d1)
    else:
        delta = norm.cdf(d1) - 1

    gamma = norm.pdf(d1) / (spot * iv * math.sqrt(T))
    theta = (-(spot * norm.pdf(d1) * iv) / (2 * math.sqrt(T))
             - risk_free_rate * strike * math.exp(-risk_free_rate * T)
             * (norm.cdf(d2) if option_type == "CE" else norm.cdf(-d2))) / 365.0
    vega = spot * norm.pdf(d1) * math.sqrt(T) / 100.0

    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}
