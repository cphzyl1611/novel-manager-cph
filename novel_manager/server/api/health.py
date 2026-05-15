from __future__ import annotations

from fastapi import APIRouter, Request

from ..config import APP_NAME, APP_VERSION
from ..services.health_service import (
    get_health_summary,
    list_health_issues,
    mark_book_external_removed,
    unmark_book_external_removed,
)

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


@router.post("/api/health/books/{book_id}/mark-removed")
def mark_removed(request: Request, book_id: int):
    """Mark a book as externally removed by user."""
    repo_path = request.app.state.repo_path
    return mark_book_external_removed(repo_path, book_id)


@router.post("/api/health/books/{book_id}/unmark-removed")
def unmark_removed(request: Request, book_id: int):
    """Restore a book from external_removed to normal status."""
    repo_path = request.app.state.repo_path
    return unmark_book_external_removed(repo_path, book_id)
