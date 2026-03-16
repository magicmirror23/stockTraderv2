"""FastAPI dependency injection helpers.

Provides reusable dependencies for routers:
- Database sessions
- Authentication
- Service access
"""

from __future__ import annotations

from typing import Generator

from fastapi import Depends, Header, HTTPException

from backend.db.session import SessionLocal


def get_db() -> Generator:
    """Yield a SQLAlchemy session, auto-closing on completion."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_auth(authorization: str = Header(default="")) -> str:
    """Validate Bearer token from Authorization header.

    Returns the token string on success; raises 401 otherwise.
    """
    from backend.core.config import settings

    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = authorization.removeprefix("Bearer ").strip()
    if settings.SECRET_KEY and token != settings.SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid token")
    return token
