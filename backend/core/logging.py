"""Structured logging suitable for Render log streams."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from backend.core.config import settings
from backend.core.middleware import get_request_id


class JsonFormatter(logging.Formatter):
    """Render-friendly JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key in ("path", "method", "status_code", "duration_ms", "mode"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=True)


def setup_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_stocktrader_logging_configured", False):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    root._stocktrader_logging_configured = True  # type: ignore[attr-defined]
