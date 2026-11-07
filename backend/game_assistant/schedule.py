"""后续活动日程（UpcomingEvent / EventSchedule）。

口径（与 backlog 里这条待办的要求一致）：
  * 日程只有两种状态：**confirmed**（用户确认过的）与 **candidate**（候选，例如从公告里
    抽出来还没核对的）。回答"下一个活动"时**只认 confirmed**；
  * 没有任何已确认日程时，明确回"暂无已确认日程"，**不许**用日服进度、版本号或模型记忆
    去推国服的排期；
  * 存储用 KB 目录下的 JSON（不新增数据库表、不动迁移），文件里带版本号。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

import config

SCHEDULE_VERSION = 1
SHANGHAI = ZoneInfo("Asia/Shanghai")   # 国服口径：起止时间都带 +08:00，比较时不能用裸 datetime
STATUS_CONFIRMED = "confirmed"
STATUS_CANDIDATE = "candidate"
STATUSES = (STATUS_CONFIRMED, STATUS_CANDIDATE)
EventKind = Literal["main", "campaign", "other"]


class UpcomingEvent(BaseModel):
    event_id: str
    title: str
    server: str = "CN"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    event_kind: EventKind = "other"
    status: str = STATUS_CANDIDATE
    source_title: str = ""
    source_url: str = ""
    note: str = ""
    updated_at: datetime = Field(default_factory=datetime.now)


class SchedulePayload(BaseModel):
    version: int = SCHEDULE_VERSION
    items: list[UpcomingEvent] = Field(default_factory=list)


class ScheduleUpsertRequest(BaseModel):
    """新增/更新一条日程。`confirm=True` 表示**用户已经核对过来源**，才标成 confirmed。"""

    event_id: str
    title: str
    server: str = "CN"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    event_kind: EventKind = "other"
    source_title: str = ""
    source_url: str = ""
    note: str = ""
    confirm: bool = False


def schedule_path() -> Path:
    """日程文件路径。**每次现读 config**，测试里 monkeypatch 就能隔离。"""
    return Path(config.GAME_ASSISTANT_KB_DIR) / "upcoming_events_cn.json"


def load_schedule() -> list[UpcomingEvent]:
    """读日程；文件不存在 / 解析不了都当作空列表（不编数据）。"""
    path = schedule_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items: list[UpcomingEvent] = []
    for raw in payload.get("items") or []:
        try:
            items.append(UpcomingEvent.model_validate(raw))
        except Exception:
            continue
    return _sorted(items)


def _sorted(items: list[UpcomingEvent]) -> list[UpcomingEvent]:
    return sorted(items, key=lambda item: (item.starts_at is None, item.starts_at or datetime.max))


def _aware(value: datetime | None, fallback: datetime) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=fallback.tzinfo or SHANGHAI)


def _save(items: list[UpcomingEvent]) -> None:
    path = schedule_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = SchedulePayload(items=_sorted(items))
    path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")


def upsert_event(raw: dict[str, Any], *, confirm: bool = False) -> UpcomingEvent:
    """新增/更新一条日程。`confirm=True` 才会标成 confirmed（默认是 candidate）。"""
    event = UpcomingEvent.model_validate(raw)
    if event.status not in STATUSES:
        event.status = STATUS_CANDIDATE
    if confirm:
        event.status = STATUS_CONFIRMED
    event.updated_at = datetime.now()
    items = [item for item in load_schedule() if item.event_id != event.event_id]
    items.append(event)
    _save(items)
    return event


def delete_event(event_id: str) -> bool:
    items = load_schedule()
    remaining = [item for item in items if item.event_id != event_id]
    if len(remaining) == len(items):
        return False
    _save(remaining)
    return True


def confirmed_events(now: datetime | None = None) -> list[UpcomingEvent]:
    """只返回**已确认**且（按 ends_at 看）还没结束的日程，按开始时间排序。"""
    # 注意：日程里的时间都带 +08:00，默认值也必须是 aware 的，否则比较会抛 TypeError。
    moment = now or datetime.now(SHANGHAI)
    result = []
    for item in load_schedule():
        if item.status != STATUS_CONFIRMED:
            continue
        ends_at = _aware(item.ends_at, moment)
        if ends_at is not None and ends_at < moment:
            continue
        result.append(item)
    return _sorted(result)


def current_confirmed_events(now: datetime | None = None) -> list[UpcomingEvent]:
    """Return confirmed schedule items whose start/end interval contains ``now``."""
    moment = now or datetime.now(SHANGHAI)
    return [
        item
        for item in confirmed_events(moment)
        if (starts_at := _aware(item.starts_at, moment)) is not None and starts_at <= moment
    ]


def current_main_event(
    now: datetime | None = None,
    *,
    items: list[UpcomingEvent] | None = None,
) -> UpcomingEvent | None:
    """Choose the active confirmed main event, never a campaign or placeholder."""
    moment = now or datetime.now(SHANGHAI)
    source = items if items is not None else current_confirmed_events(moment)
    candidates = [
        item
        for item in source
        if item.event_kind == "main"
        and item.status == STATUS_CONFIRMED
        and (starts_at := _aware(item.starts_at, moment)) is not None
        and starts_at <= moment
        and ((ends_at := _aware(item.ends_at, moment)) is None or ends_at >= moment)
    ]
    return max(
        candidates,
        key=lambda item: _aware(item.starts_at, moment) or moment,
        default=None,
    )


def upcoming_confirmed_events(now: datetime | None = None) -> list[UpcomingEvent]:
    """Return confirmed events that have not started yet, in start order."""
    moment = now or datetime.now(SHANGHAI)
    return [
        item
        for item in confirmed_events(moment)
        if (starts_at := _aware(item.starts_at, moment)) is not None and starts_at > moment
    ]


def next_confirmed_event(now: datetime | None = None) -> UpcomingEvent | None:
    events = upcoming_confirmed_events(now)
    return events[0] if events else None
