"""LightGBM classification model for stock action prediction."""

from __future__ import annotations

import json
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.prediction_engine.models.base_model import BaseModel

try:
    import lightgbm as lgb
except ImportError:
    lgb = None


class LightGBMModel(BaseModel):
    """LightGBM-based classifier: sell(0), hold(1), buy(2)."""

    CLASS_NAMES = ["sell", "hold", "buy"]

    def __init__(
        self,
        version: str | None = None,
        seed: int = 42,
        params: dict | None = None,
    ) -> None:
        self._seed = seed
        self._version = version or datetime.now(timezone.utc).strftime("v%Y%m%d.%H%M%S")
        self._model: lgb.Booster | None = None  # type: ignore[name-defined]
        self._params = params or self._default_params()
        self._metrics: dict = {}

    def _default_params(self) -> dict:
        return {
            "objective": "binary",
            "metric": "binary_logloss",
            "learning_rate": 0.01,
            "num_leaves": 31,
            "max_depth": 5,
            "min_child_samples": 80,
            "feature_fraction": 0.7,
            "feature_fraction_bynode": 0.5,
            "bagging_fraction": 0.7,
            "bagging_freq": 5,
            "lambda_l1": 0.3,
            "lambda_l2": 1.5,
            "min_gain_to_split": 0.02,
            "path_smooth": 5,
            "max_bin": 255,
            "is_unbalance": True,
            "seed": self._seed,
            "verbose": -1,
        }

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, X: pd.DataFrame, y: pd.Series, **kwargs: Any) -> dict:
        if lgb is None:
            raise RuntimeError("lightgbm is not installed")

        num_boost_round = kwargs.get("num_boost_round", 800)
        early_stopping_rounds = kwargs.get("early_stopping_rounds", 80)
        val_X = kwargs.get("val_X")
        val_y = kwargs.get("val_y")
        class_weight = kwargs.get("class_weight")  # optional per-sample weights

        dtrain = lgb.Dataset(X, label=y, weight=class_weight)
        valid_sets = [dtrain]
        valid_names = ["train"]
        callbacks = [lgb.log_evaluation(period=50)]

        if val_X is not None and val_y is not None:
            dval = lgb.Dataset(val_X, label=val_y, reference=dtrain)
            valid_sets.append(dval)
            valid_names.append("val")
            callbacks.append(lgb.early_stopping(early_stopping_rounds))

        self._model = lgb.train(
            self._params,
            dtrain,
            num_boost_round=num_boost_round,
            valid_sets=valid_sets,
            valid_names=valid_names,
            callbacks=callbacks,
        )

        # Compute accuracy on training data
        raw_preds = self._model.predict(X)
        if isinstance(raw_preds, np.ndarray) and raw_preds.ndim == 1:
            binary_preds = (raw_preds > 0.5).astype(int)
        else:
            binary_preds = np.argmax(raw_preds, axis=1)
        accuracy = float((binary_preds == y.values if hasattr(y, 'values') else binary_preds == y).mean())
        self._metrics = {
            "accuracy": accuracy,
            "best_iteration": self._model.best_iteration,
        }
        return self._metrics

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return 3-class labels: 0=sell, 1=hold, 2=buy.

        Binary model predicts P(up). Map to 3 classes using confidence:
        - P(up) > 0.55 → buy (2)
        - P(up) < 0.45 → sell (0)
        - otherwise → hold (1)
        """
        proba_up = self.predict_proba(X)
        if proba_up.ndim == 2:
            proba_up = proba_up[:, 1] if proba_up.shape[1] == 2 else proba_up[:, 0]
        labels = np.ones(len(proba_up), dtype=int)  # default hold
        labels[proba_up > 0.55] = 2   # buy
        labels[proba_up < 0.45] = 0   # sell
        return labels

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return raw model probabilities.

        For binary model, returns P(up) as 1D array.
        """
        if self._model is None:
            raise RuntimeError("Model not trained / loaded")
        raw = self._model.predict(X)
        return raw

    def predict_proba_3class(self, X: pd.DataFrame) -> np.ndarray:
        """Return 3-class probability matrix (n_samples, 3).

        Maps binary P(up) to [P(sell), P(hold), P(buy)] using
        confidence-based allocation.
        """
        proba_up = self.predict_proba(X)
        if proba_up.ndim == 2:
            proba_up = proba_up[:, 1] if proba_up.shape[1] == 2 else proba_up[:, 0]
        n = len(proba_up)
        result = np.zeros((n, 3))
        for i, p_up in enumerate(proba_up):
            p_down = 1 - p_up
            if p_up > 0.55:
                result[i] = [0.1, 0.2, 0.7 * (p_up / 0.55)]  # buy-leaning
            elif p_up < 0.45:
                result[i] = [0.7 * (p_down / 0.55), 0.2, 0.1]  # sell-leaning
            else:
                result[i] = [0.2, 0.6, 0.2]  # hold
            result[i] /= result[i].sum()  # normalize
        return result

    def predict_with_expected_return(
        self, X: pd.DataFrame, price: float | None = None, quantity: int = 1
    ) -> list[dict]:
        """Return action probabilities mapped to actions + expected return estimate.

        When *price* and *quantity* are provided, factors in Angel One brokerage
        charges so that only trades with a positive net-of-charges return are
        recommended.
        """
        from backend.services.brokerage_calculator import estimate_breakeven_move, TradeType

        proba_up = self.predict_proba(X)
        if proba_up.ndim == 2:
            proba_up = proba_up[:, 1] if proba_up.shape[1] == 2 else proba_up[:, 0]
        results = []
        for p_up in proba_up:
            p_down = 1 - p_up

            # Cost-aware thresholds
            buy_threshold = 0.55
            sell_threshold = 0.45
            if price is not None and quantity > 0:
                breakeven = estimate_breakeven_move(price, quantity, TradeType.INTRADAY)
                breakeven_pct = breakeven / price if price > 0 else 0
                buy_threshold = min(0.70, 0.55 + breakeven_pct * 3)
                sell_threshold = max(0.30, 0.45 - breakeven_pct * 3)

            if p_up > buy_threshold:
                action = "buy"
            elif p_up < sell_threshold:
                action = "sell"
            else:
                action = "hold"

            confidence = float(max(p_up, p_down))
            expected_return = float(p_up - 0.5) * 0.10  # scaled direction signal

            net_expected_return = expected_return
            if price is not None and quantity > 0:
                breakeven = estimate_breakeven_move(price, quantity, TradeType.INTRADAY)
                net_expected_return = expected_return - (breakeven / price if price > 0 else 0)

            results.append({
                "action": action,
                "confidence": round(confidence, 4),
                "expected_return": round(expected_return, 6),
                "net_expected_return": round(net_expected_return, 6),
            })
        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        model_file = path / "model.pkl"
        meta_file = path / "meta.json"

        with open(model_file, "wb") as f:
            pickle.dump(self._model, f)

        meta = {
            "version": self._version,
            "seed": self._seed,
            "params": self._params,
            "metrics": self._metrics,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        meta_file.write_text(json.dumps(meta, indent=2))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "LightGBMModel":
        path = Path(path)
        meta = json.loads((path / "meta.json").read_text())

        instance = cls(
            version=meta["version"],
            seed=meta.get("seed", 42),
            params=meta.get("params"),
        )
        with open(path / "model.pkl", "rb") as f:
            instance._model = pickle.load(f)  # noqa: S301
        instance._metrics = meta.get("metrics", {})
        return instance

    def get_version(self) -> str:
        return self._version
