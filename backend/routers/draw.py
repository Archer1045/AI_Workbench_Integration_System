"""AI 绘画接口：模型/LoRA 列表、图片访问、单张与批量绘画。"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

import content_filter
import database
from comfy_worker import DEFAULT_MODEL, generate, list_diffusion_models, list_loras
from routers.chat import translate_text
from routers.settings_router import content_restriction_enabled

router = APIRouter()

AI_PRODUCT_DIR = Path(r"D:\workSpace\code\骑手招聘助手\AIproduct")
DE_MOSAIC_TAGS = "mosaic_censored, bar_censor, text_censor, censored, censor, censor_bar, blur_censor, pixelated, mosaic, censorship"
MAX_GROUP_COUNT = 10
MAX_TOTAL_COUNT = 20

# 批量绘画任务缓存（内存）
BATCH_JOBS: dict[str, dict] = {}
BATCH_LOCK = threading.Lock()


def _prepare_prompts(prompt: str, negative_prompt: str) -> tuple[str, str]:
    """自动加入 uncensored 和无遮挡标签，并执行内容限制检查。"""
    prompt = prompt.strip()
    if "uncensored" not in prompt.lower():
        prompt = f"{prompt}, uncensored"
    if not all(tag in negative_prompt.lower() for tag in ("mosaic_censored", "bar_censor", "censored")):
        negative_prompt = f"{negative_prompt}, {DE_MOSAIC_TAGS}".strip(", ")
    if content_filter.is_always_blocked(prompt) or content_filter.is_always_blocked(negative_prompt):
        raise HTTPException(status_code=403, detail="该内容被禁止生成")
    if content_restriction_enabled() and (
        content_filter.is_nsfw(prompt) or content_filter.is_nsfw(negative_prompt)
    ):
        raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")
    return prompt, negative_prompt


def _generate_and_record(
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    model: str,
    loras: list[str],
    batch_id: str | None,
    group_index: int | None,
    image_index: int,
) -> dict:
    """生成一张图并写入数据库记录。"""
    prompt, negative_prompt = _prepare_prompts(prompt, negative_prompt)
    record_id = database.insert_draw_start(
        prompt,
        translate_text(prompt),
        negative_prompt,
        translate_text(negative_prompt),
        width,
        height,
        steps,
        cfg,
        model,
        batch_id=batch_id,
        group_index=group_index,
        lora_anima_turbo=any("anima-turbo" in str(name) for name in loras),
        lora_high_contrast=any("high-contrast" in str(name) for name in loras),
    )
    started = time.time()
    try:
        result = generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg=cfg,
            loras=loras,
            model_name=model,
        )
        duration = round(time.time() - started, 2)
        database.finish_draw(
            record_id,
            duration,
            result.get("saved_path"),
            result.get("image_url"),
            result.get("seed"),
            "success",
        )
        return {
            **result,
            "batch_id": batch_id,
            "group_index": group_index,
            "image_index": image_index,
        }
    except Exception as exc:  # noqa: BLE001
        database.finish_draw(
            record_id,
            round(time.time() - started, 2),
            None,
            None,
            None,
            "error",
            str(exc),
        )
        raise


def _run_batch(job_id: str, groups: list[dict], config: dict) -> None:
    """后台线程逐组生成图片并更新进度。"""
    results: list[dict] = []
    done = 0
    error: str | None = None
    try:
        for group_index, group in enumerate(groups):
            for image_index in range(group["count"]):
                result = _generate_and_record(
                    group["prompt"],
                    config["negative_prompt"],
                    config["width"],
                    config["height"],
                    config["steps"],
                    config["cfg"],
                    config["model"],
                    config["loras"],
                    job_id,
                    group_index,
                    image_index,
                )
                results.append(result)
                done += 1
                with BATCH_LOCK:
                    BATCH_JOBS[job_id]["done"] = done
                    BATCH_JOBS[job_id]["current_group"] = group_index
                    BATCH_JOBS[job_id]["results"] = results
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    with BATCH_LOCK:
        BATCH_JOBS[job_id]["status"] = "error" if error else "done"
        BATCH_JOBS[job_id]["error"] = error
        BATCH_JOBS[job_id]["finished_at"] = database.now_iso()
        BATCH_JOBS[job_id]["done"] = done
        BATCH_JOBS[job_id]["results"] = results


def _validate_model(model: str) -> str:
    """校验底模名称，返回可用模型名。"""
    model = str(model or DEFAULT_MODEL)
    available = {item["name"] for item in list_diffusion_models()}
    if model not in available:
        raise HTTPException(status_code=400, detail="未知的底模")
    return model


@router.get("/api/loras")
def get_loras() -> dict:
    """返回 ComfyUI LoRA 目录下的模型文件列表。"""
    return {"loras": list_loras()}


@router.get("/api/models")
def get_models() -> dict:
    """返回可选的绘画底模列表和默认底模。"""
    return {"models": list_diffusion_models(), "default": DEFAULT_MODEL}


@router.get("/api/images/{filename}")
def get_image(filename: str) -> Response:
    """从 AIproduct 目录提供生成的图片。"""
    safe_name = Path(filename).name
    path = AI_PRODUCT_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="image not found")
    return Response(path.read_bytes(), media_type="image/png")


@router.post("/api/draw/batch")
def draw_batch(payload: dict = Body(...)):
    """批量绘画：多组提示词，每组指定张数，后台执行并返回任务ID。"""
    model = _validate_model(payload.get("model"))
    groups_raw = payload.get("groups")
    if not groups_raw:
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt 不能为空")
        groups_raw = [{"prompt": prompt, "count": int(payload.get("count", 1))}]

    groups: list[dict] = []
    for group in groups_raw:
        prompt = str(group.get("prompt") or "").strip()
        count = int(group.get("count", 1))
        if not prompt:
            raise HTTPException(status_code=400, detail="提示词不能为空")
        if count < 1 or count > MAX_GROUP_COUNT:
            raise HTTPException(status_code=400, detail=f"每组最多 {MAX_GROUP_COUNT} 张")
        groups.append({"prompt": prompt, "count": count})

    total = sum(group["count"] for group in groups)
    if total > MAX_TOTAL_COUNT:
        raise HTTPException(status_code=400, detail=f"总张数最多 {MAX_TOTAL_COUNT} 张")

    config = {
        "negative_prompt": str(payload.get("negative_prompt") or ""),
        "width": int(payload.get("width", 1080)),
        "height": int(payload.get("height", 1920)),
        "steps": int(payload.get("steps", 18)),
        "cfg": float(payload.get("cfg", 1.0)),
        "model": model,
        "loras": payload.get("loras") or [],
    }

    job_id = uuid.uuid4().hex
    BATCH_JOBS[job_id] = {
        "batch_id": job_id,
        "status": "running",
        "total": total,
        "done": 0,
        "current_group": 0,
        "results": [],
        "error": None,
        "created_at": database.now_iso(),
        "finished_at": None,
    }
    threading.Thread(target=_run_batch, args=(job_id, groups, config), daemon=True).start()
    return {"batch_id": job_id, "total": total, "status": "running"}


@router.get("/api/draw/batch/{batch_id}")
def draw_batch_status(batch_id: str) -> dict:
    """查询批量绘画任务进度。"""
    job = BATCH_JOBS.get(batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="batch not found")
    return job


@router.post("/api/draw")
def draw(payload: dict = Body(...)):
    """兼容旧接口：单张绘画，同步返回结果。"""
    model = _validate_model(payload.get("model"))
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    result = _generate_and_record(
        prompt,
        str(payload.get("negative_prompt") or ""),
        int(payload.get("width", 1080)),
        int(payload.get("height", 1920)),
        int(payload.get("steps", 18)),
        float(payload.get("cfg", 1.0)),
        model,
        payload.get("loras") or [],
        None,
        0,
        0,
    )
    return result
