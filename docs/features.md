# Feature Specification

> Generated for StockTrader v0.1.0

## Feature Columns

All features are computed from raw OHLCV data.  The columns below are produced
by `build_features()` and are consumed by models in the exact order listed.

| # | Column | Type | Description |
|---|--------|------|-------------|
| 1 | `ticker` | str | Ticker symbol identifier |
| 2 | `date` | datetime | Trading date |
| 3 | `close` | float | Closing price |
| 4 | `sma_10` | float | 10-day Simple Moving Average of Close |
| 5 | `sma_20` | float | 20-day Simple Moving Average of Close |
| 6 | `sma_50` | float | 50-day Simple Moving Average of Close |
| 7 | `ema_10` | float | 10-day Exponential Moving Average of Close |
| 8 | `ema_20` | float | 20-day Exponential Moving Average of Close |
| 9 | `rsi_14` | float | 14-day Relative Strength Index (0–100) |
| 10 | `macd` | float | MACD line (EMA12 – EMA26) |
| 11 | `macd_signal` | float | 9-day EMA of MACD line |
| 12 | `macd_hist` | float | MACD histogram (macd – signal) |
| 13 | `atr_14` | float | 14-day Average True Range |
| 14 | `volatility_20` | float | 20-day annualised volatility of log-returns |
| 15 | `return_1d` | float | 1-day simple percentage return |
| 16 | `return_5d` | float | 5-day simple percentage return |
| 17 | `log_return_1d` | float | 1-day logarithmic return |
| 18 | `volume_spike` | int | 1 if volume > 2× 20-day mean, else 0 |
| 19 | `volume_ratio` | float | Current volume / 20-day mean volume |

## Warm-up Period

The longest look-back window is the 50-day SMA, so the first 49 rows of each
ticker will contain NaN values and are dropped by `build_features()`.

## Determinism

All transforms are deterministic — no randomness is involved.  Given the same
input CSV, the output feature matrix will be identical.

## Versioning

A manifest file (`prediction_engine/feature_store/manifest.json`) is written
each time `build_features()` runs, recording:

- Feature column names and order
- Tickers processed
- Row count and date range
- Timestamp of generation
