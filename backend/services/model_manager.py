"""Model loading with safe fallback for cloud and demo deployments."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from typing import Any

from backend.core.config import settings
from backend.prediction_engine.model_features import MODEL_INPUT_COLUMNS
from backend.prediction_engine.models.lightgbm_model import LightGBMModel


logger = logging.getLogger(__name__)

_FEATURE_LABELS: dict[str, str] = {
    "momentum_10": "10-day momentum",
    "return_5d": "5-day return",
    "macd_hist": "MACD trend",
    "rsi_14": "RSI",
    "volume_spike": "Volume spike",
    "market_trend_20": "Market trend",
    "market_volatility_20": "Market volatility",
    "macro_stress_score": "Macro stress",
    "company_sentiment_30d": "Company news sentiment",
    "company_event_score_30d": "Company event score",
    "company_event_intensity": "Company event intensity",
    "news_domestic_sentiment_30d": "Domestic macro sentiment",
    "news_global_sentiment_30d": "Global news sentiment",
    "news_geopolitical_risk_30d": "Geopolitical risk",
    "breadth_up_ratio": "Market breadth",
    "excess_return_5d": "Relative strength",
    "rolling_beta_20": "Market beta",
}


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

            artifact_path = settings.model_artifacts_path / version
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
            from backend.prediction_engine.feature_store.feature_store import get_features_for_inference

            feat_dict = get_features_for_inference(ticker)
            X = pd.DataFrame([{c: feat_dict[c] for c in MODEL_INPUT_COLUMNS}])
            results = self._model.predict_with_expected_return(
                X,
                price=float(feat_dict.get("close", 0.0) or 0.0),
                quantity=1,
            )
            r = results[0]
            explanation = self._build_prediction_explanation(ticker, feat_dict, r)
            return {
                "action": r["action"],
                "confidence": r["confidence"],
                "expected_return": r["expected_return"],
                "net_expected_return": r.get("net_expected_return", r["expected_return"]),
                "model_version": self._model_version,
                "calibration_score": r.get("calibration_score"),
                "signal_policy": r.get("signal_policy"),
                "explanation": explanation,
                "shap_top_features": [driver["label"] for driver in explanation["drivers"]],
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
        explanation = self._fallback_explanation(ticker, action, confidence, expected_return)
        return {
            "action": action,
            "confidence": confidence,
            "expected_return": expected_return,
            "model_version": "demo-fallback",
            "calibration_score": None,
            "signal_policy": {
                "buy_threshold": 0.58,
                "sell_threshold": 0.42,
                "min_signal_confidence": 0.55,
            },
            "explanation": explanation,
            "shap_top_features": [driver["label"] for driver in explanation["drivers"]],
            "fallback": True,
            "close": close,
        }

    def _build_prediction_explanation(self, ticker: str, feat_dict: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        action = str(result.get("action", "hold"))
        confidence = float(result.get("confidence", 0.0))
        expected_return = float(result.get("expected_return", 0.0))
        policy = result.get("signal_policy") or {}
        drivers = self._top_drivers(feat_dict)
        market_regime = self._market_regime(feat_dict)
        news_regime = self._news_regime(feat_dict)
        risk_flags = self._risk_flags(action, feat_dict, confidence, policy)
        confidence_band = self._confidence_band(confidence)
        summary = self._build_summary(
            ticker=ticker,
            action=action,
            confidence_band=confidence_band,
            expected_return=expected_return,
            market_regime=market_regime,
            news_regime=news_regime,
        )
        return {
            "summary": summary,
            "confidence_band": confidence_band,
            "market_regime": market_regime,
            "news_regime": news_regime,
            "decision_gate": self._decision_gate(action, confidence, policy),
            "drivers": drivers,
            "risk_flags": risk_flags,
            "thresholds": {
                "buy_threshold": self._safe_float(policy.get("buy_threshold")),
                "sell_threshold": self._safe_float(policy.get("sell_threshold")),
                "min_signal_confidence": self._safe_float(policy.get("min_signal_confidence")),
                "confidence_gap": self._confidence_gap(action, confidence, policy),
                "edge_score": round(abs(confidence - 0.5) * 2, 4),
            },
        }

    def _fallback_explanation(
        self,
        ticker: str,
        action: str,
        confidence: float,
        expected_return: float,
    ) -> dict[str, Any]:
        confidence_band = self._confidence_band(confidence)
        return {
            "summary": (
                f"{ticker} is using demo fallback mode, so this {action} signal is synthetic and meant for UI safety checks."
            ),
            "confidence_band": confidence_band,
            "market_regime": "Demo mode",
            "news_regime": "No live explanation data",
            "decision_gate": "Fallback mode bypassed the live model thresholds.",
            "drivers": [
                {
                    "feature": "demo_fallback",
                    "label": "Demo fallback",
                    "value": round(expected_return, 4),
                    "direction": "neutral",
                    "insight": "This response is generated without a trained model artifact.",
                }
            ],
            "risk_flags": ["Train and load a live model to see real feature-based explanations."],
            "thresholds": {
                "buy_threshold": 0.58,
                "sell_threshold": 0.42,
                "min_signal_confidence": 0.55,
                "confidence_gap": round(confidence - 0.55, 4),
                "edge_score": round(abs(confidence - 0.5) * 2, 4),
            },
        }

    def _top_drivers(self, feat_dict: dict[str, Any]) -> list[dict[str, Any]]:
        scored: list[tuple[float, str, float]] = []
        for feature, label in _FEATURE_LABELS.items():
            value = self._safe_float(feat_dict.get(feature))
            if value is None:
                continue
            scored.append((abs(value), feature, value))
        scored.sort(reverse=True)

        drivers: list[dict[str, Any]] = []
        for _, feature, value in scored[:4]:
            drivers.append(
                {
                    "feature": feature,
                    "label": _FEATURE_LABELS.get(feature, feature.replace("_", " ").title()),
                    "value": round(value, 4),
                    "direction": self._driver_direction(feature, value),
                    "insight": self._driver_insight(feature, value),
                }
            )
        return drivers

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if result != result:  # NaN
            return None
        return result

    def _driver_direction(self, feature: str, value: float) -> str:
        bearish_positive = {"news_geopolitical_risk_30d", "market_volatility_20", "macro_stress_score", "rolling_beta_20"}
        if feature in bearish_positive:
            return "bearish" if value > 0 else "bullish"
        if value > 0.1:
            return "bullish"
        if value < -0.1:
            return "bearish"
        return "neutral"

    def _driver_insight(self, feature: str, value: float) -> str:
        label = _FEATURE_LABELS.get(feature, feature.replace("_", " "))
        direction = self._driver_direction(feature, value)
        if direction == "bullish":
            return f"{label} is supportive of upside risk-taking right now."
        if direction == "bearish":
            return f"{label} is acting as a headwind for this setup."
        return f"{label} is close to neutral and not dominating the decision."

    def _market_regime(self, feat_dict: dict[str, Any]) -> str:
        trend = self._safe_float(feat_dict.get("market_trend_20")) or 0.0
        vol = self._safe_float(feat_dict.get("market_volatility_20")) or 0.0
        stress = self._safe_float(feat_dict.get("macro_stress_score")) or 0.0
        if stress > 0.9 or vol > 1.0:
            return "Risk-off / volatile"
        if trend > 0.35 and vol < 0.75:
            return "Uptrend / stable"
        if trend < -0.35:
            return "Downtrend / defensive"
        return "Mixed / range-bound"

    def _news_regime(self, feat_dict: dict[str, Any]) -> str:
        company = self._safe_float(feat_dict.get("company_sentiment_30d")) or 0.0
        macro = self._safe_float(feat_dict.get("news_domestic_sentiment_30d")) or 0.0
        geo = self._safe_float(feat_dict.get("news_geopolitical_risk_30d")) or 0.0
        if geo > 0.5:
            return "Geopolitical risk is elevated"
        if company > 0.35 and macro > 0:
            return "Company and macro news are constructive"
        if company < -0.35 or macro < -0.2:
            return "News flow is cautious to negative"
        return "News flow is mixed"

    def _risk_flags(
        self,
        action: str,
        feat_dict: dict[str, Any],
        confidence: float,
        policy: dict[str, Any],
    ) -> list[str]:
        flags: list[str] = []
        threshold_gap = self._confidence_gap(action, confidence, policy)
        if threshold_gap is not None and threshold_gap < 0.05:
            flags.append("Confidence is only slightly above the decision gate.")
        if (self._safe_float(feat_dict.get("macro_stress_score")) or 0.0) > 0.9:
            flags.append("Macro stress is elevated, so the setup may be fragile.")
        if (self._safe_float(feat_dict.get("news_geopolitical_risk_30d")) or 0.0) > 0.5:
            flags.append("Geopolitical news risk is high.")
        if (self._safe_float(feat_dict.get("company_event_intensity")) or 0.0) > 1.2:
            flags.append("Company-specific event flow is unusually strong and can increase volatility.")
        if action == "buy" and (self._safe_float(feat_dict.get("company_sentiment_30d")) or 0.0) < 0:
            flags.append("The buy signal is fighting negative company news tone.")
        if action == "sell" and (self._safe_float(feat_dict.get("company_sentiment_30d")) or 0.0) > 0.2:
            flags.append("The sell signal is fighting positive company news tone.")
        return flags

    def _build_summary(
        self,
        *,
        ticker: str,
        action: str,
        confidence_band: str,
        expected_return: float,
        market_regime: str,
        news_regime: str,
    ) -> str:
        if action == "buy":
            return (
                f"{ticker} is a {confidence_band.lower()}-confidence buy setup with an expected move of "
                f"{expected_return * 100:.2f}% in a {market_regime.lower()} regime. {news_regime}."
            )
        if action == "sell":
            return (
                f"{ticker} is a {confidence_band.lower()}-confidence sell setup with an expected move of "
                f"{expected_return * 100:.2f}% in a {market_regime.lower()} regime. {news_regime}."
            )
        return (
            f"{ticker} is staying on hold because the edge is not strong enough for action in a "
            f"{market_regime.lower()} regime. {news_regime}."
        )

    def _decision_gate(self, action: str, confidence: float, policy: dict[str, Any]) -> str:
        buy_threshold = self._safe_float(policy.get("buy_threshold"))
        sell_threshold = self._safe_float(policy.get("sell_threshold"))
        min_confidence = self._safe_float(policy.get("min_signal_confidence"))
        if action == "buy":
            return (
                f"Confidence {confidence * 100:.1f}% cleared the buy threshold "
                f"{(buy_threshold or 0) * 100:.1f}% and the confidence gate {(min_confidence or 0) * 100:.1f}%."
            )
        if action == "sell":
            return (
                f"Confidence {confidence * 100:.1f}% cleared the sell threshold "
                f"{(sell_threshold or 0) * 100:.1f}% and the confidence gate {(min_confidence or 0) * 100:.1f}%."
            )
        return (
            f"Confidence {confidence * 100:.1f}% did not create enough edge beyond the buy/sell gates, so the model stayed on hold."
        )

    def _confidence_gap(self, action: str, confidence: float, policy: dict[str, Any]) -> float | None:
        min_confidence = self._safe_float(policy.get("min_signal_confidence"))
        if min_confidence is None:
            return None
        return round(confidence - min_confidence, 4)

    @staticmethod
    def _confidence_band(confidence: float) -> str:
        if confidence >= 0.78:
            return "High"
        if confidence >= 0.65:
            return "Moderate"
        return "Cautious"
