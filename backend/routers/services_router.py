"""Ollama / ComfyUI 服务启停接口。"""
from __future__ import annotations

from fastapi import APIRouter, Body

import services

router = APIRouter()


@router.get("/api/services")
def service_status() -> dict:
    """返回两个服务的运行状态。"""
    return services.status()


@router.post("/api/services/start")
def service_start(payload: dict = Body(...)):
    """启动指定服务。"""
    ok, message = services.start(str(payload.get("name") or ""))
    return {"ok": ok, "message": message, "services": services.status()}


@router.post("/api/services/stop")
def service_stop(payload: dict = Body(...)):
    """停止指定服务。"""
    ok, message = services.stop(str(payload.get("name") or ""))
    return {"ok": ok, "message": message, "services": services.status()}
