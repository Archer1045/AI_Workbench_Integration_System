"""Mooncell 活动表 → 日服同期参考 的回归测试（不联网，页面片段是手工缩的小样）。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import config
from game_assistant import mooncell_events

TZ = timezone(timedelta(hours=8))

PAGE = (
    "<h2>未来活动 [ 编辑 ]</h2><table>"
    "<tr><th>活动时间<br>（日本标准时间）</th><th>名称</th><th>公告页面</th><th>类型</th></tr>"
    "<tr><td>2025年10月22日(周三)20:00</td><td>2025年11月12日(周三)12:59</td>"
    "<td>最终·万圣节2025 ～南瓜行星上闪耀的歌姬～</td><td>Event</td></tr>"
    "<tr><td>2026年8月3日(周一)18:00</td><td>～？</td>"
    "<td>从者强化任务 第20弹</td><td>Other</td></tr>"
    "</table>"
    "<h2>2026年 [ 编辑 ]</h2><table>"
    "<tr><th>活动时间</th><th>名称</th><th>公告页面</th><th>类型</th></tr>"
    "<tr><td>2026年10月13日(周二)19:00</td><td>2026年12月20日(周日)13:59</td>"
    "<td>Final Order Project [Ordeal Call Ⅲ]通关应援纪念活动</td><td>Campaign</td></tr>"
    "</table>"
)


def test_parse_page_splits_sections_and_rows() -> None:
    items = mooncell_events.parse_page(PAGE)

    assert [(item["server"], item["type"]) for item in items] == [
        ("jp", "Event"), ("jp", "Other"), ("cn", "Campaign"),
    ]
    halloween = items[0]
    assert halloween["title"].startswith("最终·万圣节2025")
    assert halloween["starts_at"].startswith("2025-10-22T20:00")
    assert halloween["ends_at"].startswith("2025-11-12T12:59")
    assert items[1]["ends_at"] is None, "「～？」= 没写结束时间"
    assert items[2]["starts_at"].startswith("2026-10-13T19:00")


def test_refresh_cache_writes_and_loads(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_KB_DIR", tmp_path)

    summary = mooncell_events.refresh_cache(html=PAGE, now=datetime(2026, 10, 15, 12, 0, tzinfo=TZ))

    assert summary["ok"] is True and summary["jp"] == 2 and summary["cn"] == 1
    assert mooncell_events.cache_path().exists()
    cache = mooncell_events.load_cache()
    assert len(cache["items"]) == 3 and cache["fetched_at"].startswith("2026-10-15T12:00")


def test_refresh_cache_keeps_old_cache_when_the_page_looks_wrong(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_KB_DIR", tmp_path)
    mooncell_events.refresh_cache(html=PAGE)

    broken = mooncell_events.refresh_cache(html="<html><body>页面改版了</body></html>")

    assert broken["ok"] is False and "0 条" in broken["error"]
    assert len(mooncell_events.load_cache()["items"]) == 3, "解析失败要保留旧缓存"


def test_japanese_reference_only_picks_jp_items_near_a_year_ago(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_KB_DIR", tmp_path)
    payload = {
        "version": 1,
        "fetched_at": "2026-10-15T12:00:00+08:00",
        "items": [
            {"server": "jp", "title": "万圣节2025 开幕前夕", "starts_at": "2025-10-17T18:00:00+08:00",
             "ends_at": None, "type": "Campaign"},
            {"server": "jp", "title": "今年的日服活动", "starts_at": "2026-10-20T18:00:00+08:00",
             "ends_at": None, "type": "Event"},
            {"server": "cn", "title": "国服同期条目", "starts_at": "2025-10-17T18:00:00+08:00",
             "ends_at": None, "type": "Event"},
        ],
    }
    (tmp_path / "mooncell_events.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    reference = mooncell_events.japanese_reference(datetime(2026, 10, 15, 12, 0, tzinfo=TZ))

    assert [item["title"] for item in reference["items"]] == ["万圣节2025 开幕前夕"]
    assert reference["anchor"] == "2025-10-15"
    assert "不代表国服排期" in reference["note"]


def test_japanese_reference_is_empty_without_a_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_KB_DIR", tmp_path)
    reference = mooncell_events.japanese_reference(datetime(2026, 10, 15, 12, 0, tzinfo=TZ))
    assert reference["items"] == [] and "不代表国服排期" in reference["note"]
