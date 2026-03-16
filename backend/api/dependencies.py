"""FastAPI dependency providers."""

from __future__ import annotations

from functools import lru_cache

from backend.core.config import Settings, get_settings
from backend.services.model_manager import ModelManager
from backend.services.price_feed import PriceFeed


def get_app_settings() -> Settings:
    return get_settings()


@lru_cache
def get_model_manager() -> ModelManager:
    return ModelManager()


@lru_cache
def get_price_feed() -> PriceFeed:
    return PriceFeed()
