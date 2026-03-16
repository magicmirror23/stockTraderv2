from backend.core.config import Settings


def test_settings_support_demo_mode_defaults():
    settings = Settings(
        APP_ENV="testing",
        SECRET_KEY="test-secret",
        ENABLE_DEMO_MODE=True,
        ENABLE_REPLAY_FALLBACK=True,
        ENABLE_LIVE_BROKER=False,
    )
    assert settings.demo_enabled is True
    assert settings.database_url.startswith("sqlite")
    assert settings.run_mode == "replay"


def test_settings_validate_production_secret():
    try:
        Settings(APP_ENV="production")
    except Exception as exc:
        assert "SECRET_KEY" in str(exc)
    else:
        raise AssertionError("production secret validation should fail")
