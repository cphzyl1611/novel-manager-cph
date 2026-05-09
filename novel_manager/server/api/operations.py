from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from ..services.operation_service import get_operation, list_operations, restore_operation

router = APIRouter(tags=["operations"])


@router.get("/api/operations")
def api_list(request: Request, limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), type: str = Query(default=""), reversible: bool | None = Query(default=None), restored: bool | None = Query(default=None)):
    return list_operations(request.app.state.repo_path, limit=limit, offset=offset, op_type=type, reversible=reversible, restored=restored)


@router.get("/api/operations/{operation_id}")
def api_get(operation_id: str, request: Request):
    r = get_operation(request.app.state.repo_path, operation_id)
    if r is None:
        raise HTTPException(status_code=404, detail="操作记录不存在")
    return r


@router.post("/api/operations/{operation_id}/restore")
def api_restore(operation_id: str, request: Request):
    r = restore_operation(request.app.state.repo_path, operation_id)
    if not r["ok"]:
        raise HTTPException(status_code=400, detail=r["error"])
    return r
