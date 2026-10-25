"""固定轮转 → 手册 的回归测试（执行链路第 2 步）。"""
from __future__ import annotations

import pytest

from game_assistant.combat_simulator import simulate
from game_assistant.combat_domain import SimulationRequest
from game_assistant.combat_store import CombatStore
from game_assistant.rotation_runbook import build_plan, render_runbook

QUEST = "fgo-cn-2026-gudaguda9-90pp"


def _spec() -> dict:
    return {
        "quest_id": QUEST,
        "title": "轮转测试",
        "team": [
            {
                "name": "U－奥尔加玛丽",
                "class_name": "Beast",
                "level": 110,
                "np_level": 5,
                "skills": [10, 10, 10],
                "ce_name": "倍卡礼装（满破）",
                "ce_damage_up": 1.0,
                "ce_start_np": 0.5,
            },
            {"name": "梅林", "class_name": "Caster", "level": 90},
            {"name": "光之高扬斯卡娅", "class_name": "Assassin", "level": 90},
        ],
        "steps": [
            {"turn": 1, "actor": "光之高扬斯卡娅", "kind": "skill", "skill": "NFF特别服务 A", "target": "U－奥尔加玛丽"},
            {"turn": 1, "actor": "U－奥尔加玛丽", "kind": "skill", "skill": "惊天动地 B"},
            {"turn": 1, "actor": "U－奥尔加玛丽", "kind": "np"},
            {"turn": 2, "actor": "U－奥尔加玛丽", "kind": "np"},
            {"turn": 2, "actor": "U－奥尔加玛丽", "kind": "card", "card": "buster", "position": 2, "crit": True},
        ],
    }


def test_build_plan_from_rotation_spec() -> None:
    if CombatStore().get_profile(QUEST) is None:
        pytest.skip("缺少 90++ 战斗档案")
    plan, profile = build_plan(_spec())
    assert plan.quest_id == QUEST
    assert len(plan.combatants) == 3
    assert profile.total_enemy_hp == 1_639_409
    kinds = [action.action_type for action in plan.actions]
    assert kinds.count("np") == 2 and kinds.count("attack") == 1
    # 礼装被翻译成计划效果：伤害 +100% 与开局 +50% 宝具值
    ce_actions = [action for action in plan.actions if "倍卡" in action.skill_id]
    assert len(ce_actions) == 2


def test_runbook_reports_the_three_checks() -> None:
    if CombatStore().get_profile(QUEST) is None:
        pytest.skip("缺少 90++ 战斗档案")
    spec = _spec()
    plan, profile = build_plan(spec)
    result = simulate(SimulationRequest(profile=profile, plan=plan))
    text = render_runbook(spec, plan, profile, result)
    assert "## 校验" in text
    assert "伤害（最小 roll）" in text
    assert "1,639,409" in text, "必须写明副本需要的总血量"
    assert "暴击卡" in text and "充能来源" in text
    assert "实际伤害高于本估算" in text, "必须标注模型的保守偏差"
