"""Tests for core configuration and exceptions."""

import os

from backend.core.config import settings
from backend.core.exceptions import AppError, NotFoundError, AuthenticationError


def test_settings_defaults():
    """Settings should have sane defaults for development."""
    assert settings.API_V1_PREFIX == "/api/v1"
    assert settings.PAPER_MODE is True or settings.PAPER_MODE == "true"


def test_settings_allowed_origins():
    origins = settings.allowed_origins_list
    assert isinstance(origins, list)
    assert len(origins) >= 1


def test_app_error_hierarchy():
    err = AppError("test")
    assert err.status_code == 500
    assert str(err) == "test"


def test_not_found_error():
    err = NotFoundError("missing")
    assert err.status_code == 404


def test_auth_error():
    err = AuthenticationError()
    assert err.status_code == 401
