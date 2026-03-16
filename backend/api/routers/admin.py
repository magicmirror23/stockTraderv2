"""Retrain, monitoring, drift detection, and model management endpoints."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

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
_retrain_status: dict = {"running": False, "progress": None, "error": None}


def _require_auth(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid bearer token")
    return authorization.split(" ", 1)[1]


def _run_train_sync() -> dict:
    """Run training in a thread – never call from the event loop directly."""
    from backend.prediction_engine.training.trainer import train
    return train()


@router.get("/retrain/status")
async def retrain_status():
    """Poll retrain progress without blocking."""
    return _retrain_status


@router.post("/retrain")
async def retrain(token: str = Depends(_require_auth)):
    """Trigger a model retrain.

    Training runs in a background thread so the event loop stays responsive
    for live-chart, bot, and other endpoints.
    """
    if _retrain_status["running"]:
        return {"message": "Retrain already in progress", "status": "running"}

    _retrain_status.update(running=True, progress="training", error=None)

    try:
        loop = asyncio.get_event_loop()
        entry = await loop.run_in_executor(None, _run_train_sync)

        # Log to MLflow (non-critical)
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

        # Reload the freshly trained model
        mgr = ModelManager()
        mgr.load_latest()

        record_retrain("success")
        _retrain_status.update(running=False, progress="done", error=None)

        return {
            "message": "Retrain completed",
            "model_version": entry["version"],
            "metrics": entry["metrics"],
            "data_refresh": entry.get("data_refresh", {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.exception("Retrain failed")
        record_retrain("failed")
        capture_exception(exc)
        _retrain_status.update(running=False, progress="failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


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
