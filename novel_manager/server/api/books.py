from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..services.book_service import get_book_content, get_book_detail, list_books
from ..services.progress_service import get_progress, save_progress


class ProgressInput(BaseModel):
    progress_ratio: float = Field(default=0, ge=0, le=1)
    scroll_position: int = Field(default=0, ge=0)
    device_id: str = "web"

router = APIRouter(tags=["books"])


@router.get("/api/books")
def books_list(
    request: Request,
    q: str = Query(default=""),
    area: str = Query(default="all"),
    limit: int = Query(default=60, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="updated_at"),
):
    return list_books(request.app.state.repo_path, q=q, area=area, limit=limit, offset=offset, sort=sort)


@router.get("/api/books/{book_id}")
def books_detail(book_id: int, request: Request):
    detail = get_book_detail(request.app.state.repo_path, book_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return detail


@router.get("/api/books/{book_id}/content")
def books_content(book_id: int, request: Request):
    content = get_book_content(request.app.state.repo_path, book_id)
    if content is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return content


@router.get("/api/books/{book_id}/progress")
def read_progress(book_id: int, request: Request):
    p = get_progress(request.app.state.repo_path, book_id)
    if p is None:
        return {"book_id": book_id, "progress_ratio": 0, "scroll_position": 0, "has_progress": False}
    p["has_progress"] = True
    return p


@router.post("/api/books/{book_id}/progress")
def write_progress(book_id: int, body: ProgressInput, request: Request):
    result = save_progress(
        request.app.state.repo_path,
        book_id,
        progress_ratio=body.progress_ratio,
        scroll_position=body.scroll_position,
        device_id=body.device_id,
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
