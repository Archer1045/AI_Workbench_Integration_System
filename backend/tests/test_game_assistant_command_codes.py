"""指令纹章效果解析与接入（第 5 步尾巴）测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import config
from game_assistant import command_codes


def _library() -> dict:
    target = Path(config.GAME_ASSISTANT_KB_DIR) / "command_codes_cn.json"
    if not target.exists():
        pytest.skip("本机没有纹章库")
    return json.loads(target.read_text(encoding="utf-8"))


def test_parse_real_command_codes_from_text() -> None:
    """效果写在 detail 文本里，必须按文本解析（结构化字段是空的）。"""
    payload = _library()
    cases = {
        "花之魔术师": {"charge": 10.0},
        "纹章：爆裂": {"critical_up": 3.0},
        "信选组": {"critical_up": 15.0},
        "龙爪如湖光": {"critical_up": 10.0, "stars": 2.0},
    }
    for name, expected in cases.items():
        parsed = command_codes.code_effects(payload, name)
        assert parsed["found"], f"库里应有 {name}"
        for key, value in expected.items():
            assert parsed["effects"].get(key) == pytest.approx(value), f"{name} 的 {key}"


def test_code_with_card_restriction_records_the_colour() -> None:
    payload = _library()
    quick_only = command_codes.code_effects(payload, "信选组")
    assert quick_only["card"] == "quick"
    arts_only = command_codes.code_effects(payload, "上校型自动人偶")
    assert arts_only["card"] == "arts"
    assert command_codes.code_effects(payload, "花之魔术师")["card"] == ""


def test_unknown_code_is_not_guessed() -> None:
    parsed = command_codes.code_effects({}, "并不存在的纹章")
    assert parsed["found"] is False and parsed["effects"] == {}


def test_best_critical_code_respects_card_restriction_and_picks_strongest() -> None:
    payload = _library()
    names = ["信选组", "纹章：爆裂"]
    # 迅卡：信选组 +15% 胜出
    assert command_codes.best_critical_code(payload, names, "quick")["name"] == "信选组"
    # 力卡：信选组受"仅当刻印在迅指令卡上"限制，改用通用的爆裂 +3%
    buster = command_codes.best_critical_code(payload, names, "buster")
    assert buster["name"] == "纹章：爆裂"
    # 什么都没指定 → 不加成
    assert command_codes.best_critical_code(payload, [], "buster") is None


def test_assumed_effects_include_stars_focus_and_crit_damage_once() -> None:
    payload = {
        "items": [
            {"name": "出星", "detail": "使用被刻印的指令卡攻击时，获得 10 个暴击星"},
            {"name": "集中", "detail": "使用被刻印的指令卡攻击时，暴击星集中度提升 300%"},
            {"name": "暴伤", "detail": "使用被刻印的指令卡攻击时，暴击威力提升 20%"},
        ]
    }
    summary = command_codes.assumed_command_code_effects(
        payload, ["出星", "集中", "暴伤", "出星"], "buster"
    )
    assert summary["stars"] == [{"name": "出星", "value": 10.0}]
    assert summary["focus"] == {"name": "集中", "value": 300.0}
    assert summary["critical"] == {"name": "暴伤", "value": 20.0}
