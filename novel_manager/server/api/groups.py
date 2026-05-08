from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..services.group_service import create_group, list_groups

router = APIRouter(tags=["groups"])


class CreateGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


@router.get("/api/groups")
def groups_list(request: Request):
    return list_groups(request.app.state.repo_path)


@router.post("/api/groups")
def groups_create(body: CreateGroupRequest, request: Request):
    result = create_group(request.app.state.repo_path, body.name)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "创建失败"))
    return result
