"""数据看板查询与 Excel 导出接口。"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from io import BytesIO

from fastapi import APIRouter, Body, HTTPException, Query, Response
from openpyxl import Workbook

import config
import database
import preset_asset_service
import services
import task_state
from routers.chat import translate_tag_list

router = APIRouter()


def _avg_durations(rows: list[dict]) -> float:
    durations: list[float] = []
    for row in rows:
        created = row.get("created_at")
        finished = row.get("finished_at")
        if not created or not finished:
            continue
        try:
            durations.append((datetime.fromisoformat(str(finished)) - datetime.fromisoformat(str(created))).total_seconds())
        except ValueError:
            continue
    return round(sum(durations) / len(durations), 1) if durations else 0


@router.get("/api/records/module-summary")
def module_summary() -> dict:
    """模块概览：LoRA 训练、批量绘画、图片库、提示词集、情感陪伴汇总。"""
    train_rows = database.list_train_jobs_raw()
    batch_rows = database.list_batch_jobs_raw()
    prompt_rows = database.list_prompt_sets_raw()
    video_rows = database.list_video_records_raw()
    draw_stats = database.draw_stats()
    image_total = database.query_draw_images(page=1, page_size=1)["total"]
    try:
        train_output_count = len(list(config.OUTPUT_DIR.glob("*.safetensors")))
    except Exception:
        train_output_count = 0
    prompt_top = sorted(
        prompt_rows,
        key=lambda row: row.get("use_count") or 0,
        reverse=True,
    )[: config.QUERY_MODULE_TOP_LIMIT]
    return {
        "train": {
            "count": len(train_rows),
            "status": dict(Counter(row["status"] for row in train_rows)),
            "avg_duration": _avg_durations(train_rows),
            "output_count": train_output_count,
        },
        "batch": {
            "count": len(batch_rows),
            "status": dict(Counter(row["status"] for row in batch_rows)),
            "avg_duration": _avg_durations(batch_rows),
        },
        "image_library": {
            "count": image_total,
            "model_counts": draw_stats["model_counts"],
            "daily": draw_stats["daily"],
        },
        "prompt_sets": {
            "count": len(prompt_rows),
            "by_type": dict(Counter(row["type"] for row in prompt_rows)),
            "top_used": prompt_top,
        },
        "video": {
            "count": len(video_rows),
            "status": dict(Counter(row["status"] for row in video_rows)),
            "avg_duration": _avg_durations(video_rows),
        },
        "companion": database.companion_summary(),
    }


def _daily_counts(
    rows: list[dict],
    date_key: str = "created_at",
    days: int = config.QUERY_DAILY_TREND_DAYS,
) -> list[dict]:
    daily: dict[str, int] = {}
    for row in rows:
        day = str(row.get(date_key) or "")[:10]
        if day:
            daily[day] = daily.get(day, 0) + 1
    return [{"date": day, "count": daily[day]} for day in sorted(daily)[-days:]]


def _error_rate(rows: list[dict], status_key: str = "status") -> float:
    total = len(rows)
    errors = sum(1 for row in rows if str(row.get(status_key) or "") in ("error", "failed"))
    return round(errors / total, 3) if total else 0


def _recent_errors(
    rows: list[dict],
    limit: int = config.QUERY_RECENT_ERROR_LIMIT,
) -> list[str]:
    result: list[str] = []
    for row in rows:
        if str(row.get("status") or "") in ("error", "failed") and row.get("error"):
            result.append(str(row["error"])[:120])
        if len(result) >= limit:
            break
    return result


def _dashboard_date_window(
    date_from: str | None,
    date_to: str | None,
) -> tuple[str, str]:
    today = datetime.now().astimezone().date()
    parsed_to = datetime.fromisoformat(str(date_to)).date() if date_to else today
    parsed_from = (
        datetime.fromisoformat(str(date_from)).date()
        if date_from
        else parsed_to - timedelta(days=6)
    )
    if parsed_from > parsed_to:
        parsed_from, parsed_to = parsed_to, parsed_from
    return parsed_from.isoformat(), parsed_to.isoformat()


def _in_date_range(
    rows: list[dict],
    date_from: str,
    date_to: str,
    key: str,
) -> list[dict]:
    return [
        row
        for row in rows
        if date_from <= str(row.get(key) or "")[:10] <= date_to
    ]


def _duration_summary(
    rows: list[dict],
    created_key: str = "created_at",
    finished_key: str = "finished_at",
) -> float:
    durations: list[float] = []
    for row in rows:
        created = row.get(created_key)
        finished = row.get(finished_key)
        if not created or not finished:
            continue
        try:
            durations.append(
                (
                    datetime.fromisoformat(str(finished))
                    - datetime.fromisoformat(str(created))
                ).total_seconds()
            )
        except ValueError:
            continue
    return round(sum(durations) / len(durations), 1) if durations else 0


def _job_error_rate(rows: list[dict]) -> float:
    errors = sum(
        1
        for row in rows
        if str(row.get("status") or "") in {"error", "failed", "interrupted"}
    )
    return round(errors / len(rows), 3) if rows else 0


@router.get("/api/records/dashboard/v3")
def dashboard_v3(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
) -> dict:
    """Read-only cross-module dashboard focused on drawing, training, and assets."""
    try:
        range_from, range_to = _dashboard_date_window(date_from, date_to)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式必须是 YYYY-MM-DD") from None

    draw = database.draw_stats(range_from, range_to)
    batch_rows = _in_date_range(
        database.list_batch_jobs_raw(), range_from, range_to, "created_at"
    )
    draw["batch_count"] = len(batch_rows)
    draw["batch_error_rate"] = _job_error_rate(batch_rows)

    train_rows = _in_date_range(
        database.list_train_jobs_raw(), range_from, range_to, "created_at"
    )
    train_output_count = 0
    try:
        train_output_count = len(list(config.OUTPUT_DIR.glob("*.safetensors")))
    except Exception:
        train_output_count = 0
    running_train = next(
        (row for row in train_rows if str(row.get("status") or "") == "running"),
        None,
    )
    train = {
        "count": len(train_rows),
        "status": dict(Counter(row.get("status") or "unknown" for row in train_rows)),
        "error_rate": _job_error_rate(train_rows),
        "avg_duration": _duration_summary(train_rows),
        "output_count": train_output_count,
        "daily": _daily_counts(train_rows, "created_at"),
        "recent_errors": _recent_errors(train_rows),
        "current": running_train,
        "latest": train_rows[0] if train_rows else None,
    }

    preset_assets = preset_asset_service.dashboard_summary()

    job_rows = _in_date_range(
        database.list_background_jobs(limit=config.QUERY_RECORD_EXPORT_LIMIT_DEFAULT),
        range_from,
        range_to,
        "created_at",
    )
    running_tasks = task_state.running_tasks()
    system = {
        "gpu": services.gpu_status(),
        "busy": bool(running_tasks),
        "running_tasks": running_tasks,
        "jobs": {
            "count": len(job_rows),
            "status": dict(Counter(row.get("status") or "unknown" for row in job_rows)),
            "error_rate": _job_error_rate(job_rows),
            "daily": _daily_counts(job_rows, "created_at"),
            "recent_errors": _recent_errors(job_rows),
        },
    }

    secondary = {
        "prompt_agent": database.query_records(
            "prompt", range_from, range_to, page=1, page_size=1
        )["total"],
        "recruitment_agent": database.query_records(
            "agent", range_from, range_to, page=1, page_size=1
        )["total"],
        "video": database.query_records(
            "video", range_from, range_to, page=1, page_size=1
        )["total"],
        "companion": database.companion_summary(),
    }
    return {
        "range": {"date_from": range_from, "date_to": range_to},
        "overview": {
            "draw": {
                "total": draw["total"],
                "success_count": draw["success_count"],
                "error_count": draw["error_count"],
                "avg_duration": draw["avg_duration"],
            },
            "train": {
                "count": train["count"],
                "status": train["status"],
                "current": train["current"],
            },
            "preset_assets": {
                "total": preset_assets["total"],
                "formal_count": preset_assets["formal_count"],
                "candidate_only_count": preset_assets["candidate_only_count"],
                "missing_count": preset_assets["missing_count"],
                "ready_count": preset_assets["ready_count"],
                "running_count": preset_assets["running_count"],
                "failed_count": preset_assets["failed_count"],
            },
            "system": system,
        },
        "draw": draw,
        "train": train,
        "preset_assets": preset_assets,
        "system": system,
        "secondary": secondary,
    }


@router.get("/api/records/module-summary/v2")
def module_summary_v2() -> dict:
    """模块概览 v2：卡片数据 + 近 7 天趋势 + 错误率 + 系统状态联动。"""
    train_rows = database.list_train_jobs_raw()
    batch_rows = database.list_batch_jobs_raw()
    prompt_rows = database.list_prompt_sets_raw()
    video_rows = database.list_video_records_raw()
    draw_stats = database.draw_stats()
    image_total = database.query_draw_images(page=1, page_size=1)["total"]
    try:
        train_output_count = len(list(config.OUTPUT_DIR.glob("*.safetensors")))
    except Exception:
        train_output_count = 0
    prompt_top = sorted(
        prompt_rows,
        key=lambda row: row.get("use_count") or 0,
        reverse=True,
    )[: config.QUERY_MODULE_TOP_LIMIT_V2]
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    today_count = sum(1 for item in draw_stats["daily"] if item["date"] == today)
    gpu = services.gpu_status()
    return {
        "train": {
            "count": len(train_rows),
            "status": dict(Counter(row["status"] for row in train_rows)),
            "error_rate": _error_rate(train_rows),
            "avg_duration": _avg_durations(train_rows),
            "output_count": train_output_count,
            "daily": _daily_counts(train_rows),
            "recent_errors": _recent_errors(train_rows),
        },
        "batch": {
            "count": len(batch_rows),
            "status": dict(Counter(row["status"] for row in batch_rows)),
            "error_rate": _error_rate(batch_rows),
            "avg_duration": _avg_durations(batch_rows),
            "daily": _daily_counts(batch_rows),
            "recent_errors": _recent_errors(batch_rows),
        },
        "image_library": {
            "count": image_total,
            "model_counts": draw_stats["model_counts"],
            "size_counts": draw_stats["size_counts"],
            "daily": draw_stats["daily"][-config.QUERY_DAILY_TREND_DAYS :],
            "today_count": today_count,
        },
        "prompt_sets": {
            "count": len(prompt_rows),
            "by_type": dict(Counter(row["type"] for row in prompt_rows)),
            "top_used": prompt_top,
            "unused_count": sum(1 for row in prompt_rows if not (row.get("use_count") or 0)),
        },
        "video": {
            "count": len(video_rows),
            "status": dict(Counter(row["status"] for row in video_rows)),
            "error_rate": _error_rate(video_rows),
            "avg_duration": _avg_durations(video_rows),
            "daily": _daily_counts(video_rows),
            "recent_errors": _recent_errors(video_rows),
        },
        "companion": database.companion_summary(),
        "system": {
            "gpu_used_mb": gpu["memory_used_mb"],
            "gpu_total_mb": gpu["memory_total_mb"],
            "active_models": gpu["active_models"],
            "busy": bool(task_state.running_tasks()),
        },
    }


@router.post("/api/records/cleanup")
def cleanup_records(payload: dict = Body(...)) -> dict:
    """按保留天数清理历史记录（仅删除数据库行，不删除图片文件）。"""
    try:
        days = max(
            config.SETTINGS_DATA_RETENTION_MIN + 1,
            min(
                config.SETTINGS_DATA_RETENTION_MAX,
                int(payload.get("days", 0)),
            ),
        )
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="保留天数必须是整数") from None
    deleted = database.cleanup_records_before(days)
    return {"ok": True, "deleted": deleted}


# 每次调用标签翻译接口的最大标签数，避免单次大模型输出过长被截断
OVERVIEW_TAG_CHUNK = config.QUERY_OVERVIEW_TAG_CHUNK

# 导出 Excel 时的中文字段名
HEADER_MAP = {
    "agent": {
        "id": "ID",
        "session_id": "会话ID",
        "created_at": "对话时间",
        "sender": "发送人",
        "content": "对话内容",
        "retrieval_score": "检索匹配度",
        "source": "来源",
    },
    "draw": {
        "id": "ID",
        "batch_id": "批次ID",
        "group_index": "组号",
        "started_at": "任务开始时间",
        "finished_at": "任务结束时间",
        "duration_seconds": "任务耗时(秒)",
        "prompt": "提示词",
        "prompt_translation": "提示词翻译",
        "negative_prompt": "负面提示词",
        "negative_translation": "负面提示词翻译",
        "width": "宽度",
        "height": "高度",
        "steps": "步数",
        "cfg": "CFG",
        "model": "模型",
        "loras_json": "LoRA 列表",
        "lora_anima_turbo": "anima-turbo-lora-v0.2",
        "lora_high_contrast": "high-contrast aesthetic",
        "image_path": "图片路径",
        "image_url": "图片地址",
        "seed": "随机种子",
        "status": "状态",
        "error": "错误信息",
    },
    "prompt": {
        "id": "ID",
        "started_at": "任务开始时间",
        "finished_at": "任务结束时间",
        "duration_seconds": "任务耗时(秒)",
        "mode": "模式",
        "user_input": "用户输入",
        "image_path": "图片路径",
        "description": "原始描述",
        "prompt_result": "生成提示词",
        "model": "模型",
        "status": "状态",
    },
    "video": {
        "id": "ID",
        "job_id": "任务ID",
        "script_id": "剧本ID",
        "keyframe_name": "关键帧",
        "video_name": "成片文件",
        "prompt": "正向提示词",
        "negative_prompt": "负面提示词",
        "model": "模型",
        "loras": "LoRA",
        "seed": "随机种子",
        "width": "宽度",
        "height": "高度",
        "frames": "帧数",
        "fps": "帧率",
        "duration_seconds": "耗时(秒)",
        "status": "状态",
        "error": "错误信息",
        "created_at": "创建时间",
        "finished_at": "结束时间",
    },
}


def build_excel(kind: str, rows: list[dict]) -> bytes:
    """把记录行写入 Excel 工作簿并返回字节。"""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = kind
    if rows:
        keys = list(rows[0].keys())
        headers = [HEADER_MAP.get(kind, {}).get(key, key) for key in keys]
        worksheet.append(headers)
        for row in rows:
            worksheet.append([row.get(key, "") for key in keys])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@router.get("/api/records")
def records(
    kind: str = Query("agent"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    page: int = Query(
        config.QUERY_RECORDS_PAGE_DEFAULT,
        ge=config.QUERY_PAGE_MIN,
    ),
    page_size: int = Query(
        config.QUERY_RECORDS_PAGE_SIZE_DEFAULT,
        ge=config.QUERY_PAGE_MIN,
        le=config.QUERY_RECORDS_PAGE_SIZE_MAX,
    ),
) -> dict:
    """按类型、日期范围分页查询记录。"""
    if kind not in database.available_kinds():
        raise HTTPException(status_code=404, detail="unknown kind")
    return database.query_records(kind, date_from, date_to, page, page_size)


@router.get("/api/records/prompt-stats")
def prompt_stats(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    top: int = Query(
        config.QUERY_PROMPT_STATS_TOP_DEFAULT,
        ge=config.QUERY_PAGE_MIN,
        le=config.QUERY_PROMPT_STATS_TOP_MAX,
    ),
    normalize: bool = Query(True),
    per_image: bool = Query(True),
    exclude_auto: bool = Query(True),
) -> dict:
    """统计 AI 绘画中最常用的单个提示词标签。"""
    rows = database.export_records(
        "draw",
        date_from,
        date_to,
        limit=config.QUERY_RECORD_EXPORT_LIMIT_DEFAULT,
    )
    counter: Counter[str] = Counter()
    total_images = 0
    for row in rows:
        prompt = row.get("prompt") or ""
        tags = [tag.strip() for tag in prompt.split(",") if tag.strip()]
        if normalize:
            tags = [tag.lower() for tag in tags]
        if per_image:
            tags = list(dict.fromkeys(tags))
        if exclude_auto:
            tags = [tag for tag in tags if tag != "uncensored"]
        if tags:
            total_images += 1
        counter.update(tags)
    items = [
        {
            "tag": tag,
            "count": count,
            "percent": round(count / total_images * 100, 2) if total_images else 0,
        }
        for tag, count in counter.most_common(top)
    ]
    translated = {
        item["tag"]: item["translation"]
        for item in translate_tag_list([item["tag"] for item in items])
    }
    for item in items:
        item["translation"] = translated.get(item["tag"], "")
    return {
        "total_tags": len(counter),
        "total_images": total_images,
        "top": top,
        "items": items,
    }


def _collect_prompt_tags(rows: list[dict], normalize: bool = True, exclude_auto: bool = True) -> list[str]:
    """从绘画记录里提取去重后的单个提示词标签。"""
    seen: set[str] = set()
    tags: list[str] = []
    for row in rows:
        prompt = row.get("prompt") or ""
        for tag in (item.strip() for item in prompt.split(",") if item.strip()):
            key = tag.lower() if normalize else tag
            if exclude_auto and key == "uncensored":
                continue
            if key not in seen:
                seen.add(key)
                tags.append(tag)
    tags.sort(key=str.lower)
    return tags


@router.get("/api/records/prompt-overview")
def prompt_overview(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    normalize: bool = Query(True),
    exclude_auto: bool = Query(True),
) -> dict:
    """返回 AI 绘画中使用过的全部单个提示词及中文翻译。"""
    rows = database.export_records(
        "draw",
        date_from,
        date_to,
        limit=config.QUERY_RECORD_EXPORT_LIMIT_DEFAULT,
    )
    tags = _collect_prompt_tags(rows, normalize=normalize, exclude_auto=exclude_auto)
    items: list[dict] = []
    for start in range(0, len(tags), OVERVIEW_TAG_CHUNK):
        chunk = tags[start : start + OVERVIEW_TAG_CHUNK]
        translated = {
            item["tag"]: item["translation"]
            for item in translate_tag_list(chunk)
        }
        items.extend(
            {"tag": tag, "translation": translated.get(tag, "")}
            for tag in chunk
        )
    return {"total": len(items), "items": items}


@router.get("/api/export/{kind}")
def export(kind: str, date_from: str | None = None, date_to: str | None = None) -> Response:
    """导出 Excel 文件。"""
    if kind not in database.available_kinds():
        raise HTTPException(status_code=404, detail="unknown kind")
    data = build_excel(kind, database.export_records(kind, date_from, date_to))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{kind}_records.xlsx"'},
    )


@router.get("/api/records/stats")
def records_stats(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
) -> dict:
    """返回绘画记录统计：状态/模型/尺寸分布与每日趋势。"""
    return database.draw_stats(date_from, date_to)
