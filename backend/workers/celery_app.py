"""Optional Celery bootstrap for upgraded deployments."""

from __future__ import annotations

import logging

from backend.core.config import settings


logger = logging.getLogger(__name__)

celery_app = None
celery_enabled = False

if settings.CELERY_BROKER_URL and settings.CELERY_RESULT_BACKEND:
    try:
        from celery import Celery

        celery_app = Celery(
            "stocktrader",
            broker=settings.CELERY_BROKER_URL,
            backend=settings.CELERY_RESULT_BACKEND,
        )
        celery_app.conf.update(
            timezone="UTC",
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            task_track_started=True,
        )
        celery_app.autodiscover_tasks(["backend.workers"])
        celery_enabled = True
        logger.info("Celery enabled for async tasks")
    except ImportError:
        logger.info("Celery package not installed; synchronous fallback will be used")
else:
    logger.info("Celery broker/backend not configured; synchronous fallback will be used")
