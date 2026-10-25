"""御主礼装建模：充能、卡色增伤、出星与选择偏好。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from game_assistant.mystic_code import MysticCodeTable


def _table(tmp_path: Path) -> MysticCodeTable:
    entries = {
        "mystic_codes": [
            {
                "name": "充能礼装",
                "skills": [
                    {
                        "name": "灵子转让",
                        "cooldown": "15→14→13",
                        "effects": [{"text": "己方单体的NP增加", "values": ["20%"]}],
                    }
                ],
            },
            {
                "name": "红绿卡礼装",
                "skills": [
                    {
                        "name": "壬生浪式精神",
                        "cooldown": "15→14→13",
                        "effects": [
                            {
                                # Mooncell 每个效果固定 10 个值，按等级取（Lv1..Lv10）。
                                "text": "己方全体的Quick指令卡性能提升(1回合)",
                                "values": [
                                    "10%",
                                    "11%",
                                    "12%",
                                    "13%",
                                    "14%",
                                    "15%",
                                    "16%",
                                    "17%",
                                    "18%",
                                    "20%",
                                ],
                            },
                            {
                                "text": "Buster指令卡性能提升(1回合)",
                                "values": [
                                    "10%",
                                    "11%",
                                    "12%",
                                    "13%",
                                    "14%",
                                    "15%",
                                    "16%",
                                    "17%",
                                    "18%",
                                    "20%",
                                ],
                            },
                        ],
                    }
                ],
            },
            {
                "name": "全体出星礼装",
                "skills": [
                    {
                        "name": "小小的礼物",
                        "cooldown": "9→8→7",
                        "effects": [
                            {"text": "获得暴击星", "values": [str(value) for value in range(6, 16)]},
                            {"text": "己方全体的NP小幅增加", "values": ["5%"]},
                        ],
                    }
                ],
            },
        ]
    }
    owned = {
        "mystic_codes": [
            {"name": "充能礼装", "level": 10},
            {"name": "红绿卡礼装", "level": 6},
            {"name": "全体出星礼装", "level": 10},
        ]
    }
    table_path = tmp_path / "mc_table.json"
    owned_path = tmp_path / "mc_owned.json"
    table_path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    owned_path.write_text(json.dumps(owned, ensure_ascii=False), encoding="utf-8")
    return MysticCodeTable(table_path=table_path, owned_path=owned_path)


def test_np_increase_maps_to_charge(tmp_path: Path) -> None:
    profile = _table(tmp_path).profile("充能礼装", 10)
    assert profile is not None
    assert profile.charge_for() == pytest.approx(0.20)
    assert profile.effects[0].target == "ally_one"


def test_card_buffs_are_card_restricted_and_use_mc_level(tmp_path: Path) -> None:
    """Lv6 的浅葱的队服应为 Quick/Buster 各 +15%，且只对对应卡色生效。"""
    profile = _table(tmp_path).profile("红绿卡礼装", 6)
    assert profile is not None
    assert profile.buff_sum("quick") == pytest.approx(0.15)
    assert profile.buff_sum("buster") == pytest.approx(0.15)
    assert profile.buff_sum("arts") == pytest.approx(0.0)


def test_party_charge_and_stars(tmp_path: Path) -> None:
    profile = _table(tmp_path).profile("全体出星礼装", 10)
    assert profile is not None
    assert profile.charge_for() == pytest.approx(0.05)
    assert all(effect.target == "ally_all" for effect in profile.effects if effect.kind == "charge")
    assert profile.stars() == pytest.approx(15)


def test_best_for_prefers_charge_over_buffs(tmp_path: Path) -> None:
    """用户偏好：优先用免费的充能，再考虑增伤。"""
    best = _table(tmp_path).best_for("quick", 1.0)
    assert best is not None
    assert best.name == "充能礼装"


def test_missing_table_is_reported_not_guessed(tmp_path: Path) -> None:
    table = MysticCodeTable(table_path=tmp_path / "missing.json", owned_path=tmp_path / "missing_owned.json")
    assert table.available() is False
    assert table.profiles() == []
