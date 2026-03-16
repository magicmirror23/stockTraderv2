"""Ensemble model: stacked meta-learner over base model predictions.

Combines out-of-fold predictions from multiple model families
(LightGBM, XGBoost, LSTM) into a calibrated meta-learner.
"""

from __future__ import annotations

import json
import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression

from backend.prediction_engine.models.base_model import BaseModel

logger = logging.getLogger(__name__)


class EnsembleModel(BaseModel):
    """Stacked ensemble that combines multiple base model predictions."""

    def __init__(self) -> None:
        self._meta_learner = None
        self._calibrator = None
        self._base_model_names: list[str] = []
        self._version: str = ""
        self._trained_at: datetime | None = None

    def train_from_oof(
        self,
        oof_predictions: dict[str, np.ndarray],
        y: np.ndarray,
        calibrate: bool = True,
    ) -> None:
        """Train stacked meta-learner from out-of-fold predictions.

        Parameters
        ----------
        oof_predictions : dict[str, np.ndarray]
            {model_name: probability_array} where each array is (n_samples, n_classes).
        y : np.ndarray
            True labels.
        calibrate : bool
            Whether to apply Platt scaling calibration.
        """
        self._base_model_names = list(oof_predictions.keys())

        # Stack predictions horizontally
        X_meta = np.hstack([oof_predictions[name] for name in self._base_model_names])

        self._meta_learner = LogisticRegression(
            max_iter=500, random_state=42, multi_class="multinomial"
        )
        self._meta_learner.fit(X_meta, y)

        if calibrate:
            self._calibrator = CalibratedClassifierCV(
                self._meta_learner, cv=3, method="isotonic"
            )
            self._calibrator.fit(X_meta, y)

        self._trained_at = datetime.now(timezone.utc)
        self._version = f"ensemble_{self._trained_at.strftime('%Y%m%d_%H%M%S')}"

    def train(self, X: np.ndarray, y: np.ndarray, params: dict | None = None) -> None:
        """Train on pre-stacked feature matrix."""
        self._meta_learner = LogisticRegression(
            max_iter=500, random_state=42, multi_class="multinomial"
        )
        self._meta_learner.fit(X, y)
        self._calibrator = CalibratedClassifierCV(
            self._meta_learner, cv=3, method="isotonic"
        )
        self._calibrator.fit(X, y)
        self._trained_at = datetime.now(timezone.utc)
        self._version = f"ensemble_{self._trained_at.strftime('%Y%m%d_%H%M%S')}"

    def predict(self, X: np.ndarray) -> np.ndarray:
        model = self._calibrator or self._meta_learner
        if model is None:
            raise RuntimeError("Ensemble not trained")
        return model.predict(X)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        model = self._calibrator or self._meta_learner
        if model is None:
            raise RuntimeError("Ensemble not trained")
        return model.predict_proba(X)

    def predict_calibrated(self, base_probas: dict[str, np.ndarray]) -> np.ndarray:
        """Predict from base model probability outputs."""
        X_meta = np.hstack([base_probas[name] for name in self._base_model_names])
        return self.predict_proba(X_meta)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        with open(path / "meta_learner.pkl", "wb") as f:
            pickle.dump(self._meta_learner, f)
        if self._calibrator:
            with open(path / "calibrator.pkl", "wb") as f:
                pickle.dump(self._calibrator, f)
        meta = {
            "type": "ensemble",
            "version": self._version,
            "trained_at": self._trained_at.isoformat() if self._trained_at else None,
            "base_models": self._base_model_names,
        }
        (path / "meta.json").write_text(json.dumps(meta, indent=2))

    def load(self, path: str | Path) -> None:
        path = Path(path)
        with open(path / "meta_learner.pkl", "rb") as f:
            self._meta_learner = pickle.load(f)
        cal_path = path / "calibrator.pkl"
        if cal_path.exists():
            with open(cal_path, "rb") as f:
                self._calibrator = pickle.load(f)
        meta = json.loads((path / "meta.json").read_text())
        self._version = meta.get("version", "")
        self._base_model_names = meta.get("base_models", [])

    def get_version(self) -> str:
        return self._version
