from __future__ import annotations

from fastapi import APIRouter, Request

from ..services.sync_service import get_sync_status

router = APIRouter(tags=["sync"])


@router.get("/api/sync/status")
def sync_status(request: Request):
    return get_sync_status(request.app.state.repo_path)
