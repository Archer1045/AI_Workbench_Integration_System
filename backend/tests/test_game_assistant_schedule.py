"""后续活动日程（UpcomingEvent / 「下一个活动」意图）回归测试。

硬要求：只用 **confirmed** 的日程回答；没有就明确说没有；不许用日服进度或模型记忆推国服排期。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import config
from game_assistant import domain, schedule, service

TZ = timezone(timedelta(hours=8))     # 国服口径


# ---------- 活动生命周期（2026-10-15 定） ----------
# 起因：幕末武斗神话 2026-10-15 13:59 结束后，页面仍把它当"本期活动"完整展示
# —— 视图里从来没有"已结束"这个概念，只按"已开放"算。


def test_event_status_running_then_shop_window_then_closed(schedule_env) -> None:
    """三档口径：进行中 / 已结束但交换所还开 / 已完全关闭；`ends_at` 当刻即算结束。"""
    bundle = _bundle()
    assert service.event_status(bundle, datetime(2026, 10, 15, 13, 58, tzinfo=TZ)) == service.STATUS_RUNNING
    assert service.event_status(bundle, datetime(2026, 10, 15, 13, 59, tzinfo=TZ)) == service.STATUS_ENDED_SHOP_OPEN
    assert service.event_status(bundle, datetime(2026, 10, 18, 12, 0, tzinfo=TZ)) == service.STATUS_ENDED_SHOP_OPEN
    assert service.event_status(bundle, datetime(2026, 10, 22, 13, 59, tzinfo=TZ)) == service.STATUS_CLOSED


def test_event_without_exchange_closes_right_after_it_ends(schedule_env) -> None:
    """没有交换所的活动：结束即 closed（不能一直挂着"商店剩余 N 天"）。"""
    bundle = _bundle().model_copy(update={"exchange_ends_at": None})
    at_end = datetime(2026, 10, 15, 13, 59, tzinfo=TZ)

    assert service.event_status(bundle, at_end) == service.STATUS_CLOSED
    state = service.shop_state(bundle, at_end)
    assert state == {"ends_at": None, "state": "none", "days_left": None, "ends_today": False}


def test_shop_state_counts_whole_days_and_flags_the_deadline_day(schedule_env) -> None:
    """天数向下取整（保守，绝不出现"剩余 0 天"）；截止日在当天时 ends_today=True。"""
    bundle = _bundle()
    state = service.shop_state(bundle, datetime(2026, 10, 18, 12, 0, tzinfo=TZ))
    assert state["state"] == "open" and state["days_left"] == 4 and state["ends_today"] is False
    assert state["ends_at"].startswith("2026-10-22T13:59")

    # 10-21 14:00：截止是"明天"，所以不算当天，且不足整天也至少报 1 天
    one_day = service.shop_state(bundle, datetime(2026, 10, 21, 14, 0, tzinfo=TZ))
    assert one_day["days_left"] == 1 and one_day["ends_today"] is False

    last_day = service.shop_state(bundle, datetime(2026, 10, 22, 2, 0, tzinfo=TZ))
    assert last_day["ends_today"] is True and last_day["days_left"] == 1

    closed = service.shop_state(bundle, datetime(2026, 10, 22, 14, 0, tzinfo=TZ))
    assert closed["state"] == "closed" and closed["days_left"] is None


def test_event_view_carries_lifecycle_fields_and_keeps_the_snapshot(schedule_env) -> None:
    """视图带上生命周期字段；同时**保留**最后阶段 / 关卡快照，折叠区还能看复盘资料。"""
    view = service.build_event_view(_bundle(), datetime(2026, 10, 18, 12, 0, tzinfo=TZ))

    assert view["event_status"] == service.STATUS_ENDED_SHOP_OPEN
    assert view["quests_closed_at"].startswith("2026-10-15T13:59")
    assert view["shop"]["days_left"] == 4
    assert "current_phase" in view and "available_quests" in view
    assert "upcoming_quests" in view and "next_phase" in view


@pytest.fixture()
def schedule_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GAME_ASSISTANT_KB_DIR", tmp_path)
    return tmp_path


def _bundle() -> domain.EventBundle:
    return domain.EventBundle(
        event_id="e-current",
        revision=1,
        server="CN",
        title="当前活动",
        starts_at=datetime(2026, 10, 8, 18, 0, tzinfo=TZ),
        ends_at=datetime(2026, 10, 15, 13, 59, tzinfo=TZ),
        exchange_ends_at=datetime(2026, 10, 22, 13, 59, tzinfo=TZ),
        sources=[
            domain.SourceCitation(
                source_id="S1",
                title="官方公告",
                url="https://example.invalid/1",
                source_type="official",
                publisher="bilibili",
                fetched_at=datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc),
                confidence=0.9,
                verification_status="verified",
            )
        ],
    )


def test_upsert_loads_and_only_confirmed_is_used(schedule_env) -> None:
    now = datetime(2026, 10, 14, 12, 0, tzinfo=TZ)
    schedule.upsert_event({"event_id": "cand", "title": "候选活动",
                           "starts_at": (now + timedelta(days=1)).isoformat()})
    schedule.upsert_event({"event_id": "ok", "title": "已确认活动",
                           "starts_at": (now + timedelta(days=2)).isoformat()}, confirm=True)

    items = schedule.load_schedule()
    assert [item.event_id for item in items] == ["cand", "ok"]
    assert schedule.load_schedule()[1].status == schedule.STATUS_CONFIRMED
    assert [item.event_id for item in schedule.confirmed_events(now)] == ["ok"]
    assert schedule.next_confirmed_event(now).event_id == "ok"


def test_finished_or_unconfirmed_events_are_not_offered(schedule_env) -> None:
    now = datetime(2026, 10, 14, 12, 0, tzinfo=TZ)
    schedule.upsert_event({"event_id": "past", "title": "过期活动",
                           "ends_at": (now - timedelta(days=1)).isoformat()}, confirm=True)
    schedule.upsert_event({"event_id": "cand", "title": "没核对的",
                           "starts_at": (now + timedelta(days=1)).isoformat()})

    assert schedule.confirmed_events(now) == []
    assert schedule.next_confirmed_event(now) is None


def test_current_main_event_ignores_active_campaigns(schedule_env) -> None:
    now = datetime(2026, 10, 23, 15, 0, tzinfo=TZ)
    schedule.upsert_event(
        {
            "event_id": "campaign",
            "title": "同期纪念活动",
            "event_kind": "campaign",
            "starts_at": "2026-10-20T19:00:00+08:00",
            "ends_at": "2026-12-20T13:59:00+08:00",
        },
        confirm=True,
    )
    schedule.upsert_event(
        {
            "event_id": "official-18491",
            "title": "终结·万圣节2026",
            "event_kind": "main",
            "starts_at": "2026-10-22T19:00:00+08:00",
            "ends_at": "2026-11-12T13:59:00+08:00",
        },
        confirm=True,
    )

    assert [item.event_id for item in schedule.current_confirmed_events(now)] == [
        "campaign",
        "official-18491",
    ]
    assert schedule.current_main_event(now).event_id == "official-18491"
    assert schedule.upcoming_confirmed_events(now) == []


def test_delete_and_broken_file(schedule_env) -> None:
    schedule.upsert_event({"event_id": "x", "title": "x"}, confirm=True)
    assert schedule.delete_event("x") is True
    assert schedule.delete_event("x") is False
    assert schedule.load_schedule() == []
    schedule.schedule_path().write_text("{ not json", encoding="utf-8")
    assert schedule.load_schedule() == []


def test_intent_routes_next_event_questions() -> None:
    assert service._guide_intent("下一个活动是什么？") == "next_event"
    assert service._guide_intent("接下来有什么活动") == "next_event"
    assert service._guide_intent("这期活动怎么打") == "general"
    assert service._guide_intent("90++ 组队怎么配") == "team_recommendation"


def test_next_event_answer_says_nothing_confirmed(schedule_env) -> None:
    draft = service._template_next_event(_bundle(), "下一个活动是什么", datetime(2026, 10, 14, 12, 0, tzinfo=TZ))
    bullets = [bullet for section in draft.sections for bullet in section.bullets]
    assert any("暂无已确认的后续活动日程" in bullet for bullet in bullets)
    assert draft.warnings and "不许" in "".join(draft.warnings) or "不要用日服进度" in "".join(draft.warnings)
    assert "当前活动" in "".join(bullets)


def test_next_event_answer_lists_confirmed_events(schedule_env) -> None:
    now = datetime(2026, 10, 14, 12, 0, tzinfo=TZ)
    schedule.upsert_event(
        {"event_id": "next", "title": "下期活动", "starts_at": (now + timedelta(days=1)).isoformat(),
         "ends_at": (now + timedelta(days=10)).isoformat(), "source_title": "官方公告 2026-10-14"},
        confirm=True,
    )
    draft = service._template_next_event(_bundle(), "下一个活动", now)
    bullets = [bullet for section in draft.sections for bullet in section.bullets]
    assert any("下期活动" in bullet and "官方公告 2026-10-14" in bullet for bullet in bullets)
    assert not draft.warnings


def test_next_event_plan_does_not_reuse_current_event_steps(schedule_env) -> None:
    now = datetime(2026, 10, 14, 12, 0, tzinfo=TZ)
    schedule.upsert_event(
        {
            "event_id": "next",
            "title": "下期活动",
            "starts_at": (now + timedelta(days=1)).isoformat(),
            "ends_at": (now + timedelta(days=10)).isoformat(),
        },
        confirm=True,
    )
    plan = service._build_plan(_bundle(), "下一个活动", now)
    assert plan.title == "接下来的活动日程"
    assert [step.title for step in plan.steps] == ["下期活动"]
    assert all(not step.step_id.startswith("phase-") for step in plan.steps)
    assert all(step.availability == "upcoming" for step in plan.steps)
    assert any("只列日程" in warning for warning in plan.warnings)


def test_schedule_api_roundtrip(client, schedule_env) -> None:
    base = "/api/game-assistant/fgo/schedule"
    assert client.get(base).json()["confirmed_count"] == 0

    created = client.post(base, json={
        "event_id": "e-next", "title": "下期活动", "starts_at": "2026-10-16T18:00:00",
        "source_title": "官方公告", "confirm": True,
    })
    assert created.status_code == 200
    assert created.json()["item"]["status"] == "confirmed"

    listing = client.get(base).json()
    assert listing["confirmed_count"] == 1 and listing["items"][0]["event_id"] == "e-next"

    candidate = client.post(base, json={"event_id": "e-cand", "title": "候选", "confirm": False})
    assert candidate.json()["item"]["status"] == "candidate"
    assert client.get(base).json()["confirmed_count"] == 1

    assert client.delete(f"{base}/e-cand").json()["deleted"] is True
    assert client.delete(f"{base}/e-cand").json()["deleted"] is False


def test_refresh_from_official_endpoint(client, schedule_env, monkeypatch) -> None:
    """`POST /schedule/refresh-from-official`：把采集汇总原样回给界面（这里把抓取换成假的）。"""
    from game_assistant import announcement_feed

    def fake_refresh(*, limit: int = 12, **kwargs):   # noqa: ARG001
        return {"added": [{"event_id": "official-18453", "title": "X"}], "updated": [],
                "skipped": [], "errors": [], "checked": 1, "candidate_total": 1}

    monkeypatch.setattr(announcement_feed, "refresh_schedule", fake_refresh)
    response = client.post("/api/game-assistant/fgo/schedule/refresh-from-official")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["added"][0]["event_id"] == "official-18453"
    assert payload["errors"] == []


def test_schedule_endpoint_carries_upcoming_and_japanese_reference(client, schedule_env, monkeypatch) -> None:
    """`GET /schedule` 给页面的三样东西：全部条目、**下个活动**（confirmed 且未结束）、日服参考。"""
    from game_assistant import mooncell_events

    schedule.upsert_event(
        {
            "event_id": "official-18453",
            "title": "「冠位戴冠战：Assassin」开幕（常驻）",
            "starts_at": "2026-10-23T19:00:00+08:00",
            "ends_at": "2026-12-31T13:59:00+08:00",
        },
        confirm=True,
    )
    schedule.upsert_event({"event_id": "official-1", "title": "候选", "starts_at": "2026-10-20T19:00:00+08:00"})
    monkeypatch.setattr(
        mooncell_events, "japanese_reference",
        lambda now=None: {"items": [{"title": "日服同期"}], "note": "日服·参考，不代表国服排期"},
    )

    payload = client.get("/api/game-assistant/fgo/schedule").json()

    assert payload["confirmed_count"] == 1
    assert [item["event_id"] for item in payload["confirmed_upcoming"]] == ["official-18453"]
    assert payload["japanese_reference"]["items"][0]["title"] == "日服同期"
    assert "不代表国服排期" in payload["japanese_reference"]["note"]
