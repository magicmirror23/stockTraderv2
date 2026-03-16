"""Shared pytest fixtures for the StockTrader test suite."""

import os
import pytest
from fastapi.testclient import TestClient

# Force test environment before importing the app
os.environ.setdefault("APP_ENV", "testing")
os.environ.setdefault("PAPER_MODE", "true")
os.environ.setdefault("ENABLE_DEMO_MODE", "true")
os.environ.setdefault("ENABLE_REPLAY_FALLBACK", "true")
os.environ.setdefault("ENABLE_LIVE_BROKER", "false")

from backend.api.main import app  # noqa: E402


@pytest.fixture()
def client():
    """Return a TestClient bound to the FastAPI app."""
    return TestClient(app)


@pytest.fixture()
def auth_client():
    """Return a TestClient with a valid auth header."""
    from backend.core.config import settings

    return TestClient(
        app,
        headers={"Authorization": f"Bearer {settings.SECRET_KEY}"},
    )


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset singletons between tests to avoid state leaks."""
    from backend.services.model_manager import ModelManager
    from backend.services.price_feed import PriceFeed

    yield
    ModelManager._instance = None
    PriceFeed._instance = None
