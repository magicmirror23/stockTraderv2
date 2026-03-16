"""Prometheus metrics, model health monitoring, and Sentry integration."""

from __future__ import annotations

import logging
from typing import Any

from backend.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus
# ---------------------------------------------------------------------------

try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest
    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False
    logger.info("prometheus_client not installed – metrics export disabled")


# ---------------------------------------------------------------------------
# Sentry
# ---------------------------------------------------------------------------

try:
    import sentry_sdk
    _SENTRY_DSN = settings.SENTRY_DSN or ""
    if _SENTRY_DSN:
        sentry_sdk.init(dsn=_SENTRY_DSN, traces_sample_rate=0.1)
        _SENTRY_AVAILABLE = True
        logger.info("Sentry initialised")
    else:
        _SENTRY_AVAILABLE = False
except ImportError:
    _SENTRY_AVAILABLE = False
    logger.info("sentry_sdk not installed – error reporting disabled")


# ---------------------------------------------------------------------------
# Metrics definitions (no-op stubs when prometheus_client is absent)
# ---------------------------------------------------------------------------

if _PROM_AVAILABLE:
    PREDICTION_REQUESTS = Counter(
        "stocktrader_prediction_requests_total",
        "Total prediction requests",
        ["endpoint"],
    )
    PREDICTION_LATENCY = Histogram(
        "stocktrader_prediction_latency_seconds",
        "Prediction endpoint latency",
        ["endpoint"],
    )
    MODEL_VERSION_GAUGE = Gauge(
        "stocktrader_model_version_info",
        "Currently loaded model version (label)",
        ["version"],
    )
    MODEL_ACCURACY_GAUGE = Gauge(
        "stocktrader_model_accuracy",
        "Current model test accuracy",
    )
    TRADE_EXECUTIONS = Counter(
        "stocktrader_trade_executions_total",
        "Total trade executions",
        ["side", "status"],
    )
    # Option-specific metrics
    OPTION_SIGNAL_COUNT = Counter(
        "stocktrader_option_signals_total",
        "Total option signals generated",
        ["option_type", "action"],
    )
    OPTION_STRATEGY_COUNT = Counter(
        "stocktrader_option_strategy_total",
        "Total option strategy intents",
        ["strategy"],
    )
    # Replay metrics
    REPLAY_RUNS = Counter(
        "stocktrader_replay_runs_total",
        "Total paper replay runs",
    )
    REPLAY_DURATION = Histogram(
        "stocktrader_replay_duration_seconds",
        "Paper replay execution time",
    )
    # Drift metrics
    DRIFT_DETECTED = Counter(
        "stocktrader_drift_detected_total",
        "Number of drift detections",
        ["feature", "test_type"],
    )
    # Retrain metrics
    RETRAIN_RUNS = Counter(
        "stocktrader_retrain_runs_total",
        "Total retrain runs",
        ["status"],
    )


# ---------------------------------------------------------------------------
# Recording helpers
# ---------------------------------------------------------------------------


def record_prediction(endpoint: str, latency: float) -> None:
    if _PROM_AVAILABLE:
        PREDICTION_REQUESTS.labels(endpoint=endpoint).inc()
        PREDICTION_LATENCY.labels(endpoint=endpoint).observe(latency)


def set_model_info(version: str, accuracy: float | None = None) -> None:
    if _PROM_AVAILABLE:
        MODEL_VERSION_GAUGE.labels(version=version).set(1)
        if accuracy is not None:
            MODEL_ACCURACY_GAUGE.set(accuracy)


def record_trade(side: str, status: str) -> None:
    if _PROM_AVAILABLE:
        TRADE_EXECUTIONS.labels(side=side, status=status).inc()


def record_option_signal(option_type: str, action: str) -> None:
    if _PROM_AVAILABLE:
        OPTION_SIGNAL_COUNT.labels(option_type=option_type, action=action).inc()


def record_option_strategy(strategy: str) -> None:
    if _PROM_AVAILABLE:
        OPTION_STRATEGY_COUNT.labels(strategy=strategy).inc()


def record_replay(duration: float) -> None:
    if _PROM_AVAILABLE:
        REPLAY_RUNS.inc()
        REPLAY_DURATION.observe(duration)


def record_drift(feature: str, test_type: str) -> None:
    if _PROM_AVAILABLE:
        DRIFT_DETECTED.labels(feature=feature, test_type=test_type).inc()


def record_retrain(status: str) -> None:
    if _PROM_AVAILABLE:
        RETRAIN_RUNS.labels(status=status).inc()


def capture_exception(exc: Exception) -> None:
    """Send exception to Sentry if available."""
    if _SENTRY_AVAILABLE:
        sentry_sdk.capture_exception(exc)
    logger.error("Captured exception: %s", exc)


def get_metrics_text() -> str:
    """Return Prometheus-compatible metrics text."""
    if _PROM_AVAILABLE:
        return generate_latest().decode("utf-8")
    return "# prometheus_client not installed\n"
