from __future__ import annotations

from fastapi import APIRouter, Request

from ..services.task_service import get_updates_summary

router = APIRouter(tags=["updates"])


@router.get("/api/updates/summary")
def updates_summary(request: Request):
    return get_updates_summary(request.app.state.repo_path)
