"""资源占用、任务状态与活动审计接口。"""
from __future__ import annotations

from fastapi import APIRouter, Query

import config
import database
import task_resources
import task_state

router = APIRouter()

MAX_BACKUPS = config.BACKUP_KEEP_COUNT


@router.get("/api/system/busy")
def system_busy() -> dict:
    """返回当前运行中的重任务与资源快照；保留旧版字段。"""
    tasks = task_state.running_tasks()
    return {"busy": bool(tasks), "tasks": tasks, "resources": task_resources.snapshot()}


@router.get("/api/system/resources")
def system_resources() -> dict:
    """返回资源定义、活动租约与可用性快照。"""
    return task_resources.snapshot()


@router.get("/api/system/tasks")
def system_tasks(
    kind: str | None = None,
    status: str | None = None,
    limit: int = Query(
        config.QUERY_SYSTEM_TASKS_LIMIT_DEFAULT,
        ge=config.QUERY_PAGE_MIN,
        le=config.QUERY_SYSTEM_TASKS_LIMIT_MAX,
    ),
) -> dict:
    """统一任务列表/历史：读取 background_jobs 注册表记录。"""
    rows = database.list_background_jobs(
        kind=(kind or None),
        status=(status or None),
        limit=limit,
    )
    items = []
    for row in rows:
        item = dict(row)
        item["type"] = item.get("kind")
        item["label"] = task_state.TASK_LABELS.get(str(item.get("kind") or ""), str(item.get("kind") or ""))
        item["resource_claims"] = task_resources.list_job_claims(str(item.get("job_id") or ""), active_only=True)
        items.append(item)
    return {"items": items, "running": task_state.running_tasks()}


@router.get("/api/system/activity-events")
def system_activity_events(
    event_type: str | None = None,
    module: str | None = None,
    job_id: str | None = None,
    kind: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    """读取最近活动审计事件。"""
    return {
        "items": database.list_activity_events(
            event_type=event_type or None,
            module=module or None,
            job_id=job_id or None,
            kind=kind or None,
            limit=limit,
        )
    }


@router.post("/api/system/auto-shutdown/cancel")
def cancel_auto_shutdown() -> dict:
    """取消任务完成后自动关机倒计时。"""
    import auto_shutdown

    return auto_shutdown.cancel()


@router.post("/api/system/backup")
def create_backup() -> dict:
    """创建数据库备份，并清理超出保留数量的旧备份。"""
    from pathlib import Path

    info = database.backup_database(config.BACKUP_ROOT)
    db_files = sorted(
        Path(config.BACKUP_ROOT).glob("rider_studio_*.db"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for stale in db_files[MAX_BACKUPS:]:
        try:
            stale.unlink()
        except OSError:
            pass
    return {"ok": True, "backup": info, "kept": min(len(db_files), MAX_BACKUPS)}


@router.get("/api/system/backups")
def list_backups() -> dict:
    """列出已保留的数据库备份。"""
    from datetime import datetime
    from pathlib import Path

    items = []
    root = Path(config.BACKUP_ROOT)
    if root.exists():
        for path in sorted(root.glob("rider_studio_*.db"), key=lambda item: item.stat().st_mtime, reverse=True):
            items.append(
                {
                    "name": path.name,
                    "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
                    "created_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                }
            )
    return {"items": items}