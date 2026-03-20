"""API exception handling and consistent error envelopes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.core.middleware import get_request_id


logger = logging.getLogger(__name__)


class AppError(Exception):
    """Project-level application exception with an HTTP status code."""

    status_code = 500
    code = "APP_ERROR"

    def __init__(self, message: str = "Application error", *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message)


class AuthenticationError(AppError):
    status_code = 401
    code = "AUTHENTICATION_ERROR"

    def __init__(self, message: str = "Authentication required"):
        super().__init__(message)


def _error_payload(code: str, message: str, request: Request, extras: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "detail": message,
        "code": code,
        "request_id": get_request_id(),
        "path": request.url.path,
    }
    if extras:
        payload.update(extras)
    return payload


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_exception_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(exc.code, str(exc), request),
        )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload("HTTP_ERROR", detail, request),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_payload("VALIDATION_ERROR", "Request validation failed", request, {"errors": exc.errors()}),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled application error")
        return JSONResponse(
            status_code=500,
            content=_error_payload("INTERNAL_SERVER_ERROR", "Internal server error", request),
        )
