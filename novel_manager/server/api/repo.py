from __future__ import annotations

from fastapi import APIRouter, Request

from ..services.repo_service import get_repo_status

router = APIRouter(tags=["repo"])


@router.get("/api/repo/status")
def repo_status(request: Request):
    return get_repo_status(request.app.state.repo_path)
