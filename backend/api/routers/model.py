"""Model management endpoints: GET /model/status and POST /model/reload."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.api.schemas import (
    ModelMetadataResponse,
    ModelReloadRequest,
    ModelReloadResponse,
    ModelStatusResponse,
)
from backend.services.model_manager import ModelManager

router = APIRouter(prefix="/model", tags=["model"])


@router.get("/status", response_model=ModelStatusResponse)
async def model_status():
    mgr = ModelManager()
    info = mgr.get_model_info()
    return ModelStatusResponse(
        model_version=info["model_version"],
        status=info["status"],
        last_trained=info.get("last_trained"),
        accuracy=info.get("accuracy"),
        fallback=bool(info.get("fallback")),
        last_error=info.get("last_error"),
    )


@router.get("/metadata", response_model=ModelMetadataResponse)
async def model_metadata():
    mgr = ModelManager()
    info = mgr.get_model_metadata()
    return ModelMetadataResponse(**info)


@router.post("/reload", response_model=ModelReloadResponse)
async def model_reload(req: ModelReloadRequest | None = None):
    mgr = ModelManager()
    try:
        if req and req.version:
            new_version = mgr.load_version(req.version)
        else:
            new_version = mgr.load_latest()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return ModelReloadResponse(
        message="Model reload initiated.",
        new_version=new_version,
        status=mgr.status,
    )
