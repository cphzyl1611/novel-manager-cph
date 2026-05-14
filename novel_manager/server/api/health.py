from __future__ import annotations

from fastapi import APIRouter, Request

from ..config import APP_NAME, APP_VERSION
from ..services.health_service import get_health_summary, list_health_issues

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health():
    return {"ok": True, "app": APP_NAME, "mode": "server", "repo_path": "", "version": APP_VERSION}


@router.get("/api/health/summary")
def health_summary(request: Request):
    """Get repository health summary."""
    repo_path = request.app.state.repo_path
    return get_health_summary(repo_path)


@router.get("/api/health/issues")
def health_issues(request: Request):
    """List detailed health issues."""
    repo_path = request.app.state.repo_path
    return list_health_issues(repo_path)
