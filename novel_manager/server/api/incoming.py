from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..services.incoming_service import compare_books, import_to_library, move_to_review_duplicates

router = APIRouter(tags=["incoming"])


@router.post("/api/incoming/{book_id}/import-to-library")
def api_import(book_id: int, request: Request):
    r = import_to_library(request.app.state.repo_path, book_id)
    if not r["ok"]:
        raise HTTPException(status_code=400, detail=r["error"])
    return r


@router.post("/api/incoming/{book_id}/move-to-review-duplicates")
def api_move_review(book_id: int, request: Request):
    r = move_to_review_duplicates(request.app.state.repo_path, book_id)
    if not r["ok"]:
        raise HTTPException(status_code=400, detail=r["error"])
    return r


@router.get("/api/incoming/{book_id}/compare/{matched_book_id}")
def api_compare(book_id: int, matched_book_id: int, request: Request):
    r = compare_books(book_id, matched_book_id, request.app.state.repo_path)
    if not r.get("ok"):
        raise HTTPException(status_code=404, detail=r.get("error", "对比失败"))
    return r
