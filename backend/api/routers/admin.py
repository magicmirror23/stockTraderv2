"""Retrain, monitoring, drift detection, and model management endpoints."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import PlainTextResponse

from backend.services.model_manager import ModelManager
from backend.services.model_registry import ModelRegistry
from backend.services.monitoring import (
    capture_exception,
    get_metrics_text,
    record_retrain,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

# Track retrain state so the frontend can poll progress
_retrain_status: dict[str, Any] = {
    "running": False,
    "progress": None,
    "progress_percent": 0,
    "error": None,
    "message": None,
    "model_version": None,
    "metrics": None,
    "data_refresh": None,
    "last_started_at": None,
    "last_finished_at": None,
}
_retrain_logs: list[dict[str, Any]] = []
_retrain_log_lock = threading.Lock()
_retrain_log_cursor = 0
_MAX_RETRAIN_LOG_LINES = 400
_last_progress_logged: dict[str, Any] = {"stage": None, "percent": -1}
_RETRAIN_LOGGER_PREFIXES = (
    "backend.prediction_engine",
    "backend.services.training_data",
    "backend.services.model_manager",
    "backend.services.mlflow_registry",
    "backend.services.monitoring",
    "yfinance",
)


def _require_auth(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")
    return authorization.split(" ", 1)[1]


def _run_train_sync(progress_callback=None) -> dict:
    """Run training in a thread – never call from the event loop directly."""
    from backend.prediction_engine.training.trainer import train
    return train(progress_callback=progress_callback)


def _update_retrain_progress(stage: str, percent: int, message: str) -> None:
    _retrain_status.update(progress=stage, progress_percent=percent, message=message)
    should_log = (
        _last_progress_logged["stage"] != stage
        or percent in {0, 100}
        or percent - int(_last_progress_logged["percent"]) >= 5
    )
    if should_log:
        _last_progress_logged.update(stage=stage, percent=percent)
        logger.info("Retrain progress %s%% [%s] %s", percent, stage, message)


class _RetrainLogHandler(logging.Handler):
    """Capture training logs in memory for the admin panel."""

    def emit(self, record: logging.LogRecord) -> None:
        if not _should_capture_retrain_log(record):
            return
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        _append_retrain_log(record.levelname, record.name, message)


def _append_retrain_log(level: str, logger_name: str, message: str) -> None:
    global _retrain_log_cursor
    with _retrain_log_lock:
        _retrain_log_cursor += 1
        _retrain_logs.append(
            {
                "id": _retrain_log_cursor,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "logger": logger_name,
                "message": message,
            }
        )
        if len(_retrain_logs) > _MAX_RETRAIN_LOG_LINES:
            del _retrain_logs[: len(_retrain_logs) - _MAX_RETRAIN_LOG_LINES]


def _should_capture_retrain_log(record: logging.LogRecord) -> bool:
    logger_name = record.name or ""
    if logger_name == "backend.core.middleware":
        return False
    if logger_name.startswith(_RETRAIN_LOGGER_PREFIXES):
        return True
    if logger_name == "yfinance":
        return True
    return record.levelno >= logging.WARNING


def _clear_retrain_logs() -> None:
    with _retrain_log_lock:
        _retrain_logs.clear()
    _last_progress_logged.update(stage=None, percent=-1)


def _get_retrain_logs(after: int = 0) -> tuple[list[dict[str, Any]], int]:
    with _retrain_log_lock:
        entries = [entry for entry in _retrain_logs if entry["id"] > after]
        next_cursor = _retrain_logs[-1]["id"] if _retrain_logs else after
    return entries, next_cursor


async def _run_retrain_background() -> None:
    handler = _RetrainLogHandler()
    handler.setLevel(logging.INFO)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    try:
        _update_retrain_progress("training", 2, "Retrain background job started")
        _append_retrain_log("INFO", __name__, "Retrain background job started")
        entry = await asyncio.to_thread(_run_train_sync, _update_retrain_progress)

        try:
            from backend.services.mlflow_registry import log_model_training
            log_model_training(
                experiment_name="stocktrader",
                model_version=entry["version"],
                params=entry.get("params", {}),
                metrics=entry.get("metrics", {}),
            )
        except Exception:
            logger.debug("MLflow logging skipped")

        mgr = ModelManager()
        _update_retrain_progress("loading_model", 98, "Loading newly trained model")
        mgr.load_latest()

        record_retrain("success")
        _retrain_status.update(
            running=False,
            progress="done",
            progress_percent=100,
            error=None,
            message="Retrain completed",
            model_version=entry["version"],
            metrics=entry.get("metrics"),
            data_refresh=entry.get("data_refresh"),
            last_finished_at=datetime.now(timezone.utc).isoformat(),
        )
        _append_retrain_log("INFO", __name__, f"Retrain completed with model version {entry['version']}")
    except Exception as exc:
        logger.exception("Retrain failed")
        record_retrain("failed")
        capture_exception(exc)
        _retrain_status.update(
            running=False,
            progress="failed",
            progress_percent=100,
            error=str(exc),
            message="Retrain failed",
            last_finished_at=datetime.now(timezone.utc).isoformat(),
        )
        _append_retrain_log("ERROR", __name__, f"Retrain failed: {exc}")
    finally:
        root_logger.removeHandler(handler)


@router.get("/retrain/status")
async def retrain_status():
    """Poll retrain progress without blocking."""
    return _retrain_status


@router.get("/retrain/logs")
async def retrain_logs(
    after: int = 0,
    token: str = Depends(_require_auth),
):
    """Return buffered retrain log lines for the admin panel."""
    entries, next_cursor = _get_retrain_logs(after=after)
    return {
        "entries": entries,
        "next_cursor": next_cursor,
        "running": _retrain_status["running"],
        "progress": _retrain_status["progress"],
        "progress_percent": _retrain_status["progress_percent"],
    }


@router.post("/retrain")
async def retrain(token: str = Depends(_require_auth)):
    """Trigger a model retrain.

    Returns immediately and performs training in the background so
    free-hosted deployments do not hit request timeouts.
    """
    if _retrain_status["running"]:
        return {
            "message": "Retrain already in progress",
            "status": "running",
            "progress": _retrain_status["progress"],
            "progress_percent": _retrain_status["progress_percent"],
            "last_started_at": _retrain_status["last_started_at"],
        }

    _retrain_status.update(
        running=True,
        progress="queued",
        progress_percent=0,
        error=None,
        message="Retrain started",
        model_version=None,
        metrics=None,
        data_refresh=None,
        last_started_at=datetime.now(timezone.utc).isoformat(),
        last_finished_at=None,
    )
    _clear_retrain_logs()
    _append_retrain_log("INFO", __name__, "Retrain requested from admin panel")

    asyncio.create_task(_run_retrain_background())

    return {
        "message": "Retrain started",
        "status": "queued",
        "progress": "queued",
        "progress_percent": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    """Prometheus-compatible metrics endpoint."""
    return get_metrics_text()


@router.get("/registry/versions")
async def registry_versions():
    """List all registered model versions."""
    reg = ModelRegistry()
    return {
        "latest": reg.get_latest_version(),
        "versions": reg.list_versions(),
    }


@router.get("/registry/mlflow")
async def mlflow_latest():
    """Return latest model version from MLflow registry."""
    try:
        from backend.services.mlflow_registry import get_latest_model_version
        info = get_latest_model_version()
        if info is None:
            return {"status": "no_models_registered"}
        return info
    except Exception:
        return {"status": "mlflow_unavailable"}


@router.post("/drift/check")
async def check_drift(token: str = Depends(_require_auth)):
    """Run drift detection on the current feature distribution vs training."""
    try:
        import numpy as np
        from backend.prediction_engine.monitoring.drift import (
            DriftConfig,
            detect_label_drift,
            summarize_drift,
        )
        from backend.services.monitoring import record_drift

        # In a full deployment, reference and current data would come from
        # a feature store or database.  Here we return the drift detection
        # capability and config.
        return {
            "status": "drift_check_available",
            "config": {
                "ks_threshold": DriftConfig().ks_p_value_threshold,
                "psi_threshold": DriftConfig().psi_threshold,
            },
            "message": "Supply reference/current data via the Python API for full detection.",
        }
    except ImportError as exc:
        return {"status": "unavailable", "detail": str(exc)}


@router.get("/canary/status")
async def canary_status():
    """Return current canary deployment status (if active)."""
    try:
        from backend.prediction_engine.monitoring.canary import CanaryEvaluator
        return {
            "status": "canary_module_available",
            "message": "Use CanaryEvaluator Python API to manage canary deployments.",
        }
    except ImportError:
        return {"status": "unavailable"}
