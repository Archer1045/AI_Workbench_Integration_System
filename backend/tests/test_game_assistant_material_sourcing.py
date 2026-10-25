"""素材获取查询（掉落 + 活动）测试（2026-10-11）。"""
from __future__ import annotations

import base64

from game_assistant.material_sourcing import material_sourcing


def test_heart_sourcing_returns_free_quests_and_notes() -> None:
    result = material_sourcing("蛮神心脏")
    assert result["material"] == "蛮神心脏"
    assert result["free_quests"], "蛮神心脏应有掉落关卡"
    top = result["free_quests"][0]
    assert top["chapter"] and top["ap"] > 0 and top["rate"] > 0
    # wiki 数据的口径与时效必须随答案一起给出
    assert any("100%" in note for note in result["notes"])
    assert result["sources"]["free_quests"]["age_days"] is not None


def test_material_without_event_route_says_so() -> None:
    """英雄之证：活动路线给不了它，答案必须明说，而不是留空。"""
    result = material_sourcing("英雄之证")
    assert result["free_quests"], "英雄之证应有掉落关卡"
    if not result["events"]["cn"] and not result["events"]["jp"]:
        assert any("活动路线" in note for note in result["notes"])


def test_alias_names_query_the_same_material() -> None:
    """Atlas 写「祸骨」、Mooncell 写「凶骨」，两种写法都要能查到掉落。"""
    atlas = material_sourcing("祸骨")
    wiki = material_sourcing("凶骨")
    assert atlas["free_quests"] and wiki["free_quests"]
    assert atlas["free_quests"][0]["chapter"] == wiki["free_quests"][0]["chapter"]
    assert "凶骨" in atlas["queried_names"]


def test_unknown_material_reports_missing_data() -> None:
    result = material_sourcing("并不存在的素材")
    assert result["free_quests"] == []
    assert any("108 项" in note for note in result["notes"])


def test_material_sourcing_endpoint(client) -> None:
    response = client.get(
        "/api/game-assistant/fgo/material-sourcing", params={"material": "虚影之尘"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["free_quests"], "接口应返回掉落关卡"
    assert payload["free_quests"][0]["rate"] > 0


def test_material_sourcing_endpoint_rejects_empty(client) -> None:
    response = client.get("/api/game-assistant/fgo/material-sourcing", params={"material": "  "})
    assert response.status_code == 400
