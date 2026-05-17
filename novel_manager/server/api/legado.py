"""Legado BookSource API endpoints."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query, Request
from ..services.legado_service import book_info, build_source_json, get_content, get_toc, search_books

router = APIRouter(prefix="/api/legado", tags=["legado"])

@router.get("/source")
def legado_source(request: Request):
    host = request.client.host if request.client else "localhost:8765"
    return build_source_json(host)

@router.post("/search")
def legado_search(request: Request, key: str = Query(default=""), page: int = Query(default=1, ge=1)):
    return search_books(request.app.state.repo_path, key=key, page=page)

@router.get("/book/{book_id}")
def legado_book_info(request: Request, book_id: int):
    r = book_info(request.app.state.repo_path, book_id)
    if r is None: raise HTTPException(status_code=404, detail="Book not found")
    return r

@router.get("/book/{book_id}/chapters")
def legado_toc(request: Request, book_id: int):
    r = get_toc(request.app.state.repo_path, book_id)
    if r is None: raise HTTPException(status_code=404, detail="Book not found")
    return r

@router.get("/book/{book_id}/chapter/{chapter_index}")
def legado_content(request: Request, book_id: int, chapter_index: int):
    r = get_content(request.app.state.repo_path, book_id, chapter_index)
    if r is None: raise HTTPException(status_code=404, detail="Chapter not found")
    return r
