"""XGBoost model implementation.

Wraps xgboost.XGBClassifier following the BaseModel interface.
"""

from __future__ import annotations

import json
import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from backend.prediction_engine.models.base_model import BaseModel

logger = logging.getLogger(__name__)

try:
    import xgboost as xgb
except ImportError:
    xgb = None
    logger.warning("xgboost not installed")


class XGBoostModel(BaseModel):
    """XGBoost classifier for buy/sell/hold prediction."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._params = params or {
            "n_estimators": 1000,
            "max_depth": 4,
            "learning_rate": 0.01,
            "subsample": 0.8,
            "colsample_bytree": 0.7,
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "random_state": 42,
            "use_label_encoder": False,
            "reg_alpha": 0.5,
            "reg_lambda": 2.0,
            "min_child_weight": 5,
            "gamma": 0.2,
        }
        self._model: Any = None
        self._version: str = ""
        self._trained_at: datetime | None = None
        self._best_threshold: float = 0.5

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        params: dict | None = None,
        eval_set: list | None = None,
        early_stopping_rounds: int = 50,
    ) -> None:
        if xgb is None:
            raise RuntimeError("xgboost is not installed")
        p = {**self._params, **(params or {})}
        seed = p.pop("random_state", 42)

        # Compute scale_pos_weight for class imbalance
        num_pos = int(np.sum(y == 1))
        num_neg = int(np.sum(y == 0))
        scale = num_neg / num_pos if num_pos > 0 else 1.0
        p.setdefault("scale_pos_weight", scale)

        self._model = xgb.XGBClassifier(
            **p, random_state=seed, early_stopping_rounds=early_stopping_rounds
        )
        fit_kwargs: dict[str, Any] = {"verbose": False}
        if eval_set is not None:
            fit_kwargs["eval_set"] = eval_set
        self._model.fit(X, y, **fit_kwargs)
        self._trained_at = datetime.now(timezone.utc)
        self._version = f"xgb_{self._trained_at.strftime('%Y%m%d_%H%M%S')}"

    def optimize_threshold(self, X_val: np.ndarray, y_val: np.ndarray) -> float:
        """Search for optimal decision threshold on validation set."""
        from sklearn.metrics import accuracy_score
        prob = self._model.predict_proba(X_val)[:, 1]
        best_acc, best_thresh = 0.0, 0.5
        for thresh in np.arange(0.40, 0.62, 0.01):
            preds = (prob >= thresh).astype(int)
            acc = accuracy_score(y_val, preds)
            if acc > best_acc:
                best_acc = acc
                best_thresh = float(thresh)
        self._best_threshold = best_thresh
        logger.info("Optimal threshold: %.2f (val accuracy: %.4f)", best_thresh, best_acc)
        return best_thresh

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Model not trained or loaded")
        prob = self._model.predict_proba(X)[:, 1]
        return (prob >= self._best_threshold).astype(int)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Model not trained or loaded")
        return self._model.predict_proba(X)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        with open(path / "model.pkl", "wb") as f:
            pickle.dump(self._model, f)
        meta = {
            "type": "xgboost",
            "version": self._version,
            "trained_at": self._trained_at.isoformat() if self._trained_at else None,
            "params": self._params,
            "best_threshold": self._best_threshold,
        }
        (path / "meta.json").write_text(json.dumps(meta, indent=2))

    def load(self, path: str | Path) -> None:
        path = Path(path)
        with open(path / "model.pkl", "rb") as f:
            self._model = pickle.load(f)
        meta_path = path / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            self._version = meta.get("version", "")
            self._best_threshold = meta.get("best_threshold", 0.5)

    def get_version(self) -> str:
        return self._version
