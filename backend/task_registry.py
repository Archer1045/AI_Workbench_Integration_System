"""统一后台任务注册表：任务创建、状态流转、资源租约与 SQLite 持久化。"""
from __future__ import annotations

import threading
import time

import database
import task_activity
import task_resources

TERMINAL_STATUSES = {"done", "error", "stopped", "cancelled", "interrupted"}

_REGISTRY: dict[str, dict[str, dict]] = {}
_LOCK = threading.RLock()
_HEARTBEATS: dict[str, tuple[threading.Event, threading.Thread]] = {}
_HEARTBEAT_INTERVAL_SECONDS = 30.0


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _heartbeat_key(kind: str, job_id: str) -> str:
    return f"{kind}:{job_id}"


def _record_event(event_type: str, job: dict, **changes) -> None:
    task_activity.record(
        event_type,
        module="task",
        job_id=str(job.get("job_id") or ""),
        kind=str(job.get("kind") or ""),
        summary=str(changes.pop("summary", "")),
        payload=changes or None,
    )


def _start_heartbeat(kind: str, job_id: str) -> None:
    key = _heartbeat_key(kind, job_id)
    with _LOCK:
        if key in _HEARTBEATS:
            return
        stop = threading.Event()
        thread = threading.Thread(
            target=_heartbeat_loop,
            args=(kind, job_id, stop),
            daemon=True,
            name=f"task-resource-heartbeat-{kind}-{job_id[:8]}",
        )
        _HEARTBEATS[key] = (stop, thread)
        thread.start()


def _stop_heartbeat(kind: str, job_id: str) -> None:
    key = _heartbeat_key(kind, job_id)
    with _LOCK:
        item = _HEARTBEATS.pop(key, None)
    if item:
        item[0].set()


def _heartbeat_loop(kind: str, job_id: str, stop: threading.Event) -> None:
    while not stop.wait(_HEARTBEAT_INTERVAL_SECONDS):
        renewed = task_resources.renew_resources(job_id)
        if renewed:
            continue
        task_activity.record(
            "resource.lease_lost",
            module="system",
            job_id=job_id,
            kind=kind,
            severity="warning",
            summary="任务资源租约未能续期",
        )
        return


def register(
    kind: str,
    job_id: str,
    payload: dict | None = None,
    total: int = 0,
    *,
    status: str = "running",
    resources: list[dict | str] | None = None,
) -> dict:
    """注册任务、按需获取资源并落库。"""
    normalized_resources = task_resources.normalize_resources(resources)
    job = {
        "job_id": job_id,
        "kind": kind,
        "status": status,
        "total": total,
        "done": 0,
        "current": "",
        "error": None,
        "stop_requested": False,
        "created_at": _now(),
        "updated_at": _now(),
        "finished_at": None,
        "payload": payload or {},
        "resources": normalized_resources,
    }
    if status == "running" and normalized_resources:
        task_resources.claim_resources(job_id, kind, normalized_resources)
    try:
        with _LOCK:
            _REGISTRY.setdefault(kind, {})[job_id] = job
        _persist(job)
    except Exception:
        if status == "running" and normalized_resources:
            task_resources.release_resources(job_id, reason="registration_failed")
        with _LOCK:
            _REGISTRY.get(kind, {}).pop(job_id, None)
        raise
    if status == "running" and normalized_resources:
        _start_heartbeat(kind, job_id)
    _record_event("task.registered", job, status=status)
    if status == "running":
        _notify_started(kind, job_id)
    return job


def update(kind: str, job_id: str, **changes) -> dict | None:
    """更新任务状态并落库；按需获取或释放资源。"""
    existing = get(kind, job_id)
    if not existing:
        return None
    previous_status = str(existing.get("status") or "")
    next_status = str(changes.get("status", previous_status) or previous_status)
    acquired = False
    if previous_status != "running" and next_status == "running":
        task_resources.claim_resources(job_id, kind, existing.get("resources") or [])
        acquired = True
    try:
        with _LOCK:
            job = _REGISTRY.get(kind, {}).get(job_id)
            if not job:
                return None
            previous_status = str(job.get("status") or "")
            for key, value in changes.items():
                job[key] = value
            job["updated_at"] = _now()
            if job.get("status") in TERMINAL_STATUSES and job.get("finished_at") is None:
                job["finished_at"] = _now()
            snapshot = dict(job)
        _persist(snapshot)
        with _LOCK:
            current = _REGISTRY.get(kind, {}).get(job_id)
            if current is not None:
                current.update(snapshot)
    except Exception:
        if acquired:
            task_resources.release_resources(job_id, reason="update_failed")
        raise
    if next_status == "running" and (existing.get("resources") or []):
        _start_heartbeat(kind, job_id)
    if next_status in TERMINAL_STATUSES:
        _stop_heartbeat(kind, job_id)
        task_resources.release_resources(job_id, reason=f"task_{next_status}")
    if previous_status != next_status:
        _record_event("task.status_changed", snapshot, from_status=previous_status, to_status=next_status)
    if previous_status != next_status and next_status == "running":
        _notify_started(kind, job_id)
    return snapshot


def finish(kind: str, job_id: str, status: str, error: str | None = None) -> dict | None:
    """结束任务（done/error/stopped/interrupted）。"""
    existing = get(kind, job_id)
    if existing and existing.get("status") in TERMINAL_STATUSES:
        return existing
    result = update(kind, job_id, status=status, error=error)
    if result:
        try:
            from auto_shutdown import notify_task_finished

            notify_task_finished(kind, job_id, status)
        except Exception:
            pass
    return result


def get(kind: str, job_id: str) -> dict | None:
    with _LOCK:
        job = _REGISTRY.get(kind, {}).get(job_id)
        if job:
            return job
    row = database.get_background_job(job_id)
    if row and row.get("kind") == kind:
        job = _normalize_db_row(row)
        with _LOCK:
            _REGISTRY.setdefault(kind, {})[job_id] = job
        return job
    return None


def running_tasks() -> list[dict]:
    """返回当前所有运行中任务（注册表优先，数据库兜底）。"""
    result: list[dict] = []
    with _LOCK:
        for kind, jobs in _REGISTRY.items():
            for job in jobs.values():
                if job.get("status") == "running":
                    result.append(
                        {
                            "type": kind,
                            "label": kind,
                            "job_id": job["job_id"],
                            "resources": list(job.get("resources") or []),
                        }
                    )
    return result


def restore_interrupted() -> None:
    """后端启动时把库内 running 任务统一标记为 interrupted 并释放资源。"""
    rows = database.list_background_jobs(status="running")
    for row in rows:
        kind = str(row.get("kind") or "")
        job_id = str(row.get("job_id") or "")
        if not kind or not job_id:
            continue
        row["status"] = "interrupted"
        row["error"] = "后端重启中断，任务无法继续"
        row["finished_at"] = _now()
        row["updated_at"] = _now()
        database.save_background_job(row)
        task_resources.release_resources(job_id, reason="startup_recovery")
        _stop_heartbeat(kind, job_id)
        with _LOCK:
            normalized = _normalize_db_row(row)
            _REGISTRY.setdefault(kind, {})[job_id] = normalized
        _record_event(
            "task.status_changed",
            normalized,
            from_status="running",
            to_status="interrupted",
            reason="backend_restart",
        )


def _notify_started(kind: str, job_id: str) -> None:
    try:
        from auto_shutdown import notify_task_started

        notify_task_started(kind, job_id)
    except Exception:
        pass


def _normalize_db_row(row: dict) -> dict:
    resources = row.get("resources")
    if resources is None:
        try:
            import json

            resources = json.loads(row.get("resources_json") or "[]")
        except Exception:
            resources = []
    return {
        "job_id": row.get("job_id"),
        "kind": row.get("kind"),
        "status": row.get("status"),
        "total": row.get("total") or 0,
        "done": row.get("done") or 0,
        "current": row.get("current") or "",
        "error": row.get("error"),
        "stop_requested": bool(row.get("stop_requested")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "finished_at": row.get("finished_at"),
        "payload": row.get("payload") or {},
        "resources": task_resources.normalize_resources(resources),
    }


def _persist(job: dict) -> None:
    try:
        database.save_background_job(job)
    except Exception:
        # 持久化失败不应阻断任务主流程
        pass
