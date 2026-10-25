"""AI 视频接口：剧本 Agent、关键帧、i2v 任务与视频库。"""
from __future__ import annotations

import base64
import json
import random
import subprocess
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import Response

import content_filter
import config
import database
import llm
import task_state
import task_registry
import task_resources
import video_worker
from routers.settings_router import content_restriction_enabled

router = APIRouter()

VIDEO_KEYFRAME_DIR = config.VIDEO_KEYFRAME_DIR
VIDEO_OUTPUT_DIR = config.VIDEO_OUTPUT_DIR
ALLOWED_KEYFRAME_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
ALLOWED_FRAMES = set(config.VIDEO_ALLOWED_FRAMES)
ALLOWED_SIZES = set(config.VIDEO_ALLOWED_SIZES)
MEDIA_TYPES = {
    ".webm": "video/webm",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".gif": "image/gif",
    ".avi": "video/x-msvideo",
}


def restore_video_jobs() -> None:
    """后端重启后把中断的视频成片记录标记为 interrupted。"""
    database.mark_interrupted_video_records()


def _check_content(text: str) -> None:
    if content_filter.is_always_blocked(text):
        raise HTTPException(status_code=403, detail="该内容被禁止生成")
    if content_restriction_enabled() and content_filter.is_nsfw(text):
        raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")


def _payload_value(payload: dict, key: str, default):
    value = payload.get(key)
    return default if value is None or value == "" else value


def _extract_json(text: str) -> dict:
    """从剧本模型输出中提取 JSON，兼容代码围栏。"""
    cleaned = (text or "").strip().strip("`")
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("剧本输出不是 JSON 对象")
    return data


def _normalize_script(data: dict) -> dict:
    """把剧本输出规范为稳定字段，缺失项用空串补齐。"""
    allowed = {
        "story": "",
        "action": "",
        "scene": "",
        "camera": "",
        "character": "",
        "mood": "",
        "prompt": "",
        "negative_prompt": "",
    }
    result = {}
    for key, default in allowed.items():
        raw = data.get(key)
        if isinstance(raw, str):
            result[key] = raw.strip()
        elif isinstance(raw, (list, dict)):
            result[key] = str(raw)
        else:
            result[key] = default
    return result


def _save_keyframe(data: bytes, original_name: str) -> str:
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_KEYFRAME_EXTS:
        raise HTTPException(status_code=400, detail="关键帧只支持 png/jpg/jpeg/webp/bmp")
    VIDEO_KEYFRAME_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"keyframe_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{suffix}"
    (VIDEO_KEYFRAME_DIR / filename).write_bytes(data)
    return filename


@router.post("/api/video/keyframes")
def upload_keyframe(payload: dict = Body(...)) -> dict:
    """以 base64 data URL 上传一张关键帧图片供 i2v 使用。"""
    data_url = str(payload.get("data") or "").strip()
    filename = str(payload.get("name") or "keyframe.png").strip()
    if not data_url:
        raise HTTPException(status_code=400, detail="关键帧数据不能为空")
    if "," in data_url:
        _, _, encoded = data_url.partition(",")
    else:
        encoded = data_url
    try:
        raw = base64.b64decode(encoded, validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="关键帧 base64 数据格式不正确") from None
    if len(raw) > config.VIDEO_KEYFRAME_MAX_BYTES:
        max_mb = config.VIDEO_KEYFRAME_MAX_BYTES / 1024 / 1024
        raise HTTPException(status_code=400, detail=f"关键帧不能超过 {max_mb:g}MB")
    name = _save_keyframe(raw, filename)
    return {"name": name, "url": f"/api/video/keyframes/{name}"}


@router.get("/api/video/keyframes")
def list_keyframes(
    limit: int = Query(
        config.QUERY_VIDEO_KEYFRAMES_LIMIT_DEFAULT,
        ge=config.QUERY_PAGE_MIN,
        le=config.QUERY_VIDEO_KEYFRAMES_LIMIT_MAX,
    ),
) -> dict:
    """返回已上传的关键帧列表。"""
    items: list[dict] = []
    if VIDEO_KEYFRAME_DIR.is_dir():
        for path in sorted(
            (p for p in VIDEO_KEYFRAME_DIR.iterdir() if p.is_file() and p.suffix.lower() in ALLOWED_KEYFRAME_EXTS),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]:
            items.append({"name": path.name, "url": f"/api/video/keyframes/{path.name}"})
    return {"items": items}


@router.get("/api/video/keyframes/{filename}")
def get_keyframe(filename: str) -> Response:
    """提供关键帧图片访问。"""
    safe_name = Path(filename).name
    path = VIDEO_KEYFRAME_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="关键帧不存在")
    return Response(path.read_bytes(), media_type="image/png")


@router.post("/api/video/open-keyframes")
def open_keyframes() -> dict:
    """在资源管理器中打开关键帧目录。"""
    VIDEO_KEYFRAME_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer.exe", str(VIDEO_KEYFRAME_DIR)])
    return {"ok": True, "path": str(VIDEO_KEYFRAME_DIR)}


@router.post("/api/video/script")
def create_script(payload: dict = Body(...)) -> dict:
    """剧本 Agent：把一句话/一段剧情生成为单镜头分镜 JSON。"""
    source_input = str(payload.get("input") or "").strip()
    if not source_input:
        raise HTTPException(status_code=400, detail="剧情描述不能为空")
    if len(source_input) > config.VIDEO_SCRIPT_MAX_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"剧情描述不能超过 {config.VIDEO_SCRIPT_MAX_LENGTH} 个字符",
        )
    _check_content(source_input)

    restricted = content_restriction_enabled()
    model = config.R18_MODEL if content_filter.is_nsfw(source_input) and not restricted else config.LOCAL_CHAT_MODEL
    system_prompt = (
        "你是本地 AI 动画剧本 Agent，只输出单镜头动画分镜，不要解释、不要拒绝、不要输出代码围栏外的说明。"
        "内容使用动画风格；禁止未成年、儿童相关内容。"
        "如果用户描述包含成人/R18内容且本地限制关闭，请如实设计动作与镜头，不省略、不委婉。"
        "输出严格 JSON 对象，字段：story（中文剧情摘要）、action（英文动作描述，用于视频运动）、"
        "scene（中文场景）、camera（中文镜头语言）、character（中文角色说明）、mood（中文情绪）、"
        "prompt（英文 i2v 正向提示词，强调保持关键帧角色形象、细节与场景一致并描述动作节奏）、"
        "negative_prompt（英文负面提示词，包含 worst quality、deformed、static、blurry、extra limbs、text、watermark）。"
        "prompt 必须是完整可用的英文提示词。"
    )
    raw = ""
    script = {}
    for attempt in range(2):
        try:
            raw = llm.chat(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": source_input},
                ],
                temperature=0.4,
                max_tokens=1400,
                timeout=180,
                think=False,
                model=model,
            )
            data = _extract_json(raw)
            script = _normalize_script(data)
            if script.get("prompt") and script.get("story"):
                break
        except Exception:
            script = {}
    if not script:
        detail = raw.strip() or "剧本模型无输出或输出无法解析"
        raise HTTPException(status_code=502, detail=f"剧本生成失败：{detail[:500]}")
    serialized = json.dumps(script, ensure_ascii=False)
    if content_filter.is_always_blocked(serialized):
        raise HTTPException(status_code=403, detail="该内容被禁止生成")
    script_id = database.insert_video_script(source_input, script, model, restricted)
    return {"script_id": script_id, "script": script, "model": model}


@router.get("/api/video/scripts")
def list_scripts(
    limit: int = Query(
        config.QUERY_VIDEO_SCRIPTS_LIMIT_DEFAULT,
        ge=config.QUERY_PAGE_MIN,
        le=config.QUERY_VIDEO_SCRIPTS_LIMIT_MAX,
    ),
) -> dict:
    """返回最近生成的单镜头剧本。"""
    return {"items": database.list_video_scripts(limit)}


@router.post("/api/video/generate")
def start_video(payload: dict = Body(...)) -> dict:
    """提交 i2v 视频生成任务并进入统一任务注册表。"""
    script = None
    script_id = payload.get("script_id")
    if script_id:
        script = database.get_video_script(int(script_id))
        if not script:
            raise HTTPException(status_code=404, detail="剧本不存在")
        script_id = int(script_id)
    prompt = str(payload.get("prompt") or "").strip()
    negative_prompt = str(payload.get("negative_prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="正向提示词不能为空")
    _check_content(prompt)
    _check_content(negative_prompt)

    keyframe_name = str(payload.get("keyframe_name") or "").strip()
    if Path(keyframe_name).name != keyframe_name:
        raise HTTPException(status_code=400, detail="关键帧文件名不合法")
    if not (VIDEO_KEYFRAME_DIR / keyframe_name).is_file():
        raise HTTPException(status_code=404, detail="关键帧不存在，请先上传")

    try:
        frames = int(_payload_value(payload, "frames", config.VIDEO_DEFAULT_FRAMES))
        fps = int(_payload_value(payload, "fps", config.VIDEO_DEFAULT_FPS))
        width = int(_payload_value(payload, "width", config.VIDEO_DEFAULT_WIDTH))
        height = int(_payload_value(payload, "height", config.VIDEO_DEFAULT_HEIGHT))
        steps = int(_payload_value(payload, "steps", config.VIDEO_DEFAULT_STEPS))
        cfg = float(_payload_value(payload, "cfg", config.VIDEO_DEFAULT_CFG))
        denoise = float(_payload_value(payload, "denoise", config.VIDEO_DEFAULT_DENOISE))
        lora_strength = float(
            _payload_value(payload, "lora_strength", config.VIDEO_DEFAULT_LORA_STRENGTH)
        )
        timeout_seconds = int(
            _payload_value(payload, "timeout_seconds", config.VIDEO_TIMEOUT_SECONDS)
        )
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="视频参数格式不正确") from None
    if frames not in ALLOWED_FRAMES:
        allowed = "/".join(str(value) for value in sorted(ALLOWED_FRAMES))
        raise HTTPException(status_code=400, detail=f"帧数只支持 {allowed}")
    if (width, height) not in ALLOWED_SIZES:
        allowed = "/".join(f"{w}x{h}" for w, h in sorted(ALLOWED_SIZES))
        raise HTTPException(status_code=400, detail=f"分辨率只支持 {allowed}")
    if not config.VIDEO_STEPS_MIN <= steps <= config.VIDEO_STEPS_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"步数必须在 {config.VIDEO_STEPS_MIN}-{config.VIDEO_STEPS_MAX} 之间",
        )
    if not config.VIDEO_CFG_MIN <= cfg <= config.VIDEO_CFG_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"CFG 必须在 {config.VIDEO_CFG_MIN:g}-{config.VIDEO_CFG_MAX:g} 之间",
        )
    if not config.VIDEO_DENOISE_MIN <= denoise <= config.VIDEO_DENOISE_MAX:
        raise HTTPException(
            status_code=400,
            detail=(
                f"denoise 必须在 {config.VIDEO_DENOISE_MIN:g}-"
                f"{config.VIDEO_DENOISE_MAX:g} 之间"
            ),
        )
    if not config.VIDEO_LORA_STRENGTH_MIN <= lora_strength <= config.VIDEO_LORA_STRENGTH_MAX:
        raise HTTPException(
            status_code=400,
            detail=(
                f"LoRA 强度必须在 {config.VIDEO_LORA_STRENGTH_MIN:g}-"
                f"{config.VIDEO_LORA_STRENGTH_MAX:g} 之间"
            ),
        )

    busy_tasks = task_state.running_tasks()
    if busy_tasks:
        labels = "、".join(task["label"] for task in busy_tasks)
        raise HTTPException(status_code=409, detail=f"有其他项目正在运行（{labels}），请稍后再进行")

    use_lora = bool(payload.get("use_lora", True))
    seed = payload.get("seed")
    try:
        seed = random.randint(0, 2**63 - 1) if seed is None else int(seed)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="seed 格式不正确") from None

    job_id = uuid.uuid4().hex
    loras = [config.VIDEO_LORA] if use_lora else []
    database.insert_video_record(
        job_id,
        script_id,
        keyframe_name,
        prompt,
        negative_prompt,
        config.VIDEO_MODEL,
        loras,
        seed,
        width,
        height,
        frames,
        fps,
    )
    params = {
        "keyframe_name": keyframe_name,
        "positive_prompt": prompt,
        "negative_prompt": negative_prompt,
        "model": config.VIDEO_MODEL,
        "clip": config.VIDEO_CLIP,
        "vae": config.VIDEO_VAE,
        "clip_vision": config.VIDEO_CLIP_VISION,
        "lora": config.VIDEO_LORA,
        "use_lora": use_lora,
        "seed": seed,
        "frames": frames,
        "fps": fps,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg": cfg,
        "denoise": denoise,
        "lora_strength": lora_strength,
        "timeout_seconds": timeout_seconds,
        "script_id": script_id,
    }
    task_registry.register("video", job_id, payload=params, total=frames, resources=task_resources.for_kind("video"))
    threading.Thread(target=video_worker.run_video_job, args=(job_id, params), daemon=True).start()
    return {"job_id": job_id, "status": "running", "record_id": database.get_video_record_by_job(job_id)["id"]}


def _job_status(job_id: str) -> dict:
    record = database.get_video_record_by_job(job_id)
    task = task_registry.get("video", job_id) or database.get_background_job(job_id)
    if not record and not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"record": record, "task": task}


@router.get("/api/video/jobs/{job_id}")
def video_status(job_id: str) -> dict:
    """查询视频任务进度与成片记录。"""
    return _job_status(job_id)


@router.post("/api/video/jobs/{job_id}/stop")
def stop_video(job_id: str) -> dict:
    """停止视频生成任务。"""
    if not task_registry.get("video", job_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return video_worker.request_stop(job_id)


@router.get("/api/video/library")
def video_library(
    limit: int = Query(
        config.QUERY_VIDEO_LIBRARY_LIMIT_DEFAULT,
        ge=config.QUERY_PAGE_MIN,
        le=config.QUERY_VIDEO_LIBRARY_LIMIT_MAX,
    ),
) -> dict:
    """返回成片列表并补充访问 URL。"""
    items = database.list_video_records(limit)
    for item in items:
        item["video_url"] = f"/api/video/file/{item['video_name']}" if item.get("video_name") else None
        item["keyframe_url"] = f"/api/video/keyframes/{item['keyframe_name']}" if item.get("keyframe_name") else None
    return {"items": items}


@router.get("/api/video/file/{filename}")
def get_video(filename: str) -> Response:
    """提供本地成片访问。"""
    safe_name = Path(filename).name
    path = VIDEO_OUTPUT_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="视频不存在")
    media_type = MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return Response(path.read_bytes(), media_type=media_type)


@router.delete("/api/video/library/{record_id}")
def delete_video(record_id: int) -> dict:
    """删除成片记录并清理本地视频文件（关键帧可能被复用，不删除）。"""
    record = database.get_video_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    video_name = record.get("video_name")
    if video_name:
        (VIDEO_OUTPUT_DIR / video_name).unlink(missing_ok=True)
    database.delete_video_record(record_id)
    return {"ok": True}


@router.post("/api/video/open-library")
def open_video_library() -> dict:
    """在资源管理器中打开成片目录。"""
    VIDEO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer.exe", str(VIDEO_OUTPUT_DIR)])
    return {"ok": True, "path": str(VIDEO_OUTPUT_DIR)}
