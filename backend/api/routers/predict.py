"""Prediction endpoints with graceful demo fallback."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from backend.api.dependencies import get_model_manager
from backend.api.schemas import (
    ActionEnum,
    BatchPredictRequest,
    BatchPredictResponse,
    Greeks,
    OptionPredictRequest,
    OptionPredictResponse,
    OptionSignal,
    PredictRequest,
    PredictResponse,
    PredictionEntry,
)


router = APIRouter(tags=["prediction"])


def _coerce_action(value: str) -> ActionEnum:
    return ActionEnum(value if value in ActionEnum._value2member_map_ else "hold")


def _prediction_entry(ticker: str, result: dict, now: datetime) -> PredictionEntry:
    return PredictionEntry(
        ticker=ticker,
        action=_coerce_action(result["action"]),
        confidence=result["confidence"],
        expected_return=result["expected_return"],
        model_version=result["model_version"],
        calibration_score=result.get("calibration_score"),
        shap_top_features=["demo_fallback"] if result.get("fallback") else None,
        timestamp=now,
    )


@router.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    now = datetime.now(timezone.utc)
    result = get_model_manager().predict(req.ticker, req.horizon_days)
    predicted_price = round(result["close"] * (1 + result["expected_return"]), 2)
    entry = _prediction_entry(req.ticker, result, now)
    return PredictResponse(
        ticker=req.ticker,
        horizon_days=req.horizon_days,
        predicted_price=predicted_price,
        confidence=result["confidence"],
        model_version=result["model_version"],
        timestamp=now,
        prediction=entry,
    )


@router.post("/predict/options", response_model=OptionPredictResponse)
async def predict_options(req: OptionPredictRequest):
    now = datetime.now(timezone.utc)
    result = get_model_manager().predict(req.underlying, req.horizon_days)
    spot = result["close"]
    vol = 0.25
    days_to_expiry = 30
    try:
        from backend.prediction_engine.feature_store.transforms import greeks_estimate

        greeks_dict = greeks_estimate(spot, req.strike, days_to_expiry, vol, option_type=req.option_type.value)
    except Exception:
        greeks_dict = {"delta": 0.5, "gamma": 0.02, "theta": -0.01, "vega": 0.12, "rho": 0.01, "iv": vol}

    signal = OptionSignal(
        underlying=req.underlying,
        strike=req.strike,
        expiry=req.expiry,
        option_type=req.option_type,
        action=_coerce_action(result["action"]),
        confidence=result["confidence"],
        expected_return=result["expected_return"],
        greeks=Greeks(**greeks_dict),
        model_version=result["model_version"],
        calibration_score=result.get("calibration_score"),
        shap_top_features=["demo_fallback"] if result.get("fallback") else None,
        timestamp=now,
    )
    return OptionPredictResponse(signal=signal, model_version=result["model_version"], timestamp=now)


@router.post("/batch_predict", response_model=BatchPredictResponse)
async def batch_predict(req: BatchPredictRequest):
    now = datetime.now(timezone.utc)
    manager = get_model_manager()
    predictions = [_prediction_entry(ticker, manager.predict(ticker, req.horizon_days), now) for ticker in req.tickers]
    return BatchPredictResponse(predictions=predictions, model_version=manager.model_version, timestamp=now)
