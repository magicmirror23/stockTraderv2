"""Background job entrypoints with synchronous fallback."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.services.model_manager import ModelManager
from backend.services.monitoring import record_retrain
from backend.workers.celery_app import celery_app, celery_enabled


logger = logging.getLogger(__name__)


def run_retrain() -> dict:
    from backend.prediction_engine.training.trainer import train

    try:
        entry = train()
        ModelManager().load_latest()
        record_retrain("success")
        return {
            "status": "success",
            "model_version": entry.get("version", "unknown"),
            "metrics": entry.get("metrics", {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "execution_mode": "sync",
        }
    except Exception:
        record_retrain("failed")
        logger.exception("Retrain failed")
        raise


def dispatch_retrain() -> dict:
    if celery_enabled and celery_app:
        task = retrain_nightly.delay()
        return {"status": "queued", "task_id": task.id, "execution_mode": "celery"}
    return run_retrain()


if celery_enabled and celery_app:
    @celery_app.task(name="backend.workers.tasks.retrain_nightly", bind=True, max_retries=2)
    def retrain_nightly(self):
        try:
            result = run_retrain()
            result["execution_mode"] = "celery"
            return result
        except Exception as exc:
            raise self.retry(exc=exc, countdown=300)
