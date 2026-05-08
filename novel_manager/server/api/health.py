from __future__ import annotations

from fastapi import APIRouter

from ..config import APP_NAME, APP_VERSION

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health():
    return {"ok": True, "app": APP_NAME, "mode": "server", "repo_path": "", "version": APP_VERSION}
