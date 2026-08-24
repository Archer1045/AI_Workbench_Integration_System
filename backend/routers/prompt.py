"""提示词 Agent 接口：图片反推与自然语言转提示词。"""
from __future__ import annotations

import base64
import time
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

import database
import content_filter
import prompt_agent
from routers.settings_router import content_restriction_enabled

router = APIRouter()

AI_PRODUCT_DIR = Path(r"D:\workSpace\code\骑手招聘助手\AIproduct")


@router.post("/api/prompt/from-text")
def from_text(payload: dict = Body(...)):
    """自然语言转英文绘画提示词，并记录行为。"""
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")
    if not prompt_agent.is_available():
        raise HTTPException(status_code=503, detail="Ollama 未启动")
    if content_filter.is_always_blocked(text):
        raise HTTPException(status_code=403, detail="该内容被禁止生成")
    if content_restriction_enabled() and content_filter.is_nsfw(text):
        raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")
    started_at = database.now_iso()
    started_ts = time.time()
    try:
        prompt = prompt_agent.text_to_prompt(text)
        if content_filter.is_always_blocked(prompt):
            raise HTTPException(status_code=403, detail="该内容被禁止生成")
        if content_restriction_enabled() and content_filter.is_nsfw(prompt):
            raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")
        database.insert_prompt_record(
            "text", text, None, None, prompt, prompt_agent.TEXT_MODEL, "success",
            started_at, database.now_iso(), round(time.time() - started_ts, 2),
        )
        return {"prompt": prompt, "source_text": text}
    except Exception as exc:  # noqa: BLE001
        database.insert_prompt_record(
            "text", text, None, None, None, prompt_agent.TEXT_MODEL, "error",
            started_at, database.now_iso(), round(time.time() - started_ts, 2),
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/prompt/from-image")
def from_image(payload: dict = Body(...)):
    """图片反推提示词：保存原图、识别描述、生成英文提示词，并记录行为。"""
    data = str(payload.get("image_base64") or "")
    filename = str(payload.get("filename") or "image.png")
    if "," in data:
        data = data.split(",", 1)[1]
    try:
        image_bytes = base64.b64decode(data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"图片编码无效: {exc}") from exc
    if not image_bytes:
        raise HTTPException(status_code=400, detail="图片为空")
    if not prompt_agent.is_available():
        raise HTTPException(status_code=503, detail="Ollama 未启动")

    # 上传图片保存到 prompt_inputs，方便后续追溯
    prompt_inputs = AI_PRODUCT_DIR / "prompt_inputs"
    prompt_inputs.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    saved_image = prompt_inputs / f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    saved_image.write_bytes(image_bytes)

    started_at = database.now_iso()
    started_ts = time.time()
    try:
        result = prompt_agent.image_to_prompt(image_bytes, filename)
        description = result.get("description") or ""
        prompt = result.get("prompt") or ""
        if content_filter.is_always_blocked(description) or content_filter.is_always_blocked(prompt):
            raise HTTPException(status_code=403, detail="该内容被禁止生成")
        if content_restriction_enabled() and (content_filter.is_nsfw(description) or content_filter.is_nsfw(prompt)):
            raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")
        database.insert_prompt_record(
            "image", None, str(saved_image), result.get("description"),
            result.get("prompt"), prompt_agent.VLM_MODEL, "success",
            started_at, database.now_iso(), round(time.time() - started_ts, 2),
        )
        return result
    except Exception as exc:  # noqa: BLE001
        database.insert_prompt_record(
            "image", None, str(saved_image), None, None, prompt_agent.VLM_MODEL, "error",
            started_at, database.now_iso(), round(time.time() - started_ts, 2),
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
