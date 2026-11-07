"""官方公告 → 候选日程（announcement_feed）的回归测试。

不联网：列表 / 正文抓取都从参数注入。硬要求：只落 candidate、confirmed 不动、幂等、抽不到时间就不猜。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config
from game_assistant import announcement_feed, schedule

TZ = timezone(timedelta(hours=8))


def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GAME_ASSISTANT_KB_DIR", tmp_path)
    return tmp_path


# 真实公告的写法（2026-10-15 抓下来的两条）
ASSASSIN_TITLE = "「冠位戴冠战：Assassin」开幕！"
ASSASSIN_BODY = (
    "伴随Assassin职阶的冠位肖像解放，「冠位戴冠战：Assassin」开幕！"
    "「冠位戴冠战：Assassin」将常驻开放，但在2026年10月22日（周四）13:59之前，"
    "挑战无需消耗「风暴罐」。开放时间 2026年10月15日（周四）维护后~"
)
SUMMON_TITLE = "【限时】「唠唠叨叨新选组 THE END推荐召唤4」！"
MAINTENANCE_TITLE = "活动维护公告（2026年10月15日 14时）"


def test_classify_separates_events_from_pools_and_maintenance() -> None:
    assert announcement_feed.classify(ASSASSIN_TITLE) == "event"
    assert announcement_feed.classify("【限时】「Final Order Project [Ordeal Call III]通关应援纪念活动」举办！") == "event"
    assert announcement_feed.classify(SUMMON_TITLE) == "summon"
    assert announcement_feed.classify(MAINTENANCE_TITLE) == "maintenance"
    assert announcement_feed.classify("《FGO》手游随机抽取类玩法概率公示") == "other"


def test_parse_window_uses_the_marked_section_and_admits_a_missing_end() -> None:
    """只在「活动时间 / 开放时间」段落里取窗口；段落里只有一个日期就如实说"结束待核对"。"""
    starts_at, ends_at, notes = announcement_feed.parse_window(ASSASSIN_BODY)
    assert starts_at == datetime(2026, 10, 15, 0, 0, tzinfo=TZ)
    assert ends_at is None, "冠位戴冠战是常驻，公告的「开放时间」只有一个日期"
    assert any("开放时间" in note and "人工核对" in note for note in notes)
    assert any("维护后" in note for note in notes), "只有日期时要如实标注"


def test_parse_window_handles_a_same_line_range_without_the_year() -> None:
    """`2026年9月24日…维护后~10月15日…13:59为止`：第二个日期不带年份也要认。"""
    body = (
        "限时活动开幕！\n◆ 活动时间（为期3周） ◆ "
        "2026年9月24日（周四）维护后~10月15日（周四）13:59为止 \n◆ 活动参加条件 ◆ 通关第2部"
    )

    starts_at, ends_at, notes = announcement_feed.parse_window(body)

    assert starts_at == datetime(2026, 9, 24, 0, 0, tzinfo=TZ)
    assert ends_at == datetime(2026, 10, 15, 13, 59, tzinfo=TZ)
    assert any("活动时间" in note for note in notes)


def test_parse_window_leaves_the_window_empty_without_a_marker_section() -> None:
    """标不出段落 ⇒ **不给窗口**（宁可让人工填，也不把卡池、领取期的日期算进活动窗口）。"""
    body = "本次活动详情：卡池 2026年10月15日 19:00 ~ 2026年12月31日 23:59 结束。"
    starts_at, ends_at, notes = announcement_feed.parse_window(body)
    assert starts_at is None and ends_at is None
    assert any("没有「活动时间" in note for note in notes)


def test_parse_window_refuses_to_guess_when_there_is_no_date() -> None:
    starts_at, ends_at, notes = announcement_feed.parse_window("本次活动详情请以游戏内为准。")
    assert starts_at is None and ends_at is None
    assert notes and "待人工核对" in notes[0]


def _fake_list(page_size: int = 30):   # noqa: ARG001 - 与真实签名一致
    return [
        {"id": 18453, "title": ASSASSIN_TITLE, "create_time": "2026-10-13 11:03:33"},
        {"id": 18452, "title": MAINTENANCE_TITLE, "create_time": "2026-10-13 10:59:04"},
        {"id": 18407, "title": SUMMON_TITLE, "create_time": "2026-09-24 11:15:16"},
    ]


def _fake_detail(news_id: int) -> dict:
    return {"id": news_id, "title": ASSASSIN_TITLE, "body": ASSASSIN_BODY}


def test_refresh_adds_candidates_only_and_is_idempotent(tmp_path, monkeypatch) -> None:
    _env(tmp_path, monkeypatch)

    first = announcement_feed.refresh_schedule(
        list_fetcher=_fake_list, detail_fetcher=_fake_detail, now=datetime(2026, 10, 15, 16, 0, tzinfo=TZ)
    )
    assert [item["event_id"] for item in first["added"]] == ["official-18453"]
    assert first["errors"] == []

    items = schedule.load_schedule()
    assert [item.event_id for item in items] == ["official-18453"], "卡池与维护公告不进日程"
    assert items[0].status == schedule.STATUS_CANDIDATE, "采集只能落候选"
    assert "18453" in items[0].source_title and items[0].source_url.endswith("18453")

    second = announcement_feed.refresh_schedule(
        list_fetcher=_fake_list, detail_fetcher=_fake_detail, now=datetime(2026, 10, 15, 17, 0, tzinfo=TZ)
    )
    assert second["added"] == [] and len(second["updated"]) == 1, "重复拉不写重复条目"
    assert len(schedule.load_schedule()) == 1


def test_refresh_never_downgrades_a_confirmed_entry(tmp_path, monkeypatch) -> None:
    """人已经核对过并标了确认的条目，采集不许把它退回候选（用回归测试钉死）。"""
    _env(tmp_path, monkeypatch)
    schedule.upsert_event(
        {
            "event_id": "official-18453",
            "title": "「冠位戴冠战：Assassin」开幕（常驻）",
            "server": "CN",
            "starts_at": "2026-10-15T19:00:00+08:00",
            "ends_at": "2026-10-22T13:59:00+08:00",
            "source_title": "国服官方公告 18453",
        },
        confirm=True,
    )

    summary = announcement_feed.refresh_schedule(
        list_fetcher=_fake_list, detail_fetcher=_fake_detail, now=datetime(2026, 10, 15, 16, 0, tzinfo=TZ)
    )

    assert summary["added"] == [] and summary["updated"] == []
    assert [item["why"] for item in summary["skipped"]] == ["已确认，不动"]
    kept = schedule.load_schedule()[0]
    assert kept.status == schedule.STATUS_CONFIRMED
    assert kept.title == "「冠位戴冠战：Assassin」开幕（常驻）", "确认过的内容也不许被覆盖"


def test_refresh_skips_announcements_that_already_ended(tmp_path, monkeypatch) -> None:
    """日程是"接下来发生什么"，不是历史归档：公告里的时间已经过去的，只记进 stale。"""
    _env(tmp_path, monkeypatch)

    summary = announcement_feed.refresh_schedule(
        list_fetcher=_fake_list, detail_fetcher=_fake_detail,
        # 这条公告是"常驻"（只抽到开始时间、没有结束时间）⇒ 靠"开始时间已过 30 天"判过期
        now=datetime(2026, 12, 1, 12, 0, tzinfo=TZ),
    )

    assert summary["added"] == [] and summary["updated"] == []
    assert [item["event_id"] for item in summary["stale"]] == ["official-18453"]
    assert schedule.load_schedule() == []


MAINTENANCE_BODY = (
    "我们将于以下时间，对游戏服务器实施临时维护。\n【维护时间】\n"
    "2026年10月15日 14:00 ～ 10月15日 19:00（预计）\n【维护内容】\n"
    "1. 「冠位戴冠战：Assassin」开幕\n2. 关闭限时「幕末武斗神话」活动\n【维护补偿内容】\n圣晶石 5个"
)


def test_maintenance_window_is_parsed_and_kept_out_of_the_schedule(tmp_path, monkeypatch) -> None:
    """维护窗口单独存 `maintenance_cn.json`：进日程文件会污染「下一个活动」的回答。"""
    _env(tmp_path, monkeypatch)
    starts_at, ends_at, notes = announcement_feed.parse_maintenance_window(MAINTENANCE_BODY)
    assert starts_at == datetime(2026, 10, 15, 14, 0, tzinfo=TZ)
    assert ends_at == datetime(2026, 10, 15, 19, 0, tzinfo=TZ)
    assert any("预计" in note for note in notes)

    def fake_list(page_size: int = 30):
        return [{"id": 18452, "title": MAINTENANCE_TITLE, "create_time": "2026-10-13 10:59:04"}]

    def fake_detail(news_id: int) -> dict:
        return {"id": news_id, "title": MAINTENANCE_TITLE, "body": MAINTENANCE_BODY}

    summary = announcement_feed.refresh_schedule(
        list_fetcher=fake_list, detail_fetcher=fake_detail,
        now=datetime(2026, 10, 15, 12, 0, tzinfo=TZ),
    )

    assert summary["maintenance"][0]["announcement_id"] == "18452"
    assert announcement_feed.load_maintenance()[0]["starts_at"].startswith("2026-10-15T14:00")
    assert schedule.load_schedule() == [], "维护公告不能进活动日程"


def test_maintenance_window_is_not_guessed_when_the_notice_has_no_range(tmp_path, monkeypatch) -> None:
    _env(tmp_path, monkeypatch)
    starts_at, ends_at, notes = announcement_feed.parse_maintenance_window("维护时间请以游戏内公告为准。")
    assert starts_at is None and ends_at is None
    assert notes and "待人工核对" in notes[0]


def test_refresh_survives_a_broken_source(tmp_path, monkeypatch) -> None:
    """官网抖动 / 断网：把错误记进汇总、不抛异常（页面不该因此打不开）。"""
    _env(tmp_path, monkeypatch)

    def boom(page_size: int = 30):
        raise OSError("connection reset")

    summary = announcement_feed.refresh_schedule(list_fetcher=boom)
    assert summary["added"] == [] and summary["errors"]
    assert "拉公告列表失败" in summary["errors"][0]
