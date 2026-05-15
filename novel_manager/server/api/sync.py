from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..services.sync_service import (
    get_sync_manifest,
    get_sync_snapshot,
    get_sync_changes,
    sync_upload_progress,
    sync_download_progress,
    get_sync_status,
)

router = APIRouter(tags=["sync"])


class ProgressUploadRequest(BaseModel):
    device_id: str
    progress: list[dict]


@router.get("/api/sync/status")
def sync_status(request: Request):
    """Legacy sync status endpoint for backward compatibility."""
    return get_sync_status(request.app.state.repo_path)


@router.get("/api/sync/manifest")
def sync_manifest(request: Request):
    """Get sync manifest with repo metadata.

    Returns repo_id, server_revision, server_device_id, and library stats.
    Mobile clients should call this first to identify the repository.
    """
    return get_sync_manifest(request.app.state.repo_path)


@router.get("/api/sync/snapshot")
def sync_snapshot(request: Request, include_chapters: bool = False):
    """Get full library snapshot.

    Returns manifest + all books (and optionally chapters) for initial sync.
    Use when client has no local cache or needs full refresh.
    """
    return get_sync_snapshot(request.app.state.repo_path, include_chapters)


@router.get("/api/sync/changes")
def sync_changes(request: Request, since: int = 0):
    """Get incremental changes since a revision.

    Mobile clients call this with their last_synced_revision to get
    only the changes they need, minimizing bandwidth.
    """
    return get_sync_changes(request.app.state.repo_path, since)


@router.post("/api/sync/progress")
def sync_progress(request: Request, body: ProgressUploadRequest):
    """Upload reading progress from mobile device.

    Accepts a list of progress records from a device.
    Progress is stored per (book_id, device_id) combination.
    Computer remains authoritative - this just syncs reading state.
    """
    return sync_upload_progress(
        request.app.state.repo_path,
        body.device_id,
        body.progress,
    )


@router.get("/api/sync/progress")
def sync_progress_download(request: Request, device_id: str):
    """Download reading progress for a device.

    Returns all progress records for the specified device_id.
    Mobile clients use this to restore their reading state.
    """
    return sync_download_progress(request.app.state.repo_path, device_id)