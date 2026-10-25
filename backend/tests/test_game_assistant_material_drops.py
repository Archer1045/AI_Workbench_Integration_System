"""Mooncell 素材掉落 top3 关卡库测试（2026-10-11）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import config
from game_assistant import mooncell_drops

_SAMPLE_ROW = (
    '<tr>'
    '<td><span typeof="mw:File"><a href="/w/X" title="测试素材"></a></span></td>'
    '<td><a href="/w/X" title="测试素材">测试素材<br /><span lang="ja">テスト</span></a></td>'
    '<td><span class="道具一览&#95;铜素材&#95;1">【说明】测试用</span></td>'
    '<td class="nomobile">'
    '<a href="/w/第一章/关卡配置#自由关卡" title="第一章/关卡配置">第一章</a> '
    '<a href="/w/第一章/关卡配置#甲关" title="第一章/关卡配置">甲关</a> '
    '<span style="white-space:nowrap">( 20.5 AP / 55.5% )</span><br />'
    '<a href="/w/第二章/关卡配置#自由关卡" title="第二章/关卡配置">第二章</a> '
    '<a href="/w/第二章/关卡配置#乙关" title="第二章/关卡配置">乙关</a> '
    '<span style="white-space:nowrap">( 21 AP / 44.4% )</span>'
    '</td></tr>'
)


def _load() -> dict:
    target = Path(config.GAME_ASSISTANT_KB_DIR) / mooncell_drops.OUTPUT_FILENAME
    if not target.exists():
        pytest.skip("本机还没有掉落库（需先跑 python -m game_assistant.mooncell_drops）")
    return json.loads(target.read_text(encoding="utf-8"))


def test_parse_row_extracts_top3_entries() -> None:
    """渲染行的解析：章节 + 关卡名 + 消耗 AP + 掉落率，顺序即排名。"""
    parsed = mooncell_drops.parse_row(_SAMPLE_ROW)
    assert parsed is not None
    assert parsed["material"] == "测试素材"
    assert parsed["category"] == "铜素材"
    assert parsed["desc"].startswith("【说明】")
    assert [entry["rank"] for entry in parsed["entries"]] == [1, 2]
    first = parsed["entries"][0]
    assert first["chapter"] == "第一章"
    assert first["quests"] == ["甲关"]
    assert first["ap"] == 20.5
    assert first["rate"] == 55.5


def test_parse_row_skips_rows_without_drops() -> None:
    assert mooncell_drops.parse_row('<tr><td><a href="/w/X" title="无掉落"></a></td></tr>') is None


def test_library_covers_materials_with_plausible_rates() -> None:
    payload = _load()
    items = payload["items"]
    assert len(items) >= 100, "应覆盖 100+ 个素材（技能石/棋子/铜银金素材）"
    assert all(1 <= len(item["entries"]) <= 3 for item in items)
    for item in items:
        for entry in item["entries"]:
            assert entry["chapter"], f"{item['material']} 的条目缺少章节"
            assert entry["ap"] > 0
            # wiki 的掉落率可以超过 100%（一次战斗可掉多个），只校验它是正数
            assert entry["rate"] > 0


def test_drops_for_material_resolves_alias_and_missing_names() -> None:
    payload = _load()
    dust = mooncell_drops.drops_for_material(payload, "虚影之尘")
    assert dust and dust[0]["rate"] >= dust[-1]["rate"], "top1 掉落率应不低于后面几名"
    assert mooncell_drops.drops_for_material(payload, "凶骨"), "凶骨应可查"
    assert mooncell_drops.drops_for_material(payload, "祸骨"), "Atlas 写法「祸骨」应能归一到凶骨"
    assert mooncell_drops.drops_for_material(payload, "不存在的素材") == []
