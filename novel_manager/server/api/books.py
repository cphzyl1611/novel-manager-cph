from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from ..services.book_service import get_book_chapters, get_book_content, get_book_detail, list_books
from ..services.progress_service import get_progress, save_progress
from ..services.upload_service import analyze_incoming, save_upload, scan_incoming


class ProgressInput(BaseModel):
    progress_ratio: float = Field(default=0, ge=0, le=1)
    scroll_position: int = Field(default=0, ge=0)
    device_id: str = "web"
    current_chapter_index: int = Field(default=0, ge=0)

router = APIRouter(tags=["books"])


@router.get("/api/books")
def books_list(
    request: Request,
    q: str = Query(default=""),
    area: str = Query(default="all"),
    limit: int = Query(default=60, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="updated_at"),
    include_removed: bool = Query(default=False),
):
    return list_books(request.app.state.repo_path, q=q, area=area, limit=limit, offset=offset, sort=sort, include_removed=include_removed)


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
        current_chapter_index=body.current_chapter_index,
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/api/books/{book_id}/chapters")
def books_chapters(book_id: int, request: Request):
    chapters = get_book_chapters(request.app.state.repo_path, book_id)
    if chapters is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return chapters


@router.post("/api/books/upload")
async def books_upload(request: Request, files: list[UploadFile] = File(...)):
    repo = request.app.state.repo_path
    uploaded = []
    skipped = []
    for f in files:
        content = await f.read()
        result = save_upload(repo, f.filename or "unknown.txt", content)
        if result["status"] == "success":
            uploaded.append(result)
        else:
            skipped.append(result)
    return {"uploaded": uploaded, "skipped": skipped, "count": len(uploaded)}


@router.post("/api/tasks/scan-incoming")
def tasks_scan_incoming(request: Request):
    return scan_incoming(request.app.state.repo_path)


@router.post("/api/tasks/analyze-incoming")
def tasks_analyze_incoming(request: Request):
    return analyze_incoming(request.app.state.repo_path)
