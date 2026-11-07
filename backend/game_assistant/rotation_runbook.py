"""固定轮转 → 3T/1T 手册 + 校验。

用途：用户已经验证过的队伍与操作，原样编码成一份 spec，本模块把它变成
TeamPlan、跑一遍模拟器，然后输出**逐回合手册**与三项校验
（充能 / 必定暴击 / 伤害下限），供人工执行或后续自动回放使用。

设计原则：
- 数值口径与推荐器完全一致（复用 `EFFECT_TO_DOMAIN` / 条件判定 / 技能表），
  避免"手册里的数字"和"规划器里的数字"两套标准。
- 手牌/纹章/礼装等账号侧事实写在 spec 里（用户提供），不猜。
- 伤害一律报**最小 roll** 与平均两档，并明确标注模型已知的保守偏差。
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .combat_domain import (
    CombatEffect,
    CombatantSnapshot,
    SimulationRequest,
    TeamPlan,
    TeamPlanAction,
)
from .combat_recommender import (
    EFFECT_TO_DOMAIN,
    RAW_EFFECT_KINDS,
)
from .combat_traits import common_enemy_traits, condition_is_resolvable
from .combat_simulator import simulate
from .combat_store import CombatStore
from .combat_recommender import ASSUMED_ATK_FOU, class_multiplier, relation_encoding
from .servant_stats import NP_CARD_NAME, get_servant_stats, np_multiplier, np_special_multiplier
from .skill_effects import get_skill_table


@dataclass
class RunbookMember:
    slot: int
    name: str
    class_name: str
    level: int
    np_level: int = 1
    skills: list[int] = field(default_factory=lambda: [10, 10, 10])
    append_2: int = 0
    ce_damage_up: float = 0.0
    ce_start_np: float = 0.0
    ce_name: str = ""


@dataclass
class RunbookStep:
    turn: int
    actor: str
    kind: str  # skill / np / card / mystic_code
    skill: str = ""
    target: str = ""
    card: str = ""
    position: int = 1
    crit: bool = False


def _member(spec: dict[str, Any], slot: int) -> RunbookMember:
    return RunbookMember(
        slot=slot,
        name=str(spec.get("name") or ""),
        class_name=str(spec.get("class_name") or ""),
        level=int(spec.get("level") or 90),
        np_level=int(spec.get("np_level") or 1),
        skills=[int(x) for x in (spec.get("skills") or [10, 10, 10])],
        append_2=int(spec.get("append_2") or 0),
        ce_damage_up=float(spec.get("ce_damage_up") or 0.0),
        ce_start_np=float(spec.get("ce_start_np") or 0.0),
        ce_name=str(spec.get("ce_name") or ""),
    )


def _skill_effects(member: RunbookMember, skill_name: str, target_slot: int | None, traits: set[str]) -> list[CombatEffect]:
    """把一个技能按 spec 的目标翻译成计划效果（与推荐器同口径）。"""
    table = get_skill_table()
    entry = table.find(member.name, member.class_name)
    if entry is None:
        raise ValueError(f"技能表里找不到从者：{member.name}")
    skill = next((item for item in entry.get("skills") or [] if str(item.get("name")) == skill_name), None)
    if skill is None:
        raise ValueError(f"{member.name} 没有技能「{skill_name}」")
    effects: list[CombatEffect] = []
    for effect in skill.get("effects") or []:
        kind = str(effect.get("kind"))
        domain = EFFECT_TO_DOMAIN.get(kind)
        if domain is None:
            continue
        condition = str(effect.get("condition") or "")
        if condition and not condition_is_resolvable(condition):
            continue
        value = float(effect.get("value") or 0.0)
        if not value:
            continue
        if domain not in RAW_EFFECT_KINDS:
            value /= 100.0
        effects.append(
            CombatEffect(
                effect_id=f"{member.name}-{skill_name}-{kind}-{target_slot}",
                effect_type=domain,  # type: ignore[arg-type]
                value=value,
                target_actor_slot=target_slot,
                duration_turns=int(effect.get("duration") or 1) or 1,
                card=str(effect.get("card") or ""),
                source=f"{member.name} {skill_name}",
                condition=condition,
                condition_label=str(effect.get("condition_label") or ""),
            )
        )
    return effects


def build_plan(spec: dict[str, Any]) -> tuple[TeamPlan, Any]:
    """按 spec 生成 TeamPlan（并按需跑一次模拟供调用方复核）。"""
    quest_id = str(spec.get("quest_id") or "")
    profile = CombatStore().get_profile(quest_id)
    if profile is None:
        raise ValueError(f"没有找到战斗档案：{quest_id}")
    traits = common_enemy_traits(profile)
    stats = get_servant_stats()
    members = [_member(item, index) for index, item in enumerate(spec.get("team") or [], start=1)]
    by_name = {member.name: member for member in members}

    combatants = []
    for member in members:
        entry = stats.find(member.name, member.class_name)
        if entry is None:
            raise ValueError(f"基础数据里找不到从者：{member.name}")
        attack = (
            stats.attack_at_level(entry, member.level)
            or float(entry.get("atk_max") or 0.0)
        ) + ASSUMED_ATK_FOU
        enemy_class = next(
            (unit.class_name for wave in profile.waves for unit in wave.units),
            "",
        )
        multiplier = class_multiplier(entry["class_name"], enemy_class)
        relation, class_modifier = relation_encoding(multiplier)
        combatants.append(
            CombatantSnapshot(
                actor_slot=member.slot,
                servant_record_id=f"runbook-{member.name}",
                name=member.name,
                class_name=entry["class_name"],
                attack=attack + 2000,  # 与推荐器一致：一张 +2000ATK 的礼装
                hp=10000,
                attribute=str(entry.get("attribute") or "star"),
                class_attack_modifier=class_modifier,
                class_relation=relation,  # type: ignore[arg-type]
                np_multiplier=np_multiplier(entry, member.np_level) or 6.0,
                np_special_multiplier=np_special_multiplier(entry, 3),
                np_target=str(entry.get("np_target") or "area"),  # type: ignore[arg-type]
            )
        )

    actions: list[TeamPlanAction] = []
    order = 0
    for member in members:  # 礼装：开局充能作为第 1 回合效果，增伤为整场效果
        if member.ce_damage_up:
            order += 1
            actions.append(
                TeamPlanAction(
                    action_id=f"ce-{member.slot}",
                    order=order,
                    turn=1,
                    actor_slot=member.slot,
                    action_type="skill",
                    skill_id=member.ce_name or "概念礼装",
                    effects=[
                        CombatEffect(
                            effect_id=f"ce-dmg-{member.slot}",
                            effect_type="power_modifier",
                            value=member.ce_damage_up,
                            target_actor_slot=member.slot,
                            duration_turns=3,
                            source=member.ce_name or "概念礼装",
                        )
                    ],
                    notes=[f"{member.name} 装备{member.ce_name or '概念礼装'}：伤害 +{member.ce_damage_up * 100:.0f}%"],
                )
            )
        if member.ce_start_np:
            order += 1
            actions.append(
                TeamPlanAction(
                    action_id=f"ce-np-{member.slot}",
                    order=order,
                    turn=1,
                    actor_slot=member.slot,
                    action_type="skill",
                    skill_id=member.ce_name or "概念礼装",
                    effects=[
                        CombatEffect(
                            effect_id=f"ce-np-fx-{member.slot}",
                            effect_type="charge",
                            value=member.ce_start_np,
                            target_actor_slot=member.slot,
                            duration_turns=0,
                            source=member.ce_name or "概念礼装",
                        )
                    ],
                    notes=[f"{member.name} 开局宝具值 +{member.ce_start_np * 100:.0f}%"],
                )
            )

    for step in spec.get("steps") or []:
        actor = by_name.get(str(step.get("actor") or ""))
        if actor is None:
            raise ValueError(f"操作步骤里的从者不在队伍中：{step.get('actor')}")
        kind = str(step.get("kind") or "")
        target = by_name.get(str(step.get("target") or ""))
        order += 1
        if kind == "switch":
            if target is None:
                raise ValueError(f"换人步骤缺少目标：{step}")
            actions.append(
                TeamPlanAction(
                    action_id=f"t{step.get('turn')}-{actor.slot}-{order}-switch",
                    order=order,
                    turn=int(step.get("turn") or 1),
                    actor_slot=actor.slot,
                    action_type="switch",
                    switch_out_slot=actor.slot,
                    switch_in_slot=target.slot,
                    notes=[f"{actor.name} 换人 → {target.name}"],
                )
            )
        elif kind == "skill":
            effects = _skill_effects(actor, str(step.get("skill") or ""), target.slot if target else None, traits)
            actions.append(
                TeamPlanAction(
                    action_id=f"t{step.get('turn')}-{actor.slot}-{order}",
                    order=order,
                    turn=int(step.get("turn") or 1),
                    actor_slot=actor.slot,
                    action_type="skill",
                    skill_id=str(step.get("skill") or ""),
                    effects=effects,
                    notes=[f"{actor.name} 使用 {step.get('skill')}" + (f" → {target.name}" if target else "")],
                )
            )
        elif kind in {"np", "card"}:
            card = str(step.get("card") or "")
            crit = bool(step.get("crit"))
            extra: list[CombatEffect] = []
            code_charge = float(step.get("command_code_charge") or 0.0)
            if code_charge:
                extra.append(
                    CombatEffect(
                        effect_id=f"t{step.get('turn')}-{actor.slot}-code",
                        effect_type="charge",
                        value=code_charge,
                        target_actor_slot=actor.slot,
                        duration_turns=0,
                        source=str(step.get("command_code") or "指令纹章"),
                    )
                )
            actions.append(
                TeamPlanAction(
                    action_id=f"t{step.get('turn')}-{actor.slot}-{order}",
                    order=order,
                    turn=int(step.get("turn") or 1),
                    actor_slot=actor.slot,
                    action_type="np" if kind == "np" else "attack",
                    card_type=card or None,  # type: ignore[arg-type]
                    card_position=int(step.get("position") or 1),
                    is_critical=crit,
                    effects=extra,
                    notes=[
                        f"{actor.name} {'宝具' if kind == 'np' else f'{card} 指令卡'}"
                        + ("（暴击）" if crit else "")
                    ],
                )
            )
        else:
            raise ValueError(f"未知步骤类型：{kind}")

    plan = TeamPlan(
        plan_id=f"{quest_id}-runbook",
        quest_id=quest_id,
        title=str(spec.get("title") or f"{profile.quest_name} 固定轮转"),
        combatants=combatants,
        actions=actions,
        initial_front_slots=[member.slot for member in members[:3]],
        assumptions=["按用户给定的固定轮转执行；数值口径与推荐器一致。"],
        warnings=["模拟器不建模攻击回收宝具值与敌方行动；伤害为保守估计。"],
        confidence=0.6,
    )
    return plan, profile


def render_runbook(spec: dict[str, Any], plan: TeamPlan, profile: Any, result: Any) -> str:
    """输出人可读的手册 + 三项校验。"""
    lines: list[str] = []
    lines.append(f"# {plan.title}")
    lines.append(f"- 副本：{profile.quest_name}（{profile.quest_id}，AP {profile.ap_cost}）")
    lines.append(f"- 面数：{len(profile.waves)}｜需要伤害（最小 roll）：{profile.total_enemy_hp:,}")
    lines.append("")
    lines.append("## 队伍")
    for combatant in plan.combatants:
        member = next((m for m in spec.get("team") or [] if str(m.get("name")) == combatant.name), {})
        ce = ""
        if member.get("ce_name"):
            ce = f"｜礼装 {member['ce_name']}"
            if member.get("ce_damage_up"):
                ce += f"（伤害 +{float(member['ce_damage_up']) * 100:.0f}%）"
            if member.get("ce_start_np"):
                ce += f"（开局 +{float(member['ce_start_np']) * 100:.0f}% 宝具值）"
        lines.append(
            f"- 槽位 {combatant.actor_slot}：{combatant.name}（{combatant.class_name}）"
            f" 宝具倍率 {combatant.np_multiplier:g}｜{'光炮' if combatant.np_target == 'area' else '单体'}"
            f"{ce}"
        )
    lines.append("")
    for turn in result.turns:
        lines.append(f"## 第 {turn.turn} 回合")
        for action in turn.actions:
            label = action.notes[0] if action.notes else action.action_id
            detail = f"　伤害 {int(action.damage_avg):,}" if action.damage_avg else ""
            lines.append(f"{action.order}. {label}{detail}")
        lines.append(
            f"- 本回合合计伤害 {int(sum(a.damage_avg for a in turn.actions)):,}"
            f"｜剩余敌人 {turn.enemies_remaining}｜剩余血量 {int(turn.total_enemy_hp_remaining):,}"
        )
        lines.append("")
    lines.append("## 校验")
    lines.append(
        f"- 伤害（最小 roll）：{int(result.total_damage_min):,} / 需要 {profile.total_enemy_hp:,}"
        f" → {'通过' if result.total_damage_min >= profile.total_enemy_hp else f'缺口 {int(profile.total_enemy_hp - result.total_damage_min):,}'}"
    )
    lines.append(
        f"- 伤害（平均）：{int(result.total_damage_avg):,}｜清场回合：{result.cleared_by_turn or '未清场'}"
    )
    charge_steps = [
        (action.turn, action.action_id)
        for action in plan.actions
        if any(effect.effect_type == "charge" for effect in action.effects)
    ]
    lines.append(f"- 充能来源：{charge_steps}")
    crit_cards = [action for action in plan.actions if action.is_critical]
    lines.append(f"- 暴击卡：{[(a.turn, a.actor_slot, a.card_type, a.card_position) for a in crit_cards]}")
    lines.append(
        "- 说明：模型不建模攻击回收宝具值与敌方行动；带倍卡时实际伤害高于本估算。"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按固定轮转生成手册与校验")
    parser.add_argument("--spec", required=True, help="轮转 spec JSON 路径")
    parser.add_argument("--out", default="", help="手册输出路径（默认与 spec 同目录 .md）")
    args = parser.parse_args(argv)
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    plan, profile = build_plan(spec)
    result = simulate(SimulationRequest(profile=profile, plan=plan))
    text = render_runbook(spec, plan, profile, result)
    out = Path(args.out or Path(args.spec).with_suffix(".runbook.md"))
    out.write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\n[已写入 {out}]")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main())
