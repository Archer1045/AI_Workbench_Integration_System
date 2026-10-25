"""第三步：单体宝具与光炮宝具必须区别对待。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from game_assistant.combat_domain import (
    CombatantSnapshot,
    SimulationRequest,
    TeamPlan,
    TeamPlanAction,
)
from game_assistant.combat_simulator import simulate
from game_assistant.quest_profile_import import build_profile, find_quest_section, parse_quest_section
from game_assistant.servant_stats import ServantStatsStore, get_servant_stats

SECTION_HTML = Path(__file__).resolve().parent / "data" / "mooncell_90pp_section.html"
ATLAS_CACHE = Path(
    os.environ.get("FGO_ATLAS_CACHE", r"D:\workSpace\code\_research\fgo-py\atlas_cache\nice_servant_cn.json")
)


def _profile():
    html = SECTION_HTML.read_text(encoding="utf-8")
    parsed = parse_quest_section(find_quest_section(html, "神剑改_燃烧吧翡翠剑"))
    return build_profile(
        parsed,
        quest_id="test-np-target",
        event_id="test-event",
        quest_name="测试关卡",
        source_ids=["src-test"],
    )


def _plan(np_target: str, attack: float = 20000) -> TeamPlan:
    return TeamPlan(
        plan_id=f"test-{np_target}",
        quest_id="test-np-target",
        title="单体/光炮测试",
        combatants=[
            CombatantSnapshot(
                actor_slot=1,
                servant_record_id="test-1",
                name="测试打手",
                class_name="Assassin",
                attack=attack,
                hp=10000,
                class_relation="advantage",
                np_multiplier=10.0,
                np_target=np_target,  # type: ignore[arg-type]
            )
        ],
        actions=[
            TeamPlanAction(
                action_id=f"t{turn}-np",
                order=turn,
                turn=turn,
                actor_slot=1,
                action_type="np",
            )
            for turn in (1, 2, 3)
        ],
    )


def test_single_target_np_hits_only_the_toughest_enemy_in_the_wave() -> None:
    """第 2 面有 47.5 万 + 4 万两个敌人，单体宝具只应命中血量最高的那个。"""
    profile = _profile()
    result = simulate(SimulationRequest(profile=profile, plan=_plan("single")))
    # 第 1 回合清掉第 1 面；之后每次单体宝具都只指向第 2 面血量最高的敌人，
    # 低血量的 w2_02 永远不该被单体宝具选中。
    wave_two_gates = [gate for gate in result.damage_gates if gate.enemy_id.startswith("w2")]
    assert wave_two_gates, "单体宝具应当命中第 2 面的目标"
    assert {gate.enemy_id for gate in wave_two_gates} == {"w2_01"}


def test_area_np_hits_every_enemy_in_the_wave() -> None:
    profile = _profile()
    result = simulate(SimulationRequest(profile=profile, plan=_plan("area")))
    # 第 1 回合清掉第 1 面，第 2 回合的光炮同时命中该面两个敌人
    wave_two_gates = [gate for gate in result.damage_gates if gate.enemy_id.startswith("w2")]
    assert {gate.enemy_id for gate in wave_two_gates} == {"w2_01", "w2_02"}


@pytest.mark.skipif(not ATLAS_CACHE.exists(), reason="本机未找到 Atlas 缓存")
def test_catalog_np_target_classification() -> None:
    """判定必须取自伤害函数的 funcTargetType，而不是设定名。"""
    store = get_servant_stats()
    assert (store.find("迦摩", "Assassin") or {}).get("np_target") == "single"
    assert (store.find("卡米拉", "Assassin") or {}).get("np_target") == "single"
    assert (store.find("光之高扬斯卡娅", "Assassin") or {}).get("np_target") == "area"
    # 设定名写「对人宝具」，实际伤害函数是 enemyAll —— 必须是光炮。
    lily = store.find("阿尔托莉雅·潘德拉贡〔Lily〕", "Saber")
    assert lily is not None
    assert lily["np_target_type"] == "对人宝具"
    assert lily["np_target"] == "area"
