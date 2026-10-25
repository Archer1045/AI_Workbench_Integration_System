"""通用活动审计事件：只记录可审计摘要，不承载业务状态。"""
from __future__ import annotations

import database


def record(
    event_type: str,
    *,
    module: str = "",
    actor_type: str = "system",
    job_id: str | None = None,
    kind: str | None = None,
    severity: str = "info",
    summary: str = "",
    correlation_id: str | None = None,
    payload: dict | None = None,
) -> dict | None:
    """写入活动事件；审计失败不得阻断任务主流程。"""
    try:
        return database.insert_activity_event(
            event_type,
            module=module,
            actor_type=actor_type,
            job_id=job_id,
            kind=kind,
            severity=severity,
            summary=summary,
            correlation_id=correlation_id,
            payload=payload,
        )
    except Exception:
        return None


def list_events(**filters) -> list[dict]:
    return database.list_activity_events(**filters)