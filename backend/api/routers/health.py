"""Lightweight health and status endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.dependencies import get_model_manager, get_price_feed
from backend.core.config import settings


router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.get("/health/info")
async def health_info():
    model = get_model_manager().get_model_info()
    feed = get_price_feed().feed_status
    return {
        "status": "ok",
        "environment": settings.APP_ENV,
        "paper_mode": settings.PAPER_MODE,
        "demo_mode": settings.demo_enabled,
        "run_mode": settings.run_mode,
        "feed_mode": feed["mode"],
        "model_status": model["status"],
        "model_version": model["model_version"],
        "redis_enabled": settings.has_redis,
        "mlflow_enabled": settings.has_mlflow,
    }
