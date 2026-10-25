from __future__ import annotations

import pytest

from game_assistant.combat_domain import (
    CombatEffect,
    CombatProfile,
    CombatantSnapshot,
    EnemyUnit,
    EnemyWave,
    SimulationRequest,
    TeamPlan,
    TeamPlanAction,
)
from game_assistant.combat_recommender import common_enemy_traits, summarize_skills
from game_assistant.combat_simulator import simulate
from game_assistant.enemy_traits import apply_phase_traits


def _profile() -> CombatProfile:
    return CombatProfile(
        quest_id="test-traits",
        event_id="test-event",
        quest_name="特性测试",
        ap_cost=40,
        waves=[
            EnemyWave(
                wave_id="w1",
                wave_index=1,
                units=[
                    EnemyUnit(
                        enemy_id="w1_01",
                        name="大型敌人",
                        class_name="Rider",
                        level=51,
                        hp=475056,
                        notes=["出处敌人：大型敌人"],
                    ),
                    EnemyUnit(
                        enemy_id="w1_02",
                        name="小型敌人",
                        class_name="Rider",
                        level=53,
                        hp=40748,
                    ),
                ],
            )
        ],
        verified=True,
        notes=["敌人属性（天/地/人）未从该表取得，统一按默认 man 记录。"],
    )


def _payload() -> dict:
    return {
        "stages": [
            {
                "wave": 1,
                "enemies": [
                    {
                        "name": "small",
                        "lv": 53,
                        "hp": 40748,
                        "traits": [{"name": "attributeEarth"}],
                        "svt": {
                            "className": "rider",
                            "attribute": "earth",
                            "traits": [{"name": "classRider"}],
                        },
                    },
                    {
                        "name": "large",
                        "lv": 51,
                        "hp": 475056,
                        "traits": [
                            {"name": "attributeEarth"},
                            {"name": "giant"},
                            {"name": "canBeInBattle"},
                        ],
                        "svt": {
                            "className": "rider",
                            "attribute": "earth",
                            "traits": [{"name": "classRider"}],
                        },
                    },
                ],
            }
        ]
    }


def test_phase_traits_align_by_battle_row_not_list_order() -> None:
    enriched = apply_phase_traits(
        _profile(),
        _payload(),
        source_url="https://example.test/quest/1",
        source_note="fallback matched",
    )
    large, small = enriched.waves[0].units
    assert large.attribute == "earth"
    assert "giant" in large.traits
    assert "canBeInBattle" not in large.traits
    assert small.level == 53
    assert small.traits == ["attributeEarth", "classRider"]
    assert not any("未从该表取得" in note for note in enriched.notes)
    assert any("example.test" in note for note in enriched.notes)
    assert any("fallback matched" in note for note in enriched.notes)


def test_phase_traits_reject_row_mismatch() -> None:
    payload = _payload()
    payload["stages"][0]["enemies"][0]["hp"] = 999
    with pytest.raises(ValueError, match="没有匹配行"):
        apply_phase_traits(_profile(), payload, source_url="https://example.test/quest/1")


def test_common_enemy_traits_uses_imported_attributes_and_traits() -> None:
    enriched = apply_phase_traits(
        _profile(),
        _payload(),
        source_url="https://example.test/quest/1",
    )
    traits = common_enemy_traits(enriched)
    assert "classRider" in traits
    assert "attributeEarth" in traits
    assert "giant" not in traits


def test_condition_is_counted_when_enemy_traits_match() -> None:
    entry = {
        "name": "条件辅助",
        "class_name": "Assassin",
        "skills": [
            {
                "slot": 2,
                "name": "杀戮技巧（人）",
                "effects": [
                    {
                        "kind": "power_modifier",
                        "value": 50,
                        "values": [50] * 10,
                        "duration": 3,
                        "target": "ally_one",
                        "source": "upDamage",
                        "condition": "human,attributeHuman",
                        "condition_label": "对〔人类〕",
                    }
                ],
            }
        ],
    }
    without_data = summarize_skills(entry, {2: 10})
    with_data = summarize_skills(entry, {2: 10}, {"human", "attributeHuman"})
    assert without_data.ally_np_buff_sum("buster") == 0.0
    assert with_data.ally_np_buff_sum("buster") == pytest.approx(0.5)
    assert any("本次关卡满足条件" in note for note in with_data.modelling_notes)


def test_conditional_damage_is_evaluated_per_enemy() -> None:
    profile = CombatProfile(
        quest_id="conditional-target",
        quest_name="按目标判定特性",
        waves=[
            EnemyWave(
                wave_id="w1",
                wave_index=1,
                units=[
                    EnemyUnit(
                        enemy_id="human",
                        name="人类",
                        class_name="Rider",
                        hp=1000,
                        attribute="human",
                        traits=["human"],
                    ),
                    EnemyUnit(
                        enemy_id="sky",
                        name="天",
                        class_name="Rider",
                        hp=1000,
                        attribute="sky",
                    ),
                ],
            )
        ],
    )
    plan = TeamPlan(
        plan_id="conditional-plan",
        quest_id=profile.quest_id,
        title="条件特攻",
        combatants=[
            CombatantSnapshot(
                actor_slot=1,
                servant_record_id="test",
                name="打手",
                class_name="Assassin",
                attack=1000,
                hp=1000,
                np_multiplier=1.0,
                np_target="area",
            )
        ],
        actions=[
            TeamPlanAction(
                action_id="skill",
                order=1,
                turn=1,
                actor_slot=1,
                action_type="skill",
                effects=[
                    CombatEffect(
                        effect_id="human-up",
                        effect_type="power_modifier",
                        value=1.0,
                        target_actor_slot=1,
                        duration_turns=1,
                        condition="human",
                    )
                ],
            ),
            TeamPlanAction(
                action_id="np",
                order=2,
                turn=1,
                actor_slot=1,
                action_type="np",
            ),
        ],
    )
    result = simulate(SimulationRequest(profile=profile, plan=plan))
    np_action = result.turns[0].actions[1]
    # 人类目标：0.23 × 1000 × (1 + 1.0) = 460；天属性目标：230。
    assert np_action.damage_avg == pytest.approx(690.0)
