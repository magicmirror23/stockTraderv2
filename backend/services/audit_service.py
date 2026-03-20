"""Shared audit logging helpers.

This module keeps audit persistence out of routers and trading loops so that
production hardening can happen in one place without changing every caller.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.db.models import AuditLog
from backend.db.session import SessionLocal


logger = logging.getLogger(__name__)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def record_audit_event(
    event: str,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    data: dict[str, Any] | None = None,
    actor: str | None = None,
    source: str | None = None,
    request_id: str | None = None,
    db: Session | None = None,
    raise_on_error: bool = False,
) -> bool:
    """Persist a structured audit event.

    When a session is supplied the caller owns commit/rollback. Otherwise this
    helper opens a short-lived session and commits immediately.
    """

    payload = dict(data or {})
    if actor:
        payload.setdefault("actor", actor)
    if source:
        payload.setdefault("source", source)
    if request_id:
        payload.setdefault("request_id", request_id)

    owns_session = db is None
    session = db or SessionLocal()
    try:
        session.add(
            AuditLog(
                event=event,
                entity_type=entity_type,
                entity_id=entity_id,
                data=json.dumps(payload, default=_json_default),
            )
        )
        if owns_session:
            session.commit()
        logger.info(
            "Audit event recorded",
            extra={
                "audit_event": event,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "source": source,
                "request_id": request_id,
            },
        )
        return True
    except Exception:
        if owns_session:
            session.rollback()
        logger.exception("Failed to record audit event %s", event)
        if raise_on_error:
            raise
        return False
    finally:
        if owns_session:
            session.close()
