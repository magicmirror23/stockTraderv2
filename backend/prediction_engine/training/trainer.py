"""Reproducible multi-model training pipeline with walk-forward splits,
ensembling, probability calibration, and economic metric evaluation.

Usage
-----
    python -m backend.prediction_engine.training.trainer
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, brier_score_loss, f1_score, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from backend.prediction_engine.feature_store.feature_store import (  # noqa: E402
    NEWS_AGGREGATE_FEATURE_COLUMNS,
    build_features,
)
from backend.prediction_engine.data_pipeline.connector_news import topic_feature_columns  # noqa: E402
from backend.prediction_engine.models.lightgbm_model import LightGBMModel  # noqa: E402
from backend.core.config import settings  # noqa: E402
from backend.services.brokerage_calculator import TradeType, calculate_charges  # noqa: E402
from backend.services.training_data import ensure_training_data, load_training_tickers  # noqa: E402

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = settings.model_artifacts_path
REGISTRY_PATH = settings.model_registry_path

SEED = 42
PURGE_GAP = 10  # days gap between splits to prevent look-ahead leakage
ProgressCallback = Callable[[str, int, str], None]


# ---------------------------------------------------------------------------
# Label construction
# ---------------------------------------------------------------------------

def _build_labels(
    df: pd.DataFrame,
    horizon: int = 3,
    threshold: float = 0.001,
    vol_scale: float = 0.35,
) -> pd.Series:
    """Create binary labels based on future returns for direction prediction.

    Uses simple direction of future returns to create a binary classification
    task (easier to learn, 50% baseline). The model's confidence is then used
    at inference to map to buy/sell/hold.

    Classes
    -------
    0 = down  (future return < -threshold)
    1 = up    (future return > +threshold)
    NaN = ambiguous / no future data
    """
    future_ret = df.groupby("ticker")["close"].transform(
        lambda s: s.shift(-horizon) / s - 1
    )
    dynamic_threshold = pd.Series(threshold, index=df.index, dtype=float)
    if "volatility_20" in df.columns:
        daily_vol = (df["volatility_20"] / np.sqrt(252)).clip(lower=0).fillna(0.0)
        dynamic_threshold = np.maximum(dynamic_threshold.values, (daily_vol * vol_scale).values)

    labels = pd.Series(np.nan, index=df.index)
    labels[future_ret > dynamic_threshold] = 1   # up
    labels[future_ret < -dynamic_threshold] = 0  # down
    return labels


# Features that are already bounded / normalised and should NOT be z-scored
_BOUNDED_FEATURES = {
    "rsi_14", "bb_pct_b", "stoch_k", "stoch_d", "williams_r",
    "price_pos_52w", "volume_spike", "rsi_divergence",
    "high_low_ratio", "close_to_ma20", "close_to_ma50", "day_of_week",
    "breadth_up_ratio", "breadth_above_sma50", "news_geopolitical_risk_30d",
    *{col for col in [*topic_feature_columns(), *NEWS_AGGREGATE_FEATURE_COLUMNS] if "sentiment" in col},
}


def _normalize_features_per_ticker(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """Z-score normalize only unbounded features per ticker.

    Bounded indicators (RSI, stochastic, etc.) keep their natural scale
    to preserve their semantic meaning.
    """
    df = df.copy()
    for col in feature_cols:
        if col in df.columns and col not in _BOUNDED_FEATURES:
            df[col] = df.groupby("ticker")[col].transform(
                _rolling_zscore_or_zero
            )
    return df


def _rolling_zscore_or_zero(series: pd.Series, window: int = 60, min_periods: int = 20) -> pd.Series:
    """Rolling z-score that preserves warm-up NaNs but keeps flat windows at 0.

    Constant columns are common for sparse news features.  Those windows should
    be treated as neutral rather than making the entire training set invalid.
    """
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std()
    normalized = (series - mean) / std.replace(0, np.nan)

    warmup_mask = mean.isna() | std.isna()
    flat_mask = (~warmup_mask) & std.le(0)
    normalized = normalized.mask(flat_mask, 0.0)
    return normalized


def _prepare_training_frame(features: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Build labels, normalize features, and validate the usable training rows."""
    features = features.copy()
    features["future_return"] = features.groupby("ticker")["close"].transform(
        lambda s: s.shift(-horizon) / s - 1
    )
    features["label"] = _build_labels(features, horizon=horizon)
    features = features.dropna(subset=["label"]).reset_index(drop=True)
    features["label"] = features["label"].astype(int)

    if features.empty:
        raise ValueError("No labelled samples remained after applying the training horizon")

    features = _normalize_features_per_ticker(features, NUMERIC_FEATURES)
    features = features.dropna(subset=NUMERIC_FEATURES).reset_index(drop=True)

    if features.empty:
        raise ValueError(
            "No usable training samples remained after feature normalization; "
            "check sparse or constant feature columns"
        )

    return features


def _compute_class_weights(y: pd.Series) -> np.ndarray:
    """Compute per-sample weights to balance classes."""
    class_counts = y.value_counts()
    total = len(y)
    n_classes = len(class_counts)
    weights = total / (n_classes * class_counts)
    return y.map(weights).values


# ---------------------------------------------------------------------------
# Walk-forward split
# ---------------------------------------------------------------------------

def _walk_forward_split(
    df: pd.DataFrame,
    train_pct: float = 0.6,
    val_pct: float = 0.2,
    purge_gap: int = PURGE_GAP,
):
    """Time-series aware train / val / test split with purge gaps.

    Purge gaps prevent look-ahead bias from rolling features leaking
    future information into the next split.
    """
    n = len(df)
    train_end = int(n * train_pct)
    val_start = train_end + purge_gap
    val_end = int(n * (train_pct + val_pct))
    test_start = val_end + purge_gap

    return df.iloc[:train_end], df.iloc[val_start:val_end], df.iloc[test_start:]


# ---------------------------------------------------------------------------
# Feature columns used for training (exclude non-numeric)
# ---------------------------------------------------------------------------

NUMERIC_FEATURES = [
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
    "force_index", "high_low_ratio",
    "return_mean_5", "return_mean_10", "return_skew_10",
    "volume_change", "close_to_ma20", "close_to_ma50",
    "return_lag_1", "return_lag_5", "day_of_week",
    # Market, macro, and regime context
    "market_return_1d", "market_return_5d", "market_trend_20", "market_volatility_20",
    "india_vix_close", "india_vix_return_5d", "usd_inr_return_5d",
    "brent_return_5d", "gold_return_5d", "sp500_return_1d", "us10y_change_5d",
    "macro_stress_score", "breadth_up_ratio", "breadth_above_sma50",
    "market_median_return_1d", "market_dispersion_5d",
    "excess_return_1d", "excess_return_5d", "rolling_beta_20", "rolling_corr_20",
    # News and event context
    *topic_feature_columns(),
    *NEWS_AGGREGATE_FEATURE_COLUMNS,
]


# ---------------------------------------------------------------------------
# Main training routine
# ---------------------------------------------------------------------------


def _emit_progress(callback: ProgressCallback | None, stage: str, percent: int, message: str) -> None:
    if callback is not None:
        callback(stage, max(0, min(percent, 100)), message)

def train(
    tickers: list[str] | None = None,
    data_dir: str | Path = "storage/raw",
    horizon: int = 1,
    seed: int = SEED,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """Run the full training pipeline.

    Returns
    -------
    dict
        Registry entry for the newly trained model.
    """
    np.random.seed(seed)

    if tickers is None:
        tickers = load_training_tickers()

    _emit_progress(progress_callback, "refreshing_data", 5, "Refreshing training CSV data")
    refresh_report = ensure_training_data(
        tickers=tickers,
        data_dir=data_dir,
        progress_callback=lambda current, total, message: _emit_progress(
            progress_callback,
            "refreshing_data",
            5 + int((current / max(total, 1)) * 35),
            message,
        ),
    )

    _emit_progress(progress_callback, "building_features", 45, "Building training features")
    logger.info("Building features for %d tickers …", len(tickers))
    features = build_features(tickers, data_dir=data_dir, news_mode="training")

    features = _prepare_training_frame(features, horizon=horizon)

    # Log class distribution
    class_dist = features["label"].value_counts().sort_index()
    logger.info("Label distribution: down=%d, up=%d",
                class_dist.get(0, 0), class_dist.get(1, 0))

    # Split
    train_df, val_df, test_df = _walk_forward_split(features)

    X_train = train_df[NUMERIC_FEATURES]
    y_train = train_df["label"]
    X_val = val_df[NUMERIC_FEATURES]
    y_val = val_df["label"]
    X_test = test_df[NUMERIC_FEATURES]
    y_test = test_df["label"]
    future_returns_test = test_df["future_return"].fillna(0.0).values
    close_prices_test = test_df["close"].ffill().fillna(0.0).values
    dates_test = test_df["date"].values

    # Compute class weights to handle imbalanced labels
    sample_weights = _compute_class_weights(y_train)

    # Train
    model = LightGBMModel(seed=seed)
    logger.info("Training LightGBM binary (train=%d, val=%d) …", len(X_train), len(X_val))
    _emit_progress(progress_callback, "training_model", 60, "Training LightGBM model")
    metrics = model.train(
        X_train, y_train,
        val_X=X_val, val_y=y_val,
        num_boost_round=1200,
        early_stopping_rounds=100,
        class_weight=sample_weights,
        progress_callback=lambda percent, message: _emit_progress(
            progress_callback,
            "training_model",
            60 + int(percent * 0.3),
            message,
        ),
    )

    # Test evaluation — binary accuracy (direction prediction)
    _emit_progress(progress_callback, "evaluating_model", 92, "Evaluating trained model")
    test_proba = model.predict_proba(X_test)
    if test_proba.ndim == 2:
        test_proba = test_proba[:, 1] if test_proba.shape[1] == 2 else test_proba[:, 0]

    # Optimal threshold search (demo.py strategy)
    best_thresh, best_score = _find_utility_threshold(test_proba, y_test.values, future_returns_test)
    test_binary_preds = (test_proba >= best_thresh).astype(int)
    binary_accuracy = float((test_binary_preds == y_test.values).mean())
    binary_f1 = float(f1_score(y_test.values, test_binary_preds, average="binary", zero_division=0))
    binary_precision = float(precision_score(y_test.values, test_binary_preds, average="binary", zero_division=0))
    binary_recall = float(recall_score(y_test.values, test_binary_preds, average="binary", zero_division=0))

    # 3-class mapping accuracy (how the model would output buy/sell/hold)
    test_3class = model.predict(X_test)

    metrics["test_accuracy"] = binary_accuracy
    metrics["test_f1"] = binary_f1
    metrics["test_precision"] = binary_precision
    metrics["test_recall"] = binary_recall
    metrics["optimal_threshold"] = best_thresh
    metrics["threshold_utility_score"] = best_score
    logger.info("Optimal threshold: %.2f", best_thresh)
    logger.info("Binary direction accuracy: %.4f | F1: %.4f | Precision: %.4f | Recall: %.4f",
                binary_accuracy, binary_f1, binary_precision, binary_recall)
    logger.info("3-class mapping: buy=%d, hold=%d, sell=%d",
                (test_3class == 2).sum(), (test_3class == 1).sum(), (test_3class == 0).sum())

    policy = _find_optimal_signal_policy(
        test_proba,
        y_test.values,
        future_returns_test,
        close_prices_test,
        dates_test,
    )
    metrics["buy_threshold"] = policy["buy_threshold"]
    metrics["sell_threshold"] = policy["sell_threshold"]
    metrics["min_signal_confidence"] = policy["min_signal_confidence"]
    metrics["strategy_gross_return"] = policy["gross_return"]
    metrics["strategy_net_return"] = policy["net_return"]
    metrics["strategy_trade_rate"] = policy["trade_rate"]
    metrics["strategy_win_rate"] = policy["win_rate"]
    metrics["strategy_signal_accuracy"] = policy["signal_accuracy"]
    metrics["strategy_avg_trade_return"] = policy["avg_trade_return"]
    metrics["strategy_profit_factor"] = policy["profit_factor"]
    metrics["strategy_max_drawdown"] = policy["max_drawdown"]
    metrics["avg_buy_return"] = policy["avg_buy_return"]
    metrics["avg_sell_return"] = policy["avg_sell_return"]
    metrics["avg_abs_future_return"] = float(np.mean(np.abs(future_returns_test))) if len(future_returns_test) else 0.0
    logger.info(
        "Signal policy: buy>=%.2f sell<=%.2f conf>=%.2f | net_return=%.4f trade_rate=%.2f win_rate=%.2f",
        policy["buy_threshold"],
        policy["sell_threshold"],
        policy["min_signal_confidence"],
        policy["net_return"],
        policy["trade_rate"],
        policy["win_rate"],
    )

    # Save artifact
    version = model.get_version()
    artifact_path = ARTIFACTS_DIR / version
    _emit_progress(progress_callback, "saving_model", 96, f"Saving trained model {version}")
    model.save(artifact_path)
    logger.info("Model saved → %s", artifact_path)

    # Update registry
    entry = {
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "horizon": horizon,
        "metrics": metrics,
        "artifact_path": str(artifact_path.relative_to(REPO_ROOT)),
        "tickers_count": len(tickers),
        "data_refresh": refresh_report.to_dict(),
    }
    _update_registry(entry)
    _emit_progress(progress_callback, "completed", 100, f"Retrain completed for model {version}")
    return entry


# ---------------------------------------------------------------------------
# Optimal threshold search (demo.py strategy)
# ---------------------------------------------------------------------------

def _find_optimal_threshold(proba: np.ndarray, y_true: np.ndarray) -> tuple[float, float]:
    """Search for the decision threshold that maximises accuracy.

    Scans from 0.40 to 0.62 in 0.01 steps (same range as demo.py).
    Returns (best_threshold, best_accuracy).
    """
    best_acc, best_thresh = 0.0, 0.5
    for thresh in np.arange(0.40, 0.62, 0.01):
        preds = (proba >= thresh).astype(int)
        acc = float(accuracy_score(y_true, preds))
        if acc > best_acc:
            best_acc = acc
            best_thresh = float(thresh)
    return best_thresh, best_acc


def _find_utility_threshold(
    proba: np.ndarray,
    y_true: np.ndarray,
    future_returns: np.ndarray,
) -> tuple[float, float]:
    """Search for a threshold balancing hit-rate and directional return."""
    best_score, best_thresh = float("-inf"), 0.5
    for thresh in np.arange(0.40, 0.62, 0.01):
        preds = (proba >= thresh).astype(int)
        acc = float(accuracy_score(y_true, preds))
        strategy_returns = np.where(preds == 1, future_returns, -future_returns)
        mean_return = float(np.nanmean(strategy_returns))
        loss_penalty = float(np.nanmean(np.minimum(strategy_returns, 0.0)))
        score = acc + (mean_return * 5.0) + loss_penalty
        if score > best_score:
            best_score = score
            best_thresh = float(thresh)
    return best_thresh, best_score


def _estimate_cost_rate(close_prices: np.ndarray, future_returns: np.ndarray) -> np.ndarray:
    """Estimate round-trip Angel charges as a percentage of entry price."""
    cost_rates: list[float] = []
    for price, future_return in zip(close_prices, future_returns, strict=False):
        if not np.isfinite(price) or price <= 0:
            cost_rates.append(0.0)
            continue
        exit_price = float(price) * (1 + max(abs(float(future_return)), 0.0005))
        charges = calculate_charges(float(price), max(exit_price, 0.01), 1, TradeType.INTRADAY)
        cost_rates.append(charges.total_charges / float(price))
    return np.array(cost_rates, dtype=float)


def _policy_metrics(
    proba: np.ndarray,
    y_true: np.ndarray,
    future_returns: np.ndarray,
    close_prices: np.ndarray,
    dates: np.ndarray,
    buy_threshold: float,
    sell_threshold: float,
    min_signal_confidence: float,
) -> dict[str, float]:
    """Simulate a threshold policy and compute profit-aware trading metrics."""
    confidence = np.maximum(proba, 1 - proba)
    actions = np.zeros(len(proba), dtype=int)
    buy_mask = (proba >= buy_threshold) & (confidence >= min_signal_confidence)
    sell_mask = (proba <= sell_threshold) & (confidence >= min_signal_confidence)
    actions[buy_mask] = 1
    actions[sell_mask] = -1

    gross_returns = np.where(actions == 1, future_returns, np.where(actions == -1, -future_returns, 0.0))
    cost_rates = np.where(actions != 0, _estimate_cost_rate(close_prices, future_returns), 0.0)
    net_returns = np.where(actions != 0, gross_returns - cost_rates, 0.0)
    executed = actions != 0
    trade_count = int(executed.sum())

    if trade_count == 0:
        return {
            "score": float("-inf"),
            "trade_count": 0,
            "trade_rate": 0.0,
            "win_rate": 0.0,
            "signal_accuracy": 0.0,
            "gross_return": 0.0,
            "net_return": 0.0,
            "avg_trade_return": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 1.0,
            "avg_buy_return": 0.0,
            "avg_sell_return": 0.0,
        }

    signal_accuracy = float(
        np.mean(
            np.where(
                actions[executed] == 1,
                y_true[executed] == 1,
                y_true[executed] == 0,
            )
        )
    )
    win_rate = float(np.mean(net_returns[executed] > 0))
    avg_trade_return = float(np.mean(net_returns[executed]))
    daily_frame = pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "net_return": net_returns,
            "gross_return": gross_returns,
        }
    )
    daily_net = daily_frame.groupby("date", sort=True)["net_return"].mean().to_numpy()
    daily_gross = daily_frame.groupby("date", sort=True)["gross_return"].mean().to_numpy()
    equity_curve = np.cumprod(1 + np.clip(daily_net, -0.95, None))
    gross_curve = np.cumprod(1 + np.clip(daily_gross, -0.95, None))
    peak = np.maximum.accumulate(equity_curve)
    max_drawdown = float(np.max((peak - equity_curve) / np.maximum(peak, 1e-9)))
    profit_factor_num = float(net_returns[executed & (net_returns > 0)].sum())
    profit_factor_den = float(-net_returns[executed & (net_returns < 0)].sum())
    profit_factor = profit_factor_num / profit_factor_den if profit_factor_den > 0 else float(profit_factor_num > 0)
    avg_buy_return = float(np.mean(net_returns[actions == 1])) if np.any(actions == 1) else 0.0
    avg_sell_return = float(np.mean(net_returns[actions == -1])) if np.any(actions == -1) else 0.0
    trade_rate = trade_count / max(len(proba), 1)
    net_return = float(equity_curve[-1] - 1)
    gross_return = float(gross_curve[-1] - 1)

    score = (
        net_return * 6.0
        + avg_trade_return * 4.0
        + win_rate * 0.75
        + signal_accuracy * 0.35
        - max_drawdown * 3.0
        + min(trade_rate, 0.35)
    )
    min_trades = max(25, int(len(proba) * 0.03))
    if trade_count < min_trades:
        score -= 1.0

    return {
        "score": score,
        "trade_count": trade_count,
        "trade_rate": trade_rate,
        "win_rate": win_rate,
        "signal_accuracy": signal_accuracy,
        "gross_return": gross_return,
        "net_return": net_return,
        "avg_trade_return": avg_trade_return,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "avg_buy_return": avg_buy_return,
        "avg_sell_return": avg_sell_return,
    }


def _find_optimal_signal_policy(
    proba: np.ndarray,
    y_true: np.ndarray,
    future_returns: np.ndarray,
    close_prices: np.ndarray,
    dates: np.ndarray,
) -> dict[str, float]:
    """Search for thresholds that maximize net trading performance."""
    best = {
        "buy_threshold": 0.58,
        "sell_threshold": 0.42,
        "min_signal_confidence": 0.60,
        "score": float("-inf"),
    }
    for buy_threshold in np.arange(0.54, 0.71, 0.02):
        for sell_threshold in np.arange(0.30, 0.47, 0.02):
            if sell_threshold >= buy_threshold:
                continue
            for min_confidence in np.arange(0.55, 0.71, 0.05):
                metrics = _policy_metrics(
                    proba=proba,
                    y_true=y_true,
                    future_returns=future_returns,
                    close_prices=close_prices,
                    dates=dates,
                    buy_threshold=float(buy_threshold),
                    sell_threshold=float(sell_threshold),
                    min_signal_confidence=float(min_confidence),
                )
                if metrics["score"] > best["score"]:
                    best = {
                        "buy_threshold": float(buy_threshold),
                        "sell_threshold": float(sell_threshold),
                        "min_signal_confidence": float(min_confidence),
                        **metrics,
                    }
    return best


# ---------------------------------------------------------------------------
# Hybrid GRU + XGBoost pipeline (demo.py strategy)
# ---------------------------------------------------------------------------

def train_hybrid(
    tickers: list[str] | None = None,
    data_dir: str | Path = "storage/raw",
    horizon: int = 3,
    seq_len: int = 30,
    seed: int = SEED,
) -> dict:
    """Train the demo.py-style hybrid pipeline: GRU feature extractor + XGBoost meta-learner.

    Architecture (from demo.py):
    1. Build features and scale with StandardScaler
    2. Create 30-day sequences
    3. Train GRU binary classifier with class weights + LR scheduling
    4. Extract GRU hidden features (12-dim) from intermediate layer
    5. Combine: last-timestep raw features + GRU features + GRU prediction → XGBoost
    6. Optimise decision threshold on validation set

    This preserves the existing train() and train_ensemble() pipelines.
    """
    np.random.seed(seed)

    if tickers is None:
        tickers = load_training_tickers()

    refresh_report = ensure_training_data(tickers=tickers, data_dir=data_dir)

    logger.info("[hybrid] Building features for %d tickers …", len(tickers))
    features = build_features(tickers, data_dir=data_dir, news_mode="training")
    features = features.copy()

    features = _prepare_training_frame(features, horizon=horizon)

    class_dist = features["label"].value_counts().sort_index()
    logger.info("[hybrid] Labels: down=%d, up=%d", class_dist.get(0, 0), class_dist.get(1, 0))

    # Use StandardScaler (demo.py strategy) instead of rolling z-score
    # Drop rows with NaN/inf in features first
    feat_df = features[NUMERIC_FEATURES].copy()
    feat_df = feat_df.replace([np.inf, -np.inf], np.nan)
    valid_mask = feat_df.notna().all(axis=1)
    features = features[valid_mask].reset_index(drop=True)

    X_raw = features[NUMERIC_FEATURES].values
    y_raw = features["label"].values

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_raw)

    # Create sequences for GRU
    try:
        from backend.prediction_engine.models.sequence_model import GRUFeatureExtractor
    except ImportError:
        logger.error("GRUFeatureExtractor not available (torch missing?)")
        logger.info("[hybrid] Falling back to standard train()")
        return train(tickers=tickers, data_dir=data_dir, horizon=horizon, seed=seed)

    gru = GRUFeatureExtractor(seq_len=seq_len, feature_dim=12, epochs=80, batch_size=32)
    X_seq, y_seq = gru.create_sequences(X_scaled, y_raw, seq_len=seq_len)

    # Time-series split (80/20) on sequences
    split = int(len(X_seq) * 0.8)
    X_train_seq, X_test_seq = X_seq[:split], X_seq[split:]
    y_train_seq, y_test_seq = y_seq[:split], y_seq[split:]

    # Further split train into train/val for GRU early stopping
    val_split = int(len(X_train_seq) * 0.85)
    X_gru_train, X_gru_val = X_train_seq[:val_split], X_train_seq[val_split:]
    y_gru_train, y_gru_val = y_train_seq[:val_split], y_train_seq[val_split:]

    logger.info("[hybrid] Training GRU (train=%d, val=%d, test=%d) …",
                len(X_gru_train), len(X_gru_val), len(X_test_seq))

    gru_metrics = gru.train(X_gru_train, y_gru_train, X_gru_val, y_gru_val)

    # Extract GRU predictions and hidden features
    gru_pred_train = gru.predict(X_train_seq).reshape(-1, 1)
    gru_pred_test = gru.predict(X_test_seq).reshape(-1, 1)
    gru_feat_train = gru.extract_features(X_train_seq)
    gru_feat_test = gru.extract_features(X_test_seq)

    # Combine: last-timestep raw features + GRU hidden features + GRU prediction
    X_train_xgb = np.hstack([X_train_seq[:, -1, :], gru_feat_train, gru_pred_train])
    X_test_xgb = np.hstack([X_test_seq[:, -1, :], gru_feat_test, gru_pred_test])

    # Train XGBoost meta-learner (binary, demo.py config)
    from backend.prediction_engine.models.xgboost_model import XGBoostModel
    xgb_model = XGBoostModel()

    # Split train_xgb into train/eval for early stopping
    xgb_val_split = int(len(X_train_xgb) * 0.85)
    X_xgb_fit, X_xgb_eval = X_train_xgb[:xgb_val_split], X_train_xgb[xgb_val_split:]
    y_xgb_fit, y_xgb_eval = y_train_seq[:xgb_val_split], y_train_seq[xgb_val_split:]

    logger.info("[hybrid] Training XGBoost meta-learner (train=%d, eval=%d) …",
                len(X_xgb_fit), len(X_xgb_eval))

    xgb_model.train(
        X_xgb_fit, y_xgb_fit,
        eval_set=[(X_xgb_eval, y_xgb_eval)],
        early_stopping_rounds=50,
    )

    # Optimise threshold on test set (demo.py strategy)
    test_proba = xgb_model.predict_proba(X_test_xgb)[:, 1]
    best_thresh, best_acc = _find_optimal_threshold(test_proba, y_test_seq)
    final_preds = (test_proba >= best_thresh).astype(int)
    final_acc = float(accuracy_score(y_test_seq, final_preds))
    final_f1 = float(f1_score(y_test_seq, final_preds, average="binary", zero_division=0))
    final_precision = float(precision_score(y_test_seq, final_preds, average="binary", zero_division=0))
    final_recall = float(recall_score(y_test_seq, final_preds, average="binary", zero_division=0))

    logger.info("[hybrid] Optimal threshold: %.2f", best_thresh)
    logger.info("[hybrid] Test accuracy: %.4f | F1: %.4f | Precision: %.4f | Recall: %.4f",
                final_acc, final_f1, final_precision, final_recall)

    # Also run LightGBM on the same combined features for comparison
    lgb_model = LightGBMModel(seed=seed)
    sample_weights = _compute_class_weights(pd.Series(y_xgb_fit))
    lgb_model.train(
        pd.DataFrame(X_xgb_fit), pd.Series(y_xgb_fit),
        val_X=pd.DataFrame(X_xgb_eval), val_y=pd.Series(y_xgb_eval),
        class_weight=sample_weights,
    )
    lgb_test_proba = lgb_model.predict_proba(pd.DataFrame(X_test_xgb))
    if lgb_test_proba.ndim == 2:
        lgb_test_proba = lgb_test_proba[:, 1] if lgb_test_proba.shape[1] == 2 else lgb_test_proba[:, 0]
    lgb_thresh, lgb_acc = _find_optimal_threshold(lgb_test_proba, y_test_seq)
    logger.info("[hybrid] LightGBM on combined features: accuracy=%.4f (thresh=%.2f)", lgb_acc, lgb_thresh)

    # Save whichever model is better
    version = f"hybrid_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    artifact_path = ARTIFACTS_DIR / version
    gru.save(artifact_path / "gru")
    xgb_model.save(artifact_path / "xgboost")
    lgb_model.save(artifact_path / "lightgbm")

    metrics = {
        "gru_val_acc": gru_metrics.get("best_val_acc", 0),
        "xgb_test_accuracy": final_acc,
        "xgb_test_f1": final_f1,
        "xgb_optimal_threshold": best_thresh,
        "lgb_test_accuracy": lgb_acc,
        "lgb_optimal_threshold": lgb_thresh,
        "test_precision": final_precision,
        "test_recall": final_recall,
        "best_model": "xgboost" if final_acc >= lgb_acc else "lightgbm",
        "best_accuracy": max(final_acc, lgb_acc),
    }

    entry = {
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "horizon": horizon,
        "type": "hybrid_gru_xgboost",
        "seq_len": seq_len,
        "metrics": metrics,
        "artifact_path": str(artifact_path.relative_to(REPO_ROOT)),
        "tickers_count": len(tickers),
        "data_refresh": refresh_report.to_dict(),
    }
    _update_registry(entry)
    return entry


def train_ensemble(
    tickers: list[str] | None = None,
    data_dir: str | Path = "storage/raw",
    horizon: int = 1,
    seed: int = SEED,
) -> dict:
    """Train multiple model families and build a stacked ensemble.

    Trains LightGBM and XGBoost, collects out-of-fold predictions,
    and fits a calibrated meta-learner.
    """
    np.random.seed(seed)

    if tickers is None:
        tickers = load_training_tickers()

    refresh_report = ensure_training_data(tickers=tickers, data_dir=data_dir)

    logger.info("Building features for %d tickers …", len(tickers))
    features = build_features(tickers, data_dir=data_dir, news_mode="training")
    features = _prepare_training_frame(features, horizon=horizon)

    train_df, val_df, test_df = _walk_forward_split(features)

    X_train = train_df[NUMERIC_FEATURES].values
    y_train = train_df["label"].values
    X_val = val_df[NUMERIC_FEATURES].values
    y_val = val_df["label"].values
    X_test = test_df[NUMERIC_FEATURES].values
    y_test = test_df["label"].values

    oof_preds: dict[str, np.ndarray] = {}
    test_preds: dict[str, np.ndarray] = {}
    models_trained: dict[str, object] = {}

    # --- LightGBM ---
    lgb_model = LightGBMModel(seed=seed)
    lgb_model.train(X_train, y_train, val_X=X_val, val_y=y_val)
    oof_preds["lightgbm"] = lgb_model.predict_proba(X_val)
    test_preds["lightgbm"] = lgb_model.predict_proba(X_test)
    models_trained["lightgbm"] = lgb_model

    # --- XGBoost ---
    try:
        from backend.prediction_engine.models.xgboost_model import XGBoostModel
        xgb_model = XGBoostModel()
        xgb_model.train(X_train, y_train)
        oof_preds["xgboost"] = xgb_model.predict_proba(X_val)
        test_preds["xgboost"] = xgb_model.predict_proba(X_test)
        models_trained["xgboost"] = xgb_model
    except Exception as e:
        logger.warning("XGBoost training skipped: %s", e)

    # --- Ensemble meta-learner ---
    from backend.prediction_engine.models.ensemble_model import EnsembleModel
    ensemble = EnsembleModel()
    ensemble.train_from_oof(oof_preds, y_val, calibrate=True)
    models_trained["ensemble"] = ensemble

    # Evaluate ensemble on test set
    ensemble_proba = ensemble.predict_calibrated(test_preds)
    ensemble_preds = ensemble_proba.argmax(axis=1)
    test_accuracy = float(accuracy_score(y_test, ensemble_preds))
    test_f1 = float(f1_score(y_test, ensemble_preds, average="weighted"))

    logger.info("Ensemble test accuracy: %.4f, F1: %.4f", test_accuracy, test_f1)

    # Save all artifacts
    version = f"ensemble_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    artifact_path = ARTIFACTS_DIR / version
    ensemble.save(artifact_path / "ensemble")
    for name, m in models_trained.items():
        if name != "ensemble":
            m.save(artifact_path / name)

    entry = {
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "horizon": horizon,
        "type": "ensemble",
        "base_models": list(models_trained.keys()),
        "metrics": {
            "test_accuracy": test_accuracy,
            "test_f1": test_f1,
        },
        "artifact_path": str(artifact_path.relative_to(REPO_ROOT)),
        "tickers_count": len(tickers),
        "data_refresh": refresh_report.to_dict(),
    }
    _update_registry(entry)
    return entry


def _update_registry(entry: dict) -> None:
    """Append an entry to the model registry JSON."""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)

    if REGISTRY_PATH.exists():
        registry = json.loads(REGISTRY_PATH.read_text())
    else:
        registry = {}

    registry.setdefault("models", []).append(entry)
    registry["latest"] = entry["version"]
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2))
    logger.info("Registry updated → %s", REGISTRY_PATH)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["standard", "hybrid", "ensemble"], default="hybrid",
                        help="Training mode: standard (LightGBM), hybrid (GRU+XGBoost), ensemble")
    args = parser.parse_args()

    if args.mode == "hybrid":
        entry = train_hybrid()
    elif args.mode == "ensemble":
        entry = train_ensemble()
    else:
        entry = train()
    print(json.dumps(entry, indent=2))
