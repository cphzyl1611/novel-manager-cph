from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..services.book_service import get_book_content, get_book_detail, list_books

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
