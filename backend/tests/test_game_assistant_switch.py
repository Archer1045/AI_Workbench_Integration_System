from __future__ import annotations

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
from game_assistant.combat_simulator import simulate
from game_assistant.crit_model import evaluate_crit


def _profile() -> CombatProfile:
    return CombatProfile(
        quest_id="switch-test",
        quest_name="换人测试",
        waves=[
            EnemyWave(
                wave_id="w1",
                wave_index=1,
                units=[
                    EnemyUnit(
                        enemy_id="e1",
                        name="敌人",
                        class_name="Rider",
                        hp=1000,
                    )
                ],
            )
        ],
    )


def _combatant(slot: int) -> CombatantSnapshot:
    return CombatantSnapshot(
        actor_slot=slot,
        servant_record_id=f"s{slot}",
        name=f"从者{slot}",
        class_name="Assassin",
        attack=10000,
        hp=10000,
        np_multiplier=1.0,
    )


def _attack(slot: int, order: int) -> TeamPlanAction:
    return TeamPlanAction(
        action_id=f"attack-{slot}-{order}",
        order=order,
        turn=1,
        actor_slot=slot,
        action_type="attack",
        card_type="buster",
        card_position=1,
    )


def _plan(actions: list[TeamPlanAction]) -> TeamPlan:
    return TeamPlan(
        plan_id="switch-plan",
        quest_id="switch-test",
        title="换人",
        combatants=[_combatant(slot) for slot in (1, 2, 3, 4)],
        actions=actions,
        initial_front_slots=[1, 2, 3],
    )


def test_backfield_actor_cannot_act_before_switch() -> None:
    result = simulate(SimulationRequest(profile=_profile(), plan=_plan([_attack(4, 1)])))
    assert result.status == "invalid"
    assert any("backfield slot 4" in error for error in result.errors)


def test_switch_enables_backfield_actor() -> None:
    switch = TeamPlanAction(
        action_id="switch-1-4",
        order=1,
        turn=1,
        actor_slot=1,
        action_type="switch",
        switch_out_slot=1,
        switch_in_slot=4,
    )
    result = simulate(
        SimulationRequest(profile=_profile(), plan=_plan([switch, _attack(4, 2)]))
    )
    assert result.status == "success"
    assert result.errors == []
    assert result.turns[0].actions[1].actor_slot == 4


def test_switch_invalidates_prior_hand_fix() -> None:
    hand_fix = TeamPlanAction(
        action_id="hand-fix",
        order=1,
        turn=1,
        actor_slot=1,
        action_type="skill",
        effects=[
            CombatEffect(
                effect_id="fix",
                effect_type="control",
                target_actor_slot=1,
                duration_turns=3,
                notes="hand_fixed|target=self",
            ),
            CombatEffect(
                effect_id="stars",
                effect_type="stars",
                value=60,
                target_actor_slot=1,
                duration_turns=0,
            ),
        ],
    )
    switch = TeamPlanAction(
        action_id="switch-1-4",
        order=2,
        turn=1,
        actor_slot=1,
        action_type="switch",
        switch_out_slot=1,
        switch_in_slot=4,
    )
    gate = evaluate_crit(
        actions=[hand_fix, switch],
        crit_slot=1,
        names={1: "希耶尔", 4: "打手"},
    )
    assert gate.card_access == ""
    assert gate.passed is False
    assert any("换人解除" in note for note in gate.control_order_notes)
