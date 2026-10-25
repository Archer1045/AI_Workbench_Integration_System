"""第四步回归测试：必定暴击闸门（出星、集中、发牌控制、顺序）与暴击伤害口径。"""
from __future__ import annotations

import json

import pytest

from game_assistant.account_domain import ServantRecordInput
from game_assistant.account_store import AccountSnapshotStore
from game_assistant.combat_domain import (
    CombatEffect,
    CombatantSnapshot,
    CombatProfile,
    EnemyUnit,
    EnemyWave,
    SimulationRequest,
    TeamPlan,
    TeamPlanAction,
)
from game_assistant.combat_recommender import RecommendationRequest, control_cast_turn, recommend
from game_assistant.combat_simulator import card_slot_violations, simulate
from game_assistant.combat_store import CombatStore
from game_assistant.crit_model import evaluate_crit
from game_assistant.servant_stats import ServantStatsStore, lookup_entry, make_lookup
from game_assistant.skill_effects import SkillTableStore, get_skill_table


def _control(slug: str, target: str, duration: int) -> CombatEffect:
    return CombatEffect(
        effect_id=f"c-{slug}-{duration}",
        effect_type="control",
        target_actor_slot=1,
        duration_turns=duration,
        source="测试技能",
        notes=f"{slug}|target={target}",
    )


def _stars(value: float) -> CombatEffect:
    return CombatEffect(effect_id=f"s-{value}", effect_type="stars", value=value, target_actor_slot=1)


def _action(order: int, turn: int, effects: list[CombatEffect], actor: int = 1) -> TeamPlanAction:
    return TeamPlanAction(
        action_id=f"a-{order}",
        order=order,
        turn=turn,
        actor_slot=actor,
        action_type="skill",
        effects=effects,
    )


def test_rarity_disambiguates_same_name_servants() -> None:
    """同名从者（两条 `BB`）必须按稀有度消歧，否则手牌固定技能会整体丢失。"""
    index = make_lookup(
        [
            {"name": "同名", "class_name": "MoonCancer", "rarity": 4, "collection_no": 1},
            {"name": "同名", "class_name": "MoonCancer", "rarity": 5, "collection_no": 2},
        ]
    )
    assert lookup_entry(index, "同名", "MoonCancer", 5)["collection_no"] == 2
    assert lookup_entry(index, "同名", "MoonCancer", 4)["collection_no"] == 1

    table = get_skill_table()
    if not table.available():
        pytest.skip("本机没有技能表")
    entry = table.find("BB(SSR)", "MoonCancer", 5)
    assert entry is not None
    # 账号里的 BB(SSR) 是 5★ 水着 BB（collection 220），第 3 技能是手牌固定。
    assert entry["collection_no"] == 220
    slot3 = [skill for skill in entry["skills"] if skill["slot"] == 3]
    assert any(effect["kind"] == "control" and effect["source"] == "hand_fixed" for skill in slot3 for effect in skill["effects"])


def test_olga_skill_locks_others_for_one_turn() -> None:
    """奥尔加玛丽的「空前绝后 EX」是让其他人无法选卡，且只持续 1 回合。"""
    table = get_skill_table()
    if not table.available():
        pytest.skip("本机没有技能表")
    entry = table.find("U－奥尔加玛丽", "Beast", 5)
    assert entry is not None
    controls = [
        effect
        for skill in entry["skills"]
        if skill["slot"] == 1
        for effect in skill["effects"]
        if effect["kind"] == "control"
    ]
    locked = [effect for effect in controls if effect["source"] == "others_locked"]
    assert locked and locked[0]["target"] == "ally_other" and locked[0]["duration"] == 1


def test_star_threshold_and_concentration_are_both_required() -> None:
    gate = evaluate_crit(
        actions=[_action(1, 1, [_stars(60)])],
        crit_slot=1,
        names={1: "打手"},
    )
    assert gate.passed is False
    assert any("集中" in blocker for blocker in gate.blockers)


def test_crit_star_consumption_and_card_slot_rules() -> None:
    """用户确认的机制：单卡最多 10 星=100%，50 星=5 张满暴，宝具不暴击也不吃星。"""
    gate = evaluate_crit(
        actions=[_action(1, 3, [_control("others_locked", "ally_other", 1), _stars(50)])],
        crit_slot=1,
        names={1: "所长"},
    )
    assert gate.passed is True
    assert gate.stars_consumed == pytest.approx(10.0)
    assert gate.planned_crit_cards == 1
    lines = "\n".join(gate.plan("所长", "Buster"))
    assert "每张最多消耗 10 颗" in lines
    assert "门槛含义：50 星 = 5 张卡各 10 星" in lines
    assert "宝具不会暴击" in lines

    short = evaluate_crit(
        actions=[_action(1, 3, [_control("others_locked", "ally_other", 1), _stars(40)])],
        crit_slot=1,
        names={1: "所长"},
    )
    assert short.passed is False
    assert any("5 张卡各 10 星" in blocker for blocker in short.blockers)


def test_one_turn_lock_must_be_used_on_the_crit_turn() -> None:
    """1 回合的锁留在第 1 回合用，到第 3 回合补刀时已经失效。"""
    early = evaluate_crit(
        actions=[_action(1, 1, [_control("others_locked", "ally_other", 1), _stars(60)])],
        crit_slot=1,
        names={1: "所长"},
    )
    assert early.passed is False
    assert any("已失效" in note for note in early.control_order_notes)

    timed = evaluate_crit(
        actions=[_action(1, 3, [_control("others_locked", "ally_other", 1), _stars(60)])],
        crit_slot=1,
        names={1: "所长"},
    )
    assert timed.passed is True
    assert timed.concentrated and timed.card_access

    # 自动排程：1 回合的锁必须排到补刀回合；3 回合的手牌固定第 1 回合用即可。
    lock_skill = {"effects": [{"kind": "control", "duration": 1}]}
    fix_skill = {"effects": [{"kind": "control", "duration": 3}]}
    assert control_cast_turn(lock_skill) == 3
    assert control_cast_turn(fix_skill) == 1


def test_shuffle_after_hand_fix_invalidates_the_fix() -> None:
    """用户点名的顺序冲突：洗牌会强制解除此前的手牌固定。"""
    gate = evaluate_crit(
        actions=[
            _action(1, 1, [_control("hand_fixed", "self", 3), _stars(60)]),
            _action(2, 2, [_control("shuffle", "self", 0)]),
        ],
        crit_slot=1,
        names={1: "泳装BB"},
    )
    assert gate.card_access == ""
    assert gate.passed is False
    assert any("顺序冲突" in note for note in gate.control_order_notes)


def test_command_code_stars_focus_and_crit_damage_enter_the_gate() -> None:
    gate = evaluate_crit(
        actions=[_action(1, 3, [_control("hand_fixed", "self", 1), _stars(40)])],
        crit_slot=1,
        names={1: "打手"},
        command_code_stars=[("出星", 10)],
        command_code_focus=3.0,
        command_code_focus_source="集中",
        command_code_critical_up=0.2,
        command_code_critical_source="暴伤",
    )
    assert gate.passed is True
    assert gate.stars_available == pytest.approx(50.0)
    assert "指令纹章 集中" in gate.concentration_source
    assert gate.crit_damage_up == pytest.approx(0.2)
    assert any("指令纹章 暴伤" in note for note in gate.notes)


def _crit_profile() -> CombatProfile:
    return CombatProfile(
        quest_id="crit-test",
        event_id="crit-event",
        quest_name="暴击口径测试",
        mock=False,
        verified=True,
        waves=[
            {
                "wave_id": f"w{index}",
                "wave_index": index,
                "units": [
                    EnemyUnit(
                        enemy_id=f"w{index}_01",
                        name=f"稻草人{index}",
                        class_name="Rider",
                        level=10,
                        hp=1000000,
                    )
                ],
            }
            for index in (1, 2, 3)
        ],
    )


def _crit_plan(*, is_critical: bool, action_type: str) -> TeamPlan:
    action = TeamPlanAction(
        action_id="t1-a1",
        order=1,
        turn=1,
        actor_slot=1,
        action_type=action_type,  # type: ignore[arg-type]
        card_type="buster",
        is_critical=is_critical,
        effects=[
            CombatEffect(
                effect_id="crit-up",
                effect_type="critical_up",
                value=0.5,
                target_actor_slot=1,
                duration_turns=3,
            )
        ],
    )
    return TeamPlan(
        plan_id="crit-plan",
        quest_id="crit-test",
        title="暴击口径",
        combatants=[
            CombatantSnapshot(
                actor_slot=1,
                servant_record_id="owned-打手",
                name="打手",
                class_name="Assassin",
                attack=10000,
                hp=10000,
                class_attack_modifier=1.0,
                class_relation="neutral",
                np_multiplier=6.0,
            )
        ],
        actions=[action],
    )


def test_crit_damage_up_only_applies_to_critical_cards() -> None:
    """回归：暴击威力提升曾经被加进通用增益，连宝具伤害一起抬高。"""
    crit_attack = simulate(SimulationRequest(profile=_crit_profile(), plan=_crit_plan(is_critical=True, action_type="attack")))
    plain_attack = simulate(SimulationRequest(profile=_crit_profile(), plan=_crit_plan(is_critical=False, action_type="attack")))
    np_attack = simulate(SimulationRequest(profile=_crit_profile(), plan=_crit_plan(is_critical=False, action_type="np")))

    # 暴击 = 普通指令卡 × 2.0 × (1 + 50%)
    assert crit_attack.total_damage_avg == pytest.approx(plain_attack.total_damage_avg * 2.0 * 1.5)
    # 宝具不吃暴击威力
    assert np_attack.total_damage_avg == pytest.approx(
        plain_attack.total_damage_avg / 1.5 * 6.0, rel=1e-6
    )


def test_card_position_changes_card_damage() -> None:
    """卡位倍率：红卡第 1/2/3 位 = 1.5/1.8/2.1（宝具卡不套用）。"""
    damages = []
    for position in (1, 2, 3):
        plan = _crit_plan(is_critical=True, action_type="attack")
        plan.actions[0].card_position = position
        damages.append(
            simulate(SimulationRequest(profile=_crit_profile(), plan=plan)).total_damage_avg
        )
    assert damages[1] == pytest.approx(damages[0] * 1.8 / 1.5, rel=1e-6)
    assert damages[2] == pytest.approx(damages[0] * 2.1 / 1.5, rel=1e-6)
    assert damages[2] > damages[1] > damages[0]


def test_single_wave_profile_is_allowed_for_pillar_battles() -> None:
    """柱子战/冠位战是单面 1T：档案校验不能再强制"恰好 3 面"。"""
    from game_assistant.combat_domain import CombatProfile as Profile

    pillar = Profile(
        quest_id="pillar-test",
        event_id="grand-test",
        quest_name="柱子战样例",
        mock=False,
        verified=True,
        waves=[
            {
                "wave_id": "w1",
                "wave_index": 1,
                "units": [
                    EnemyUnit(enemy_id="w1_01", name="柱", class_name="Assassin", level=90, hp=900000)
                ],
            }
        ],
    )
    assert len(pillar.waves) == 1
    assert pillar.total_enemy_hp == 900000

    with pytest.raises(Exception):
        Profile(
            quest_id="bad",
            event_id="x",
            quest_name="面数不连续",
            waves=[
                {"wave_id": "w1", "wave_index": 1, "units": []},
                {"wave_id": "w3", "wave_index": 3, "units": []},
            ],
        )


def _crit_team_case(tmp_path):
    """主输出 + 一个像奥尔加玛丽那样能自己补刀的辅助。"""
    profile = _crit_profile()
    store = CombatStore(tmp_path / "combat")
    store.save_profile(profile)
    def stat_entry(name: str, class_name: str) -> dict:
        return {
            "name": name,
            "class_name": class_name,
            "rarity": 5,
            "lv_max": 100,
            "atk_max": 12000,
            "atk_growth": [12000] * 120,
            "hp_max": 14000,
            "np_card": 2,
            "np_target_type": "对人宝具",
            "np_damage_values": [12000, 16000, 18000, 19000, 20000],
        }

    path = tmp_path / "stats.json"
    path.write_text(
        json.dumps(
            {"source": {}, "servants": [stat_entry("打手", "Assassin"), stat_entry("所长", "Beast")]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    stats = ServantStatsStore(path)
    skills_path = tmp_path / "skills.json"
    skills_path.write_text(
        json.dumps(
            {
                "source": {},
                "servants": [
                    {
                        "name": "打手",
                        "class_name": "Assassin",
                        "collection_no": 1,
                        "cards": ["3", "2", "1", "1", "2"],
                        "star_gen": 100,
                        "star_absorb": 50,
                        "hit_distribution": {},
                        "skills": [],
                    },
                    {
                        "name": "所长",
                        "class_name": "Beast",
                        "collection_no": 2,
                        "cards": ["3", "2", "1", "1", "2"],
                        "star_gen": 100,
                        "star_absorb": 50,
                        "hit_distribution": {},
                        "skills": [
                            {
                                "slot": 1,
                                "name": "空前绝后",
                                "rank": "EX",
                                "cooldowns": [7] * 10,
                                "effects": [
                                    {
                                        "kind": "control",
                                        "value": 0.0,
                                        "values": [],
                                        "duration": 1,
                                        "target": "ally_other",
                                        "source": "others_locked",
                                    },
                                    {
                                        "kind": "stars",
                                        "value": 50.0,
                                        "values": [50.0] * 10,
                                        "duration": 0,
                                        "target": "self",
                                        "source": "gainStar",
                                    },
                                    {
                                        "kind": "critical_up",
                                        "value": 30.0,
                                        "values": [30.0] * 10,
                                        "duration": 3,
                                        "target": "ally_all",
                                        "source": "upCriticaldamage",
                                    },
                                ],
                            }
                        ],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    skills = SkillTableStore(skills_path)
    account = AccountSnapshotStore(tmp_path / "account.db")
    for name, class_name in (("打手", "Assassin"), ("所长", "Beast")):
        account.upsert_servant(
            ServantRecordInput(
                name=name,
                class_name=class_name,
                rarity=5,
                level=100,
                max_level=100,
                np_level=1,
                skill_1=10,
                skill_2=10,
                skill_3=10,
            )
        )
    return recommend(
        RecommendationRequest(quest_id="crit-test"),
        store=store,
        account_store=account,
        stats=stats,
        skills=skills,
    )


def test_generated_plan_fills_all_three_card_slots(tmp_path) -> None:
    """第 5 步：每个回合都要吃满 3 个卡位（宝具占 1 位）。

    此前只排了第 3 回合的暴击补刀，前两回合的空位被浪费——而攻略的结构是
    「宝具 + 2 张指令卡」，卡伤也是真实伤害。
    """
    result = _crit_team_case(tmp_path)
    plan = result.options[0].plan
    usage: dict[int, list[TeamPlanAction]] = {}
    for action in plan.actions:
        if action.action_type in {"np", "attack"}:
            usage.setdefault(action.turn, []).append(action)
    assert set(usage) == {1, 2, 3}, "三个回合都要有卡位安排"
    for turn, items in sorted(usage.items()):
        assert len(items) == 3, f"第 {turn} 回合应吃满 3 个卡位，实际 {len(items)}"
        assert sorted(item.card_position for item in items) == [1, 2, 3]
    fillers = [action for action in plan.actions if "-fill-" in action.action_id]
    assert fillers, "前两回合应有指令卡补位"
    assert all(action.action_type == "attack" and not action.is_critical for action in fillers)


def test_filler_cards_contribute_damage_to_the_simulation(tmp_path) -> None:
    """补位卡必须真的进入估算，否则排序里看不到卡伤。"""
    result = _crit_team_case(tmp_path)
    option = result.options[0]
    filler_sims = [
        action
        for turn in option.simulation.turns
        for action in turn.actions
        if "-fill-" in action.action_id
    ]
    assert filler_sims, "模拟结果里应包含补位卡"
    assert all(action.damage_avg > 0 for action in filler_sims)


def test_card_slot_rule_flags_overfilled_turns() -> None:
    """每回合 3 个卡位是游戏规则：超编必须被标出来，而不是悄悄算进伤害。"""
    profile = CombatProfile(
        quest_id="slot-rule",
        quest_name="卡位规则自检",
        waves=[
            EnemyWave(
                wave_id="w1",
                wave_index=1,
                units=[EnemyUnit(enemy_id="e1", name="敌人", class_name="Saber", hp=500_000)],
            )
        ],
    )
    actions = [
        TeamPlanAction(
            action_id=f"slot-{index}",
            order=index,
            turn=1,
            actor_slot=1,
            action_type="np" if index == 1 else "attack",
            card_type=None if index == 1 else "buster",
            card_position=min(3, index),
        )
        for index in range(1, 5)
    ]
    plan = TeamPlan(
        plan_id="slot-rule-plan",
        quest_id="slot-rule",
        title="4 个卡位的非法方案",
        combatants=[
            CombatantSnapshot(
                actor_slot=1,
                servant_record_id="s1",
                name="打手",
                class_name="Saber",
                attack=10_000,
                hp=10_000,
            )
        ],
        actions=actions,
    )
    violations = card_slot_violations(plan)
    assert violations and "第 1 回合" in violations[0]
    result = simulate(SimulationRequest(profile=profile, plan=plan))
    assert any("卡位" in warning for warning in result.warnings)


def test_recommendation_emits_guaranteed_crit_finisher(tmp_path) -> None:
    result = _crit_team_case(tmp_path)
    option = result.options[0]
    assert option.crit_gate_passed is True, option.crit_plan
    assert any("通过" in line for line in option.crit_plan)
    crit_actions = [action for action in option.plan.actions if action.is_critical]
    # 单输出结构下第 3 回合有 2 个空卡位（宝具占 1 个），因此最多 2 张暴击卡。
    assert 1 <= len(crit_actions) <= 2
    assert crit_actions[0].action_type == "attack"
    assert crit_actions[0].turn == 3
    assert [action.card_position for action in crit_actions] == list(
        range(crit_actions[0].card_position, crit_actions[0].card_position + len(crit_actions))
    )
    # 锁必须在补刀回合仍然生效：它只持续 1 回合，所以只能在第 3 回合使用。
    lock_actions = [
        action
        for action in option.plan.actions
        if any(effect.effect_type == "control" for effect in action.effects)
    ]
    assert lock_actions and all(action.turn == 3 for action in lock_actions)


def test_event_damage_ce_is_equipped_on_the_dps(tmp_path) -> None:
    """用户确认：打手带满破倍卡礼装（+100% 伤害、开局 +50% 宝具值），不是随便假设的礼装。"""
    result = _crit_team_case(tmp_path)
    option = result.options[0]
    ce_actions = [action for action in option.plan.actions if "倍卡" in action.skill_id]
    assert len(ce_actions) == 1
    effect = ce_actions[0].effects[0]
    assert effect.effect_type == "power_modifier"
    assert effect.value == pytest.approx(1.0)
    assert effect.target_actor_slot == ce_actions[0].actor_slot
    assert any("倍卡" in line for line in option.charge_plan)
    assert option.functional_ce_count >= 1
