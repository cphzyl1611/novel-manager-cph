"""Mobile API endpoints for native Android reader."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..services.mobile_service import (
    get_mobile_books,
    get_mobile_chapters,
    get_mobile_chapter_content,
    save_mobile_progress,
)

router = APIRouter(prefix="/api/mobile", tags=["mobile"])


class MobileProgressInput(BaseModel):
    book_id: int
    chapter_index: int = Field(default=0, ge=0)
    chapter_scroll: float = Field(default=0, ge=0, le=1)
    progress_ratio: float = Field(default=0, ge=0, le=1)
    scroll_position: int = Field(default=0, ge=0)
    device_id: str = "android"


@router.get("/books")
def mobile_books(request: Request):
    return get_mobile_books(request.app.state.repo_path)


@router.get("/books/{book_id}/chapters")
def mobile_chapters(book_id: int, request: Request):
    result = get_mobile_chapters(request.app.state.repo_path, book_id)
    if result is None: raise HTTPException(status_code=404, detail="Book not found")
    return result


@router.get("/books/{book_id}/chapters/{chapter_index}")
def mobile_chapter_content(book_id: int, chapter_index: int, request: Request):
    result = get_mobile_chapter_content(request.app.state.repo_path, book_id, chapter_index)
    if result is None: raise HTTPException(status_code=404, detail="Chapter not found")
    return result


@router.post("/progress")
def mobile_save_progress(body: MobileProgressInput, request: Request):
    return save_mobile_progress(request.app.state.repo_path, body.model_dump())
