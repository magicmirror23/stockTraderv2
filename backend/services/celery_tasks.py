"""Celery tasks — backwards-compatibility shim.

All task logic has moved to ``backend.workers.tasks``.
This module re-exports the public API so existing imports keep working.
"""

from backend.workers.tasks import run_retrain  # noqa: F401
from backend.workers.celery_app import celery_app as app  # noqa: F401

_CELERY_AVAILABLE = app is not None

# Re-export the Celery task if available
if _CELERY_AVAILABLE:
    from backend.workers.tasks import retrain_nightly  # noqa: F401

# Legacy alias
_run_retrain = run_retrain
