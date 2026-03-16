"""Model loading with safe fallback for cloud and demo deployments."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from typing import Any

from backend.core.config import settings
from backend.prediction_engine.models.lightgbm_model import LightGBMModel


logger = logging.getLogger(__name__)


class ModelManager:
    """Thread-safe singleton that keeps a model or a deterministic fallback active."""

    _instance: "ModelManager | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "ModelManager":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._lock = threading.Lock()
                    cls._instance._model = None
                    cls._instance._status = "not_loaded"
                    cls._instance._model_version = "demo-fallback"
                    cls._instance._last_error = None
                    cls._instance._last_loaded_version = None
        return cls._instance

    @property
    def model(self) -> LightGBMModel | None:
        return self._model

    @property
    def status(self) -> str:
        return self._status

    @property
    def model_version(self) -> str:
        return self._model_version

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def ensure_loaded(self) -> str:
        if self._status in {"loaded", "demo_fallback"}:
            return self._model_version
        try:
            return self.load_latest()
        except Exception:
            logger.exception("Model load failed during ensure_loaded; demo fallback will remain active")
            self._activate_demo_fallback("load_failed")
            return self._model_version

    def load_latest(self) -> str:
        return self._load_version(version=None)

    def load_version(self, version: str) -> str:
        return self._load_version(version=version)

    def _load_version(self, version: str | None) -> str:
        with self._lock:
            registry = self._read_registry()
            if version is None:
                version = registry.get("latest")
            if not version:
                self._activate_demo_fallback("registry_missing")
                return self._model_version

            artifact_path = settings.model_registry_path.parent / "artifacts" / version
            if not artifact_path.exists():
                self._activate_demo_fallback(f"artifact_missing:{version}")
                return self._model_version

            try:
                self._model = LightGBMModel.load(artifact_path)
            except Exception as exc:
                logger.warning("Model artifact load failed for %s: %s", version, exc)
                self._activate_demo_fallback(f"artifact_corrupt:{version}")
                return self._model_version

            self._status = "loaded"
            self._last_error = None
            self._model_version = version
            self._last_loaded_version = version
            logger.info("Loaded model version %s", version)
            return version

    def _activate_demo_fallback(self, reason: str) -> None:
        self._model = None
        self._status = "demo_fallback"
        self._last_error = reason
        self._model_version = "demo-fallback"
        logger.warning("Using demo prediction fallback", extra={"mode": "demo"})

    def get_model_info(self) -> dict[str, Any]:
        registry = self._read_registry()
        metrics = {}
        last_trained = None
        for entry in registry.get("models", []):
            if entry.get("version") == self._last_loaded_version:
                metrics = entry.get("metrics", {})
                last_trained = entry.get("timestamp")
                break
        return {
            "model_version": self._model_version,
            "status": self._status,
            "last_trained": last_trained,
            "accuracy": metrics.get("test_accuracy"),
            "fallback": self._status == "demo_fallback",
            "last_error": self._last_error,
        }

    def predict(self, ticker: str, horizon_days: int = 1) -> dict[str, Any]:
        self.ensure_loaded()
        if self._model is None or self._status != "loaded":
            return self._fallback_prediction(ticker, horizon_days)

        try:
            import pandas as pd
            from backend.prediction_engine.feature_store.feature_store import FEATURE_COLUMNS, get_features_for_inference

            feat_dict = get_features_for_inference(ticker)
            numeric_cols = [c for c in FEATURE_COLUMNS if c not in ("ticker", "date")]
            X = pd.DataFrame([{c: feat_dict[c] for c in numeric_cols}])
            results = self._model.predict_with_expected_return(X)
            r = results[0]
            return {
                "action": r["action"],
                "confidence": r["confidence"],
                "expected_return": r["expected_return"],
                "model_version": self._model_version,
                "calibration_score": r.get("calibration_score"),
                "fallback": False,
                "close": float(feat_dict.get("close", 100.0)),
            }
        except Exception as exc:
            logger.warning("Predicting %s with loaded model failed: %s", ticker, exc)
            return self._fallback_prediction(ticker, horizon_days)

    @staticmethod
    def _read_registry() -> dict[str, Any]:
        path = settings.model_registry_path
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"models": [], "latest": None}

    def _fallback_prediction(self, ticker: str, horizon_days: int) -> dict[str, Any]:
        seed = int(hashlib.sha256(f"{ticker}:{horizon_days}".encode("utf-8")).hexdigest()[:8], 16)
        bucket = seed % 3
        action = ("buy", "hold", "sell")[bucket]
        confidence = round(0.55 + ((seed >> 3) % 30) / 100, 2)
        confidence = min(confidence, 0.84)
        expected_return = round((((seed >> 5) % 600) - 300) / 10_000, 4)
        close = round(100 + (seed % 5000) / 50, 2)
        return {
            "action": action,
            "confidence": confidence,
            "expected_return": expected_return,
            "model_version": "demo-fallback",
            "calibration_score": None,
            "fallback": True,
            "close": close,
        }
