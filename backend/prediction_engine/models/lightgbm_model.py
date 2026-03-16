"""LightGBM classification model for stock action prediction."""

from __future__ import annotations

import json
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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
            "learning_rate": 0.02,
            "num_leaves": 63,
            "max_depth": 6,
            "min_child_samples": 45,
            "feature_fraction": 0.85,
            "feature_fraction_bynode": 0.75,
            "bagging_fraction": 0.8,
            "bagging_freq": 3,
            "lambda_l1": 0.1,
            "lambda_l2": 2.0,
            "min_gain_to_split": 0.0,
            "path_smooth": 2,
            "max_bin": 511,
            "is_unbalance": True,
            "seed": self._seed,
            "verbose": -1,
        }

    def _signal_policy(self) -> dict[str, float]:
        metrics = self._metrics or {}
        return {
            "buy_threshold": float(metrics.get("buy_threshold", max(metrics.get("optimal_threshold", 0.58), 0.55))),
            "sell_threshold": float(metrics.get("sell_threshold", min(1 - metrics.get("optimal_threshold", 0.58), 0.45))),
            "min_signal_confidence": float(metrics.get("min_signal_confidence", 0.60)),
            "avg_abs_future_return": float(metrics.get("avg_abs_future_return", 0.012)),
            "avg_buy_return": float(metrics.get("avg_buy_return", metrics.get("avg_abs_future_return", 0.012))),
            "avg_sell_return": float(metrics.get("avg_sell_return", -metrics.get("avg_abs_future_return", 0.012))),
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
        progress_callback: Callable[[int, str], None] | None = kwargs.get("progress_callback")

        dtrain = lgb.Dataset(X, label=y, weight=class_weight)
        valid_sets = [dtrain]
        valid_names = ["train"]
        callbacks = [lgb.log_evaluation(period=50)]

        if val_X is not None and val_y is not None:
            dval = lgb.Dataset(val_X, label=val_y, reference=dtrain)
            valid_sets.append(dval)
            valid_names.append("val")
            callbacks.append(lgb.early_stopping(early_stopping_rounds))

        if progress_callback is not None:
            def report_progress(env: Any) -> None:
                total_rounds = max(num_boost_round, 1)
                current_round = min(env.iteration + 1, total_rounds)
                percent = int((current_round / total_rounds) * 100)
                if current_round == 1 or current_round % 10 == 0 or current_round == total_rounds:
                    progress_callback(percent, f"LightGBM round {current_round}/{total_rounds}")

            callbacks.append(report_progress)

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

        Binary model predicts P(up). Map to 3 classes using the learned
        threshold policy from training when available.
        """
        proba_up = self.predict_proba(X)
        if proba_up.ndim == 2:
            proba_up = proba_up[:, 1] if proba_up.shape[1] == 2 else proba_up[:, 0]
        policy = self._signal_policy()
        confidence = np.maximum(proba_up, 1 - proba_up)
        labels = np.ones(len(proba_up), dtype=int)  # default hold
        labels[(proba_up >= policy["buy_threshold"]) & (confidence >= policy["min_signal_confidence"])] = 2
        labels[(proba_up <= policy["sell_threshold"]) & (confidence >= policy["min_signal_confidence"])] = 0
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
        policy = self._signal_policy()
        n = len(proba_up)
        result = np.zeros((n, 3))
        for i, p_up in enumerate(proba_up):
            p_down = 1 - p_up
            confidence = max(p_up, p_down)
            if p_up >= policy["buy_threshold"] and confidence >= policy["min_signal_confidence"]:
                buy_strength = max((p_up - policy["buy_threshold"]) / max(1 - policy["buy_threshold"], 1e-6), 0.0)
                result[i] = [0.08, 0.18, 0.74 + buy_strength * 0.2]
            elif p_up <= policy["sell_threshold"] and confidence >= policy["min_signal_confidence"]:
                sell_strength = max((policy["sell_threshold"] - p_up) / max(policy["sell_threshold"], 1e-6), 0.0)
                result[i] = [0.74 + sell_strength * 0.2, 0.18, 0.08]
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
        policy = self._signal_policy()
        results = []
        for p_up in proba_up:
            p_down = 1 - p_up
            confidence = float(max(p_up, p_down))
            signal_edge = float(abs(p_up - 0.5) * 2)

            buy_threshold = policy["buy_threshold"]
            sell_threshold = policy["sell_threshold"]
            min_signal_confidence = policy["min_signal_confidence"]
            if price is not None and quantity > 0:
                breakeven = estimate_breakeven_move(price, quantity, TradeType.INTRADAY)
                breakeven_pct = breakeven / price if price > 0 else 0
                buy_threshold = min(0.78, buy_threshold + breakeven_pct * 4)
                sell_threshold = max(0.22, sell_threshold - breakeven_pct * 4)
                min_signal_confidence = min(0.92, max(min_signal_confidence, 0.5 + breakeven_pct * 5))

            if confidence < min_signal_confidence:
                action = "hold"
            elif p_up >= buy_threshold:
                action = "buy"
            elif p_up <= sell_threshold:
                action = "sell"
            else:
                action = "hold"

            if action == "buy":
                expected_return = max(policy["avg_buy_return"], policy["avg_abs_future_return"]) * signal_edge
            elif action == "sell":
                expected_return = min(policy["avg_sell_return"], -policy["avg_abs_future_return"]) * signal_edge
            else:
                expected_return = 0.0

            net_expected_return = expected_return
            if price is not None and quantity > 0:
                breakeven = estimate_breakeven_move(price, quantity, TradeType.INTRADAY)
                net_expected_return = expected_return - (breakeven / price if price > 0 else 0)

            results.append({
                "action": action,
                "confidence": round(confidence, 4),
                "expected_return": round(expected_return, 6),
                "net_expected_return": round(net_expected_return, 6),
                "signal_policy": {
                    "buy_threshold": round(buy_threshold, 4),
                    "sell_threshold": round(sell_threshold, 4),
                    "min_signal_confidence": round(min_signal_confidence, 4),
                },
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
