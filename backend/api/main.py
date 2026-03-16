"""FastAPI application entrypoint for Render deployment."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.dependencies import get_model_manager, get_price_feed
from backend.api.routers import admin, backtest, health, market, model, paper, predict, stream, trade
from backend.core.config import settings
from backend.core.exceptions import register_exception_handlers
from backend.core.logging import setup_logging
from backend.core.middleware import RequestLoggingMiddleware


setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_runtime_directories()
    logger.info("Application startup", extra={"mode": settings.run_mode})
    logger.info(
        "Runtime storage ready: storage=%s registry=%s artifacts=%s persistent=%s",
        settings.storage_path,
        settings.model_registry_path,
        settings.model_artifacts_path,
        settings.persistence_enabled,
        extra={"mode": settings.run_mode},
    )
    model_manager = get_model_manager()
    price_feed = get_price_feed()
    model_manager.ensure_loaded()
    feed_status = price_feed.warm()

    app.state.model_manager = model_manager
    app.state.price_feed = price_feed
    logger.info("Startup complete", extra={"mode": feed_status["mode"]})
    yield
    logger.info("Application shutdown", extra={"mode": settings.run_mode})


app = FastAPI(
    title="StockTrader API",
    version="2.0.0",
    description="Render-ready stock and options prediction backend",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

register_exception_handlers(app)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (health, predict, model, backtest, trade, admin, paper, stream, market):
    app.include_router(router.router, prefix=settings.API_V1_PREFIX)


@app.get("/")
async def root():
    feed = get_price_feed().feed_status
    model_info = get_model_manager().get_model_info()
    return {
        "status": "ok",
        "service": "StockTrader API",
        "environment": settings.APP_ENV,
        "mode": settings.run_mode,
        "paper_mode": settings.PAPER_MODE,
        "feed_mode": feed["mode"],
        "model_status": model_info["status"],
        "version": app.version,
    }


_STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
if _STATIC_DIR.is_dir() and (_STATIC_DIR / "index.html").exists():
    if (_STATIC_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")

    @app.get("/app/{full_path:path}")
    async def serve_spa(full_path: str):
        candidate = _STATIC_DIR / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_STATIC_DIR / "index.html")
