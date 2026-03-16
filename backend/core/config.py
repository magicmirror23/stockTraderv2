"""Deployment-aware application configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORAGE_PATH = PROJECT_ROOT / "storage"
DEFAULT_MODEL_REGISTRY = PROJECT_ROOT / "models" / "registry.json"
DEFAULT_SQLITE_URL = f"sqlite:///{PROJECT_ROOT / 'stocktrader.db'}"


class Settings(BaseSettings):
    """Centralized runtime settings for local, Render, and test environments."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    APP_ENV: Literal["development", "testing", "staging", "production"] = "development"
    API_V1_PREFIX: str = "/api/v1"
    SECRET_KEY: str = "change-me-in-production"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str | None = None
    REDIS_URL: str | None = None
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None
    ALLOWED_ORIGINS: str = ""
    FRONTEND_URL: str | None = None

    PAPER_MODE: bool = True
    ENABLE_LIVE_BROKER: bool = False
    ENABLE_REPLAY_FALLBACK: bool = True
    ENABLE_DEMO_MODE: bool = True

    MLFLOW_TRACKING_URI: str | None = None
    SENTRY_DSN: str | None = None

    ANGEL_API_KEY: str | None = None
    ANGEL_CLIENT_ID: str | None = None
    ANGEL_CLIENT_PIN: str | None = Field(default=None, validation_alias="ANGEL_MPIN")
    ANGEL_TOTP_SECRET: str | None = None

    MODEL_REGISTRY_PATH: str = str(DEFAULT_MODEL_REGISTRY)
    STORAGE_PATH: str = str(DEFAULT_STORAGE_PATH)
    PERSISTENT_DATA_ROOT: str | None = None
    WATCHLIST_SYMBOLS: str = "RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK,NIFTY50"
    TRAINING_DATA_LOOKBACK_DAYS: int = 730
    TRAINING_DATA_MAX_AGE_DAYS: int = 3
    TRAINING_TICKERS_FILE: str = str(PROJECT_ROOT / "scripts" / "sample_data" / "tickers.txt")

    @field_validator("API_V1_PREFIX")
    @classmethod
    def _normalize_prefix(cls, value: str) -> str:
        value = value.strip() or "/api/v1"
        if not value.startswith("/"):
            value = f"/{value}"
        return value.rstrip("/") or "/api/v1"

    @field_validator("LOG_LEVEL")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def _validate_mode(self) -> "Settings":
        if self.APP_ENV == "production" and self.SECRET_KEY == "change-me-in-production":
            raise ValueError("SECRET_KEY must be set for production deployments")
        if self.ENABLE_LIVE_BROKER and not self.has_angel_credentials:
            if not self.ENABLE_REPLAY_FALLBACK and not self.ENABLE_DEMO_MODE:
                raise ValueError(
                    "ENABLE_LIVE_BROKER requires Angel credentials unless replay or demo mode is enabled"
                )
        return self

    @property
    def database_url(self) -> str:
        return self.DATABASE_URL or DEFAULT_SQLITE_URL

    @property
    def allowed_origins_list(self) -> list[str]:
        origins = [item.strip() for item in self.ALLOWED_ORIGINS.split(",") if item.strip()]
        if self.FRONTEND_URL:
            frontend = self.FRONTEND_URL.rstrip("/")
            if frontend not in origins:
                origins.append(frontend)
        if not origins:
            origins = ["*"] if self.APP_ENV != "production" else []
        return origins

    @property
    def has_angel_credentials(self) -> bool:
        return bool(
            self.ANGEL_API_KEY
            and self.ANGEL_CLIENT_ID
            and self.ANGEL_CLIENT_PIN
            and self.ANGEL_TOTP_SECRET
        )

    @property
    def live_broker_enabled(self) -> bool:
        return self.ENABLE_LIVE_BROKER and self.has_angel_credentials

    @property
    def replay_enabled(self) -> bool:
        return self.ENABLE_REPLAY_FALLBACK

    @property
    def demo_enabled(self) -> bool:
        return self.ENABLE_DEMO_MODE or self.PAPER_MODE

    @property
    def has_redis(self) -> bool:
        return bool(self.REDIS_URL or self.CELERY_BROKER_URL)

    @property
    def has_mlflow(self) -> bool:
        return bool(self.MLFLOW_TRACKING_URI)

    @property
    def model_registry_path(self) -> Path:
        return self._resolve_runtime_path(self.MODEL_REGISTRY_PATH)

    @property
    def storage_path(self) -> Path:
        return self._resolve_runtime_path(self.STORAGE_PATH)

    @property
    def raw_data_path(self) -> Path:
        return self.storage_path / "raw"

    @property
    def model_artifacts_path(self) -> Path:
        return self.model_registry_path.parent / "artifacts"

    @property
    def persistent_data_root(self) -> Path | None:
        if not self.PERSISTENT_DATA_ROOT:
            return None
        return Path(self.PERSISTENT_DATA_ROOT)

    @property
    def watchlist_symbols(self) -> list[str]:
        return [symbol.strip().upper() for symbol in self.WATCHLIST_SYMBOLS.split(",") if symbol.strip()]

    @property
    def training_tickers_file(self) -> Path:
        return Path(self.TRAINING_TICKERS_FILE)

    @property
    def persistence_enabled(self) -> bool:
        return self.persistent_data_root is not None

    @property
    def run_mode(self) -> str:
        if self.live_broker_enabled:
            return "live"
        if self.replay_enabled:
            return "replay"
        if self.demo_enabled:
            return "demo"
        return "unavailable"

    @property
    def service_mode(self) -> str:
        if self.PAPER_MODE:
            return "paper"
        return self.run_mode

    def ensure_runtime_directories(self) -> None:
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.raw_data_path.mkdir(parents=True, exist_ok=True)
        self.model_registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.model_artifacts_path.mkdir(parents=True, exist_ok=True)

    def _resolve_runtime_path(self, raw_value: str) -> Path:
        path = Path(raw_value)
        if path.is_absolute():
            return path
        if self.persistent_data_root is not None:
            return self.persistent_data_root / path
        return PROJECT_ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
