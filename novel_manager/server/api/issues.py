from __future__ import annotations

from fastapi import APIRouter, Request

from ..services.issue_service import get_issues

router = APIRouter(tags=["issues"])


@router.get("/api/issues")
def issues_list(request: Request):
    return get_issues(request.app.state.repo_path)
