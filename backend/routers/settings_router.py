"""内容限制开关接口。"""
from __future__ import annotations

from fastapi import APIRouter, Body

import database

router = APIRouter()

CONTENT_RESTRICTION_KEY = "content_restriction"


def content_restriction_enabled() -> bool:
    """读取内容限制开关状态。"""
    return database.get_setting(CONTENT_RESTRICTION_KEY, "false") == "true"


@router.get("/api/settings/content-restriction")
def get_content_restriction() -> dict:
    """返回当前内容限制状态。"""
    return {"enabled": content_restriction_enabled()}


@router.post("/api/settings/content-restriction")
def set_content_restriction(payload: dict = Body(...)) -> dict:
    """开启或关闭内容限制。"""
    enabled = bool(payload.get("enabled", False))
    database.set_setting(CONTENT_RESTRICTION_KEY, "true" if enabled else "false")
    return {"enabled": enabled}
