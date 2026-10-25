"""Deterministic MVP damage/NP simulator for 3T TeamPlans.

This module intentionally uses a documented simplified formula. It is suitable
for plan gating and regression tests, not for claiming exact in-game damage.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .combat_domain import (
    ActionSimulation,
    CombatantSnapshot,
    CombatEffect,
    CombatProfile,
    DamageGate,
    EnemyUnit,
    NpGate,
    SimulationRequest,
    SimulationResult,
    TeamPlanAction,
    TurnSimulation,
)
from .combat_traits import condition_satisfied, enemy_trait_set
from .damage_constants import attribute_relation_multiplier

BASE_DAMAGE_COEFFICIENT = 0.23
CRIT_DAMAGE_MULTIPLIER = 2.0

_CLASS_RELATION_MULTIPLIER = {
    "advantage": 2.0,
    "neutral": 1.0,
    "disadvantage": 0.5,
}

_CARD_MULTIPLIER = {
    "buster": 1.5,
    "arts": 1.0,
    "quick": 0.8,
    "extra": 1.0,
}

# 指令卡按「本回合第几个卡位」取倍率：红卡 1.5/1.8/2.1、蓝卡 1.0/1.2/1.4、
# 绿卡 0.8/0.96/1.12（FGO 的 cardDamageValue 表）。宝具卡不参与这套倍率。
_CARD_POSITION_MULTIPLIER = {
    "buster": (1.5, 1.8, 2.1),
    "arts": (1.0, 1.2, 1.4),
    "quick": (0.8, 0.96, 1.12),
    "extra": (1.0, 1.0, 1.0),
}


def _effect_value(effects: list[CombatEffect], effect_type: str) -> float:
    return sum(effect.value for effect in effects if effect.effect_type == effect_type)


def _active_effects_for_actor(
    stored: dict[int, list[CombatEffect]],
    source_effects: list[CombatEffect],
    actor_slot: int,
    turn: int,
) -> list[CombatEffect]:
    active: list[CombatEffect] = []
    for effect in stored.get(actor_slot, []):
        if effect.duration_turns is None or (turn <= effect.duration_turns):
            active.append(effect)
    for effect in source_effects:
        if effect.target_actor_slot in (None, actor_slot):
            active.append(effect)
    return active


def _card_multiplier(action: TeamPlanAction, combatant: CombatantSnapshot) -> float:
    if action.damage_multiplier is not None:
        return action.damage_multiplier
    if action.action_type == "np":
        return combatant.np_multiplier
    if action.card_type is None:
        return 1.0
    table = _CARD_POSITION_MULTIPLIER.get(action.card_type)
    if table:
        index = min(max(int(action.card_position or 1), 1), len(table)) - 1
        return table[index]
    return combatant.card_modifiers.get(action.card_type, _CARD_MULTIPLIER[action.card_type])


def _np_multiplier(action: TeamPlanAction, combatant: CombatantSnapshot, field_enemies: int) -> float:
    """宝具倍率 = 基础倍率 + 「个体数」第二成分 × 场上敌人数（用户 2026-10-10 确认口径）。"""
    if action.damage_multiplier is not None:
        return action.damage_multiplier
    return combatant.np_multiplier + combatant.np_special_multiplier * max(0, field_enemies)


def _damage(
    action: TeamPlanAction,
    combatant: CombatantSnapshot,
    target: EnemyUnit,
    effects: list[CombatEffect],
    variance: float,
    field_enemies: int = 0,
) -> float:
    effects = [
        effect
        for effect in effects
        if not effect.condition
        or condition_satisfied(effect.condition, enemy_trait_set(target))
    ]
    card_multiplier = (
        _np_multiplier(action, combatant, field_enemies)
        if action.action_type == "np"
        else _card_multiplier(action, combatant)
    )
    attack_buff = _effect_value(effects, "attack_up")
    card_buff = _effect_value(effects, "card_up")
    np_buff = _effect_value(effects, "np_damage_up") if action.action_type == "np" else 0.0
    power_modifier = _effect_value(effects, "power_modifier")
    special_attack = _effect_value(effects, "special_attack")
    critical_up = _effect_value(effects, "critical_up")
    defense_down = _effect_value(effects, "defense_down")
    flat_damage = _effect_value(effects, "flat_damage")
    # 暴击威力只对“必定暴击”的指令卡生效：之前它被并进通用增益，
    # 会把宝具伤害一起抬高（例如光之高扬斯卡娅的暴击威力 +50%）。
    crit_multiplier = 1.0
    if action.is_critical:
        crit_multiplier = CRIT_DAMAGE_MULTIPLIER * (1.0 + critical_up)
    # critical_up 永远不进入通用增益：只有暴击那一张卡吃它。
    buff_sum = attack_buff + card_buff + np_buff + power_modifier + special_attack
    base = combatant.attack * BASE_DAMAGE_COEFFICIENT
    relation = _CLASS_RELATION_MULTIPLIER[combatant.class_relation]
    attribute_relation = attribute_relation_multiplier(combatant.attribute, target.attribute)
    return (
        base
        * combatant.class_attack_modifier
        * relation
        * attribute_relation
        * card_multiplier
        * crit_multiplier
        * (1.0 + buff_sum)
        * (1.0 + defense_down)
        * variance
        + flat_damage
    )


def _np_after(action: TeamPlanAction, combatant: CombatantSnapshot, effects: list[CombatEffect]) -> float:
    gain_up = _effect_value(effects, "np_gain_up")
    charge = _effect_value(effects, "charge")
    delta = action.np_change + charge
    if delta > 0 and gain_up:
        delta *= 1.0 + gain_up
    return max(0.0, min(combatant.np_capacity, combatant.current_np + delta))


def _enemy_state(profile: CombatProfile) -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for wave in profile.waves:
        for unit in wave.units:
            state[unit.enemy_id] = {
                "unit": deepcopy(unit),
                "current_hp": float(unit.hp),
                "count": unit.count,
                "wave_index": wave.wave_index,
            }
    return state


def _alive_target_ids(
    state: dict[str, dict[str, Any]],
    action: TeamPlanAction,
    np_target: str = "area",
) -> list[str]:
    """解析攻击目标的存活敌人。

    宝具必须区分单体与光炮：单体宝具只打该面血量最高的敌人，
    光炮才命中该面全体。此前所有宝具都被当成光炮，会高估单体宝具的清场能力。
    """
    if action.target_enemy_ids:
        return [enemy_id for enemy_id in action.target_enemy_ids if enemy_id in state and state[enemy_id]["count"] > 0]
    alive = [enemy_id for enemy_id, item in state.items() if item["count"] > 0]
    if not alive:
        return []
    earliest_wave = min(state[enemy_id]["wave_index"] for enemy_id in alive)
    candidates = [enemy_id for enemy_id in alive if state[enemy_id]["wave_index"] == earliest_wave]
    if action.action_type != "np":
        return candidates[:1]
    if np_target == "single":
        return [max(candidates, key=lambda enemy_id: state[enemy_id]["current_hp"])]
    return candidates


def _apply_damage(state: dict[str, dict[str, Any]], enemy_id: str, damage: float) -> None:
    item = state.get(enemy_id)
    if item is None or item["count"] <= 0:
        return
    item["current_hp"] -= damage
    if item["current_hp"] <= 0:
        item["count"] -= 1
        item["current_hp"] = float(item["unit"].hp)


def _remaining_state(state: dict[str, dict[str, Any]]) -> tuple[int, float]:
    alive = [item for item in state.values() if item["count"] > 0]
    remaining_count = sum(int(item["count"]) for item in alive)
    remaining_hp = sum(float(item["current_hp"]) * int(item["count"]) for item in alive)
    return remaining_count, remaining_hp


def card_slot_violations(plan: "TeamPlan", cards_per_turn: int = 3) -> list[str]:
    """校验「每回合 3 个卡位、宝具也占 1 个卡位」这条游戏规则（用户 2026-10-10 确认）。

    规划器生成的方案必须满足它；这里再兜一道，避免手写/导入的方案把超编的卡位当真。
    """
    usage: dict[int, list[str]] = {}
    for action in plan.actions:
        if action.action_type in {"np", "attack"}:
            usage.setdefault(action.turn, []).append(action.action_id)
    return [
        f"第 {turn} 回合占用了 {len(ids)} 个卡位（上限 {cards_per_turn}）：{', '.join(ids)}"
        for turn, ids in sorted(usage.items())
        if len(ids) > cards_per_turn
    ]


def simulate(request: SimulationRequest) -> SimulationResult:
    state = _enemy_state(request.profile)
    combatants = {item.actor_slot: item.model_copy(deep=True) for item in request.plan.combatants}
    active_slots = set(request.plan.initial_front_slots or combatants.keys())
    stored_effects: dict[int, list[CombatEffect]] = {slot: [] for slot in combatants}
    actions_by_turn: dict[int, list[TeamPlanAction]] = {turn: [] for turn in (1, 2, 3)}
    for action in request.plan.actions:
        actions_by_turn.setdefault(action.turn, []).append(action)
    for items in actions_by_turn.values():
        items.sort(key=lambda item: item.order)

    # 每回合 3 个卡位（宝具占 1 位）：超编只告警，不改变数值口径。
    warnings: list[str] = card_slot_violations(request.plan)

    turns: list[TurnSimulation] = []
    damage_gates: list[DamageGate] = []
    np_gates: list[NpGate] = []
    errors: list[str] = []
    total_min = total_avg = total_max = 0.0
    cleared_by_turn: int | None = None

    for turn_number in range(1, 4):
        turn_actions: list[ActionSimulation] = []
        for action in actions_by_turn.get(turn_number, []):
            if action.action_type == "switch":
                out_slot = action.switch_out_slot or action.actor_slot
                in_slot = action.switch_in_slot
                if in_slot is None or in_slot not in combatants:
                    errors.append(
                        f"action {action.action_id} switches to missing slot {in_slot}"
                    )
                    continue
                if out_slot not in active_slots:
                    errors.append(
                        f"action {action.action_id} switches out inactive slot {out_slot}"
                    )
                    continue
                if in_slot in active_slots:
                    errors.append(
                        f"action {action.action_id} switches in already-active slot {in_slot}"
                    )
                    continue
                active_slots.remove(out_slot)
                active_slots.add(in_slot)
                turn_actions.append(
                    ActionSimulation(
                        action_id=action.action_id,
                        order=action.order,
                        turn=turn_number,
                        actor_slot=out_slot,
                        action_type="switch",
                        target_enemy_ids=[],
                        notes=action.notes,
                    )
                )
                continue
            combatant = combatants.get(action.actor_slot)
            if combatant is None:
                errors.append(f"action {action.action_id} uses missing actor slot {action.actor_slot}")
                continue
            if action.actor_slot not in active_slots:
                errors.append(
                    f"action {action.action_id} uses backfield slot {action.actor_slot} before a switch"
                )
                continue
            effects = _active_effects_for_actor(stored_effects, action.effects, action.actor_slot, turn_number)
            target_ids = _alive_target_ids(state, action, combatant.np_target)
            if action.action_type in {"attack", "np"} and not target_ids:
                errors.append(f"action {action.action_id} has no valid living target")
                continue

            damage_min = damage_avg = damage_max = 0.0
            if action.action_type in {"attack", "np"}:
                # 「场上敌人」= 当前这一面还活着的敌人数量（用户确认的个体数口径）。
                field_enemies = 0
                if target_ids:
                    current_wave = state[target_ids[0]]["wave_index"]
                    field_enemies = sum(
                        int(item["count"])
                        for item in state.values()
                        if item["count"] > 0 and item["wave_index"] == current_wave
                    )
                for enemy_id in target_ids:
                    enemy: EnemyUnit = state[enemy_id]["unit"]
                    if action.action_type == "np":
                        damage_min += _damage(action, combatant, enemy, effects, request.damage_variance_min, field_enemies)
                        damage_avg += _damage(action, combatant, enemy, effects, 1.0, field_enemies)
                        damage_max += _damage(action, combatant, enemy, effects, request.damage_variance_max, field_enemies)
                    else:
                        damage_min += _damage(action, combatant, enemy, effects, request.damage_variance_min)
                        damage_avg += _damage(action, combatant, enemy, effects, 1.0)
                        damage_max += _damage(action, combatant, enemy, effects, request.damage_variance_max)
                total_min += damage_min
                total_avg += damage_avg
                total_max += damage_max
                for enemy_id in target_ids:
                    _apply_damage(state, enemy_id, damage_avg)
                    damage_gates.append(
                        DamageGate(
                            enemy_id=enemy_id,
                            required_damage=float(state[enemy_id]["unit"].hp),
                            expected_min_damage=damage_min,
                            expected_avg_damage=damage_avg,
                            passed=damage_min >= float(state[enemy_id]["unit"].hp),
                        )
                    )

            combatant.current_np = _np_after(action, combatant, effects)
            if action.np_change or _effect_value(effects, "charge"):
                np_gates.append(
                    NpGate(
                        actor_slot=combatant.actor_slot,
                        turn=turn_number,
                        required_np=0.0,
                        actual_np=combatant.current_np,
                        passed=True,
                    )
                )

            if action.action_type in {"skill", "mystic_code"}:
                duration = max((effect.duration_turns or turn_number for effect in action.effects), default=turn_number)
                # 效果按“接收者”存储：辅助给队友上的增益必须记到队友那一位，
                # 否则辅助的增益永远只会作用在辅助自己身上（这是本轮发现的语义缺陷）。
                for effect in action.effects:
                    target_slot = effect.target_actor_slot or action.actor_slot
                    if target_slot not in active_slots:
                        errors.append(
                            f"action {action.action_id} targets backfield slot {target_slot}"
                        )
                        continue
                    stored_effects.setdefault(target_slot, []).append(
                        effect.model_copy(update={"duration_turns": duration, "target_actor_slot": target_slot})
                    )

            turn_actions.append(
                ActionSimulation(
                    action_id=action.action_id,
                    order=action.order,
                    turn=turn_number,
                    actor_slot=action.actor_slot,
                    action_type=action.action_type,
                    target_enemy_ids=target_ids,
                    damage_min=damage_min,
                    damage_avg=damage_avg,
                    damage_max=damage_max,
                    np_after=combatant.current_np,
                    notes=action.notes,
                )
            )

        remaining_count, remaining_hp = _remaining_state(state)
        turns.append(
            TurnSimulation(
                turn=turn_number,
                actions=turn_actions,
                enemies_remaining=remaining_count,
                total_enemy_hp_remaining=remaining_hp,
            )
        )
        if remaining_count == 0:
            cleared_by_turn = turn_number
            break
        if request.require_three_turn_clear and turn_number == 3:
            warnings.append("TeamPlan did not clear all enemies by turn 3")

    status = "invalid" if errors else ("success" if cleared_by_turn is not None else "failed")
    return SimulationResult(
        status=status,
        cleared_by_turn=cleared_by_turn,
        total_turns=len(turns),
        total_damage_min=total_min,
        total_damage_avg=total_avg,
        total_damage_max=total_max,
        turns=turns,
        damage_gates=damage_gates,
        np_gates=np_gates,
        errors=errors,
        warnings=warnings,
    )
