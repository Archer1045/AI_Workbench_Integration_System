"""第二步回归测试：辅助位、真实技能增益、充能闸门，以及两个已修缺陷。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from game_assistant.account_domain import ServantRecordInput
from game_assistant.account_store import AccountSnapshotStore
from game_assistant.combat_domain import RecommendationRequest
from game_assistant.combat_recommender import append_start_np, recommend, summarize_skills
from game_assistant.combat_store import CombatStore
from game_assistant.quest_profile_import import build_profile, find_quest_section, parse_quest_section
from game_assistant.servant_stats import ServantStatsStore
from game_assistant.skill_effects import SkillTableStore

SECTION_HTML = Path(__file__).resolve().parent / "data" / "mooncell_90pp_section.html"


def _profile():
    html = SECTION_HTML.read_text(encoding="utf-8")
    parsed = parse_quest_section(find_quest_section(html, "神剑改_燃烧吧翡翠剑"))
    return build_profile(
        parsed,
        quest_id="test-90pp",
        event_id="test-event",
        quest_name="神剑改 燃烧吧翡翠剑（90++）",
        source_ids=["src-test"],
    )


def _stats(tmp_path: Path, names: list[str], classes: list[str]) -> ServantStatsStore:
    servants = [
        {
            "name": name,
            "battle_name": "",
            "class_name": class_name,
            "rarity": 5,
            "lv_max": 100,
            "atk_max": 12000,
            "atk_growth": [9000] * 100 + [12000] * 20,
            "hp_max": 14000,
            "np_card": 2,
            "np_target_type": "对人宝具",
            "np_damage_values": [12000, 16000, 18000, 19000, 20000],
        }
        for name, class_name in zip(names, classes)
    ]
    path = tmp_path / "stats.json"
    path.write_text(json.dumps({"source": {}, "servants": servants}, ensure_ascii=False), encoding="utf-8")
    return ServantStatsStore(path)


def _effect(
    kind: str,
    value: float,
    target: str,
    duration: int = 3,
    source: str = "",
    condition: str = "",
    condition_label: str = "",
) -> dict:
    return {
        "kind": kind,
        "value": value,
        "values": [value] * 10,
        "duration": duration,
        "target": target,
        "source": source or kind,
        "condition": condition,
        "condition_label": condition_label,
    }


def _skill_table(tmp_path: Path, entries: list[dict]) -> SkillTableStore:
    path = tmp_path / "skills.json"
    path.write_text(
        json.dumps({"source": {}, "unmodeled_counts": {}, "servants": entries}, ensure_ascii=False),
        encoding="utf-8",
    )
    return SkillTableStore(path)


def _combat_servant(name: str, class_name: str, skills: list[dict]) -> dict:
    return {
        "name": name,
        "normalized_name": name,
        "class_name": class_name,
        "collection_no": 1,
        "star_gen": 100,
        "star_absorb": 50,
        "cards": ["1", "1", "2", "2", "3"],
        "hit_distribution": {},
        "skills": skills,
    }


def _account(tmp_path: Path, rows: list[tuple[str, str, int, int]]) -> AccountSnapshotStore:
    store = AccountSnapshotStore(tmp_path / "account.db")
    for name, class_name, level, skill in rows:
        store.upsert_servant(
            ServantRecordInput(
                name=name,
                class_name=class_name,
                rarity=5,
                level=level,
                max_level=100,
                np_level=1,
                skill_1=skill,
                skill_2=skill,
                skill_3=skill,
            )
        )
    return store


def test_support_is_selected_and_charge_gate_passes(tmp_path: Path) -> None:
    """两输出结构下，全体充能技能（ally_all）才能同时喂饱两名输出。"""
    profile = _profile()
    store = CombatStore(tmp_path / "combat")
    store.save_profile(profile)
    stats = _stats(tmp_path, ["打手", "充能辅助A", "充能辅助B"], ["Assassin", "Caster", "Caster"])
    skills = _skill_table(
        tmp_path,
        [
            _combat_servant(
                "打手",
                "Assassin",
                [
                    {
                        "slot": 1,
                        "name": "自身增伤",
                        "rank": "A",
                        "cooldowns": [6] * 10,
                        "effects": [_effect("attack_up", 30, "self")],
                    }
                ],
            ),
            _combat_servant(
                "充能辅助A",
                "Caster",
                [
                    {
                        "slot": 1,
                        "name": "充能A",
                        "rank": "A",
                        "cooldowns": [7] * 10,
                        "effects": [_effect("charge", 0.8, "ally_all", duration=0)],
                    }
                ],
            ),
            _combat_servant(
                "充能辅助B",
                "Caster",
                [
                    {
                        "slot": 1,
                        "name": "充能B",
                        "rank": "A",
                        "cooldowns": [7] * 10,
                        "effects": [_effect("charge", 0.8, "ally_all", duration=0)],
                    },
                    {
                        "slot": 2,
                        "name": "充能B2",
                        "rank": "A",
                        "cooldowns": [8] * 10,
                        "effects": [_effect("charge", 0.8, "ally_all", duration=0)],
                    },
                ],
            ),
        ],
    )
    result = recommend(
        RecommendationRequest(quest_id=profile.quest_id),
        store=store,
        account_store=_account(tmp_path, [("打手", "Assassin", 100, 10), ("充能辅助A", "Caster", 90, 10), ("充能辅助B", "Caster", 90, 10)]),
        stats=stats,
        skills=skills,
    )
    option = result.options[0]
    roles = {servant.role for servant in option.required_servants}
    assert "main_dps" in roles
    # 3.5 步之后应包含第二输出点，用来补掉主输出覆盖不到的目标
    assert "secondary_dps" in roles or "support" in roles
    assert option.charge_gate_passed is True, "\n".join(option.charge_plan)
    assert option.bond_slots >= 2
    # 辅助技能必须作用于前排：增益指向主输出，全体充能同时覆盖两名输出。
    # 全体效果会写给所有前排（辅助也可能成为必定暴击的补刀手），所以上界是前排而不是输出位。
    dps_slot = next(c.actor_slot for c in option.plan.combatants if c.name == "打手")
    support_effects = [
        effect
        for action in option.plan.actions
        if action.action_type == "skill" and action.actor_slot != dps_slot
        for effect in action.effects
    ]
    assert support_effects, "辅助应当产生作用于主输出的技能动作"
    targets = {effect.target_actor_slot for effect in support_effects}
    frontline_slots = {
        c.actor_slot
        for c in option.plan.combatants
        if c.name in {servant.name for servant in option.required_servants}
    }
    attacker_slots = {
        c.actor_slot
        for c in option.plan.combatants
        if c.name in {servant.name for servant in option.required_servants if servant.role != "support"}
    }
    assert targets <= frontline_slots
    assert attacker_slots <= targets
    assert dps_slot in targets


def test_charge_gate_reports_shortfall_without_supports(tmp_path: Path) -> None:
    profile = _profile()
    store = CombatStore(tmp_path / "combat")
    store.save_profile(profile)
    stats = _stats(tmp_path, ["独狼"], ["Assassin"])
    skills = _skill_table(tmp_path, [_combat_servant("独狼", "Assassin", [])])
    result = recommend(
        RecommendationRequest(quest_id=profile.quest_id),
        store=store,
        account_store=_account(tmp_path, [("独狼", "Assassin", 100, 10)]),
        stats=stats,
        skills=skills,
    )
    option = result.options[0]
    assert option.charge_gate_passed is False
    assert any("缺口" in line for line in option.charge_plan)
    assert any("充能闸门未通过" in item for item in option.failure_conditions)


def test_percent_buffs_are_emitted_as_fractions(tmp_path: Path) -> None:
    """回归：解析层是百分数（30），模拟器要小数（0.3），否则会乘出 31 倍伤害。"""
    profile = _profile()
    store = CombatStore(tmp_path / "combat")
    store.save_profile(profile)
    stats = _stats(tmp_path, ["打手"], ["Assassin"])
    skills = _skill_table(
        tmp_path,
        [
            _combat_servant(
                "打手",
                "Assassin",
                [
                    {
                        "slot": 1,
                        "name": "自身增伤",
                        "rank": "A",
                        "cooldowns": [6] * 10,
                        "effects": [_effect("attack_up", 30, "self"), _effect("card_up", 50, "self")],
                    }
                ],
            )
        ],
    )
    result = recommend(
        RecommendationRequest(quest_id=profile.quest_id),
        store=store,
        account_store=_account(tmp_path, [("打手", "Assassin", 100, 10)]),
        stats=stats,
        skills=skills,
    )
    effects = [effect for action in result.options[0].plan.actions for effect in action.effects]
    assert pytest.approx(0.3) in [round(effect.value, 6) for effect in effects if effect.effect_type == "attack_up"]
    assert pytest.approx(0.5) in [round(effect.value, 6) for effect in effects if effect.effect_type == "card_up"]
    # 伤害必须落在合理量级，而不是被放大成天文数字
    assert result.options[0].simulation.total_damage_avg < 5_000_000


def test_duplicate_ascension_skill_slots_are_deduplicated() -> None:
    """回归：同一槽位的多个再临形态不能同时计入。"""
    entry = {
        "name": "双形态",
        "class_name": "Beast",
        "skills": [
            {
                "slot": 1,
                "name": "形态一",
                "effects": [_effect("charge", 0.3, "ally_one", duration=0)],
            },
            {
                "slot": 1,
                "name": "形态二",
                "effects": [_effect("charge", 0.5, "ally_one", duration=0), _effect("attack_up", 50, "ally_all")],
            },
        ],
    }
    summary = summarize_skills(entry, {1: 10})
    assert summary.ally_charge == pytest.approx(0.3)
    assert summary.ally_buffs.get("attack_up") is None


def test_self_only_buffs_are_not_counted_for_allies() -> None:
    """用户纠正过：自身限定效果不能当作给队友的增益。"""
    entry = {
        "name": "只给自己",
        "class_name": "MoonCancer",
        "skills": [
            {
                "slot": 3,
                "name": "自我改造（恋）",
                "effects": [
                    _effect("critical_up", 50, "self"),
                    _effect("star_weight_up", 800, "self"),
                    _effect("crit_rate_up", 15, "self"),
                ],
            }
        ],
    }
    summary = summarize_skills(entry, {3: 10})
    # 暴击类效果目前不参与宝具伤害，但它们绝不能出现在“给队友”的集合里。
    assert summary.ally_np_buff_sum("buster") == 0.0
    assert summary.ally_buffs == {}
    assert summary.ally_charge == 0.0


def test_self_offense_buffs_are_recorded_for_the_owner() -> None:
    entry = {
        "name": "自强化",
        "class_name": "Assassin",
        "skills": [
            {
                "slot": 1,
                "name": "自身强化",
                "effects": [_effect("attack_up", 30, "self"), _effect("card_up", 50, "self")],
            }
        ],
    }
    summary = summarize_skills(entry, {1: 10})
    assert summary.self_buffs.get("attack_up") == pytest.approx(0.3)
    assert summary.self_np_buff_sum("") == pytest.approx(0.8)


def test_append_skill_start_charge_scales_with_level() -> None:
    """追加技能2「魔力装填」是免费的充能来源，Lv1 +10% → Lv10 +20%。"""
    assert append_start_np(0) == 0.0
    assert append_start_np(None) == 0.0
    assert append_start_np(1) == pytest.approx(0.10)
    assert append_start_np(10) == pytest.approx(0.20)


def _run_support_case(tmp_path: Path, with_charge_skill: bool) -> object:
    profile = _profile()
    store = CombatStore(tmp_path / "combat")
    store.save_profile(profile)
    stats = _stats(tmp_path, ["打手", "副手"], ["Assassin", "Caster"])
    effects = [_effect("charge", 1.0, "ally_all", duration=0)] if with_charge_skill else []
    skills = _skill_table(
        tmp_path,
        [
            _combat_servant("打手", "Assassin", []),
            _combat_servant(
                "副手",
                "Caster",
                [{"slot": 1, "name": "全体充能", "rank": "A", "cooldowns": [7] * 10, "effects": effects}],
            ),
        ],
    )
    return recommend(
        RecommendationRequest(quest_id=profile.quest_id),
        store=store,
        account_store=_account(tmp_path, [("打手", "Assassin", 100, 10), ("副手", "Caster", 90, 10)]),
        stats=stats,
        skills=skills,
    )


def test_plans_without_extra_craft_essences_only_cost_the_event_ce(tmp_path: Path) -> None:
    """有全体充能技能时第 1 回合不依赖额外礼装，只剩打手的倍卡礼装占 1 个位置。"""
    result = _run_support_case(tmp_path, with_charge_skill=True)
    option = result.options[0]
    # 倍卡固定占 1 位；若第 1 回合仍缺充能才会再加一张开局充能礼装。
    assert option.functional_ce_count >= 1
    assert option.drop_ce_slots == 6 - option.functional_ce_count
    assert any("倍卡" in line for line in option.charge_plan)
    assert any("倍卡" in item for item in option.required_craft_essences)


def test_missing_start_charge_costs_drop_slots(tmp_path: Path) -> None:
    """没有充能技能时只能用开局充能礼装，掉落加成位相应减少。"""
    result = _run_support_case(tmp_path, with_charge_skill=False)
    option = result.options[0]
    assert option.functional_ce_count >= 1
    assert option.drop_ce_slots == 6 - option.functional_ce_count
    assert any("礼装占用" in line for line in option.charge_plan)
    assert any("占用" in item for item in option.required_craft_essences)


def test_card_restricted_buffs_only_count_for_matching_cards() -> None:
    """用户指出的问题：红卡辅助的“红卡性能提升”对绿卡宝具无效。"""
    entry = {
        "name": "红卡辅助",
        "class_name": "Assassin",
        "skills": [
            {
                "slot": 1,
                "name": "NFF特别服务",
                "effects": [
                    {
                        "kind": "card_up",
                        "value": 50,
                        "values": [50] * 10,
                        "duration": 3,
                        "target": "ally_one",
                        "source": "upCommandall",
                        "card": "buster",
                    },
                    {
                        "kind": "attack_up",
                        "value": 20,
                        "values": [20] * 10,
                        "duration": 3,
                        "target": "ally_one",
                        "source": "upAtk",
                        "card": "",
                    },
                ],
            }
        ],
    }
    summary = summarize_skills(entry, {1: 10})
    # 红卡打手：红卡性能 + 通用攻击力都吃满
    assert summary.ally_np_buff_sum("buster") == pytest.approx(0.7)
    # 绿卡打手：只吃通用攻击力，红卡性能必须被排除
    assert summary.ally_np_buff_sum("quick") == pytest.approx(0.2)


def _broadcast_case(tmp_path: Path):
    """主输出 + 第二输出 + 一名带全体充能/增伤的辅助。"""
    profile = _profile()
    store = CombatStore(tmp_path / "combat")
    store.save_profile(profile)
    stats = _stats(tmp_path, ["打手", "副手", "辅助"], ["Assassin", "Caster", "Caster"])
    skills = _skill_table(
        tmp_path,
        [
            _combat_servant("打手", "Assassin", []),
            _combat_servant("副手", "Caster", []),
            _combat_servant(
                "辅助",
                "Caster",
                [
                    {
                        "slot": 1,
                        "name": "全体充能与增伤",
                        "rank": "A",
                        "cooldowns": [7] * 10,
                        "effects": [
                            _effect("charge", 0.6, "ally_all", duration=0),
                            _effect("np_damage_up", 30, "ally_all"),
                        ],
                    },
                    {
                        "slot": 2,
                        "name": "自身强化",
                        "rank": "A",
                        "cooldowns": [7] * 10,
                        "effects": [_effect("attack_up", 50, "self")],
                    },
                ],
            ),
        ],
    )
    return recommend(
        RecommendationRequest(quest_id=profile.quest_id),
        store=store,
        account_store=_account(
            tmp_path,
            [("打手", "Assassin", 100, 10), ("副手", "Caster", 90, 10), ("辅助", "Caster", 90, 10)],
        ),
        stats=stats,
        skills=skills,
    )


def _option_with_support(result):
    """挑出「辅助」确实坐在辅助位的那一版方案。"""
    for option in result.options:
        if any(servant.name == "辅助" and servant.role == "support" for servant in option.required_servants):
            return option
    raise AssertionError("没有任何方案把「辅助」放在辅助位")


def test_broadcast_skill_is_cast_once_per_turn(tmp_path: Path) -> None:
    """回归：同一个技能在同一回合只能施放一次，不能对两名输出各放一次。"""
    option = _option_with_support(_broadcast_case(tmp_path))
    counts: dict[tuple[int, int, str], int] = {}
    for action in option.plan.actions:
        if action.action_type != "skill" or not action.skill_id:
            continue
        key = (action.turn, action.actor_slot, action.skill_id)
        counts[key] = counts.get(key, 0) + 1
    assert counts, "方案里应当有技能动作"
    assert max(counts.values()) == 1, counts


def test_broadcast_skill_reaches_every_attacker_in_one_action(tmp_path: Path) -> None:
    """全体充能写在一个动作里，受益者只能是前排；倍卡已给打手 +50% 开局宝具值，
    所以某个回合可能只有一名输出还缺充能。"""
    option = _option_with_support(_broadcast_case(tmp_path))
    action = next(a for a in option.plan.actions if a.skill_id == "全体充能与增伤")
    frontline_slots = {combatant.actor_slot for combatant in option.plan.combatants}
    attacker_names = {servant.name for servant in option.required_servants if servant.role != "support"}
    attacker_slots = {c.actor_slot for c in option.plan.combatants if c.name in attacker_names}
    charge_targets = {
        effect.target_actor_slot for effect in action.effects if effect.effect_type == "charge"
    }
    assert charge_targets
    assert charge_targets <= frontline_slots
    assert charge_targets & attacker_slots


def test_support_self_only_skill_never_targets_the_dps(tmp_path: Path) -> None:
    """用户强调过的规则：辅助的自身增益不能算到主输出头上。"""
    option = _option_with_support(_broadcast_case(tmp_path))
    action = next(a for a in option.plan.actions if a.skill_id == "自身强化")
    support_slot = next(
        combatant.actor_slot for combatant in option.plan.combatants if combatant.name == "辅助"
    )
    assert action.actor_slot == support_slot
    assert action.effects
    assert {effect.target_actor_slot for effect in action.effects} == {support_slot}


def test_conditional_buff_is_reported_and_not_counted_as_flat_damage() -> None:
    """条件特攻（对〔人类〕等）在缺少敌人特性数据时不能按固定伤害计入。"""
    entry = {
        "name": "条件辅助",
        "class_name": "Assassin",
        "skills": [
            {
                "slot": 2,
                "name": "杀戮技巧（人）",
                "effects": [
                    _effect("attack_up", 20, "ally_one"),
                    _effect(
                        "power_modifier",
                        50,
                        "ally_one",
                        condition="human",
                        condition_label="对〔人类〕特性对象造成的伤害提升",
                    ),
                ],
            }
        ],
    }
    summary = summarize_skills(entry, {2: 10})
    assert summary.ally_np_buff_sum("buster") == pytest.approx(0.2)
    assert any("对〔人类〕" in note for note in summary.modelling_notes)
