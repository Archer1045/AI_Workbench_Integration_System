from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from game_assistant.skill_effects import (
    build_skill_table,
    parse_skill,
    SkillTableStore,
)

ATLAS_CACHE = Path(
    os.environ.get(
        "FGO_ATLAS_CACHE",
        r"D:\workSpace\code\_research\fgo-py\atlas_cache\nice_servant_cn.json",
    )
)


def _skill(name: str, slot: int, functions: list[dict]) -> dict:
    return {
        "num": slot,
        "name": name,
        "rank": "A",
        "coolDown": list(range(9, 0, -1)),
        "functions": functions,
    }


def _func(func_type: str, target: str, buffs: list[str], values: list, turns: list | None = None) -> dict:
    turns = turns or [0] * len(values)
    return {
        "funcType": func_type,
        "funcTargetType": target,
        "buffs": [{"type": buff} for buff in buffs],
        "svals": [{"Value": value, "Turn": turn} for value, turn in zip(values, turns)],
    }


def test_charge_uses_np_fraction_scaling() -> None:
    skill = _skill("测试充能", 1, [_func("gainNp", "ptOne", [], [3000] * 10)])
    parsed = parse_skill(skill, level=10)
    charges = parsed.by_kind("charge")
    assert len(charges) == 1
    assert charges[0].value == pytest.approx(0.3)  # 3000 -> 30%
    assert charges[0].target == "ally_one"


def test_percent_buffs_scale_by_ten() -> None:
    skill = _skill(
        "测试增益",
        1,
        [
            _func("addStateShort", "self", ["upAtk"], [300] * 10, [3] * 10),
            _func("addStateShort", "self", ["upCriticaldamage"], [500] * 10, [3] * 10),
        ],
    )
    parsed = parse_skill(skill, level=10)
    assert parsed.by_kind("attack_up")[0].value == pytest.approx(30)
    assert parsed.by_kind("critical_up")[0].value == pytest.approx(50)
    assert parsed.by_kind("attack_up")[0].duration == 3


def test_star_regen_is_a_raw_count() -> None:
    skill = _skill("测试出星", 1, [_func("addStateShort", "self", ["regainStar"], [5] * 10, [3] * 10)])
    parsed = parse_skill(skill, level=10)
    assert parsed.by_kind("stars_per_turn")[0].value == 5


def test_self_targeted_buffs_never_leak_to_other_servants() -> None:
    """用户明确纠正过：泳装 BB 的自我改造只对她自己生效。"""
    skill = _skill(
        "自我改造（恋）",
        3,
        [
            _func("addStateShort", "self", ["upCriticaldamage"], [500] * 10, [3] * 10),
            _func("addStateShort", "self", ["upStarweight"], [8000] * 10, [3] * 10),
            _func("addStateShort", "self", ["upCriticalrate"], [150] * 10, [3] * 10),
        ],
    )
    parsed = parse_skill(skill, level=10)
    offensive = [e for e in parsed.effects if e.kind in {"critical_up", "star_weight_up", "crit_rate_up"}]
    assert offensive, "应当解析出暴击相关增益"
    assert {effect.target for effect in offensive} == {"self"}


def test_card_control_effects_are_recognised() -> None:
    skill = _skill(
        "空前绝后",
        1,
        [
            _func("addState", "ptOther", ["donotSelectCommandcard"], [None] * 10, [1] * 10),
            _func("cardReset", "self", [], [1] * 10),
            _func("gainStar", "self", [], [50] * 10),
        ],
    )
    parsed = parse_skill(skill, level=10)
    controls = {effect.source: effect for effect in parsed.by_kind("control")}
    assert controls["others_locked"].target == "ally_other"
    assert controls["shuffle"].target == "self"
    assert parsed.by_kind("stars")[0].value == 50


def test_hand_fix_control_is_recognised() -> None:
    skill = _skill("无貌之月", 3, [_func("addState", "self", ["fixCommandcard"], [None] * 10, [3] * 10)])
    parsed = parse_skill(skill, level=10)
    assert parsed.by_kind("control")[0].source == "hand_fixed"
    assert parsed.by_kind("control")[0].duration == 3


def test_indirect_functions_are_unmodeled_not_unmapped() -> None:
    skill = _skill(
        "间接函数",
        1,
        [
            _func("addState", "self", ["addIndividuality"], [10006] * 10, [1] * 10),
            _func("addStateShort", "self", ["commandattackAfterFunction"], [967958] * 10, [3] * 10),
        ],
    )
    parsed = parse_skill(skill, level=10)
    assert parsed.by_kind("unmapped") == []
    assert len(parsed.by_kind("unmodeled")) == 2


def test_skill_level_scaling_picks_the_right_row() -> None:
    skill = _skill("等级缩放", 1, [_func("addStateShort", "self", ["upAtk"], [100, 110, 120, 130, 140, 150, 160, 170, 180, 200], [3] * 10)])
    assert parse_skill(skill, level=1).by_kind("attack_up")[0].value == pytest.approx(10)
    assert parse_skill(skill, level=10).by_kind("attack_up")[0].value == pytest.approx(20)


def _buff(
    buff_type: str,
    name: str = "",
    detail: str = "",
    tvals: list[dict] | None = None,
    ck_op_indv: list[dict] | None = None,
    ck_self_indv: list[dict] | None = None,
) -> dict:
    return {
        "type": buff_type,
        "name": name or buff_type,
        "detail": detail,
        "tvals": tvals or [],
        "ckSelfIndv": ck_self_indv or [],
        "ckOpIndv": ck_op_indv or [],
    }


def _buff_func(
    func_type: str,
    target: str,
    buffs: list[dict],
    values: list,
    turns: list | None = None,
    functvals: list[dict] | None = None,
) -> dict:
    turns = turns or [0] * len(values)
    return {
        "funcType": func_type,
        "funcTargetType": target,
        "functvals": functvals or [],
        "buffs": buffs,
        "svals": [{"Value": value, "Turn": turn} for value, turn in zip(values, turns)],
    }


def test_trait_restricted_power_modifier_is_marked_conditional() -> None:
    """「威力提升〔龙〕」这类特攻只在敌人具备该特性时生效，不能当作固定增伤。"""
    skill = _skill(
        "屠龙",
        1,
        [
            _buff_func(
                "addStateShort",
                "self",
                [
                    _buff(
                        "upDamage",
                        name="威力提升〔龙〕",
                        detail="对〔龙〕特性对象造成的伤害提升",
                        tvals=[{"id": 501, "name": "dragon"}],
                        ck_op_indv=[{"id": 501, "name": "dragon"}],
                    )
                ],
                [500] * 10,
                [3] * 10,
            )
        ],
    )
    effect = parse_skill(skill, level=10).by_kind("power_modifier")[0]
    assert effect.condition == "dragon"
    assert "龙" in effect.condition_label


def test_field_and_hp_threshold_conditions_are_detected_from_text() -> None:
    """场地限制与血量阈值只写在 buff 文本里，同样要标记为条件。"""
    field_skill = _skill(
        "圣者的数字",
        1,
        [
            _buff_func(
                "addStateShort",
                "self",
                [_buff("upCommandall", detail="仅限于在有着〔阳光照射〕的战场，力指令卡性能提升")],
                [300] * 10,
                [3] * 10,
            )
        ],
    )
    hp_skill = _skill(
        "逆境的魅力",
        2,
        [
            _buff_func(
                "addStateShort",
                "ptAll",
                [_buff("upAtk", detail="当生命值低于99%时，攻击力提升")],
                [100] * 10,
                [3] * 10,
            )
        ],
    )
    assert parse_skill(field_skill, level=10).by_kind("card_up")[0].condition
    assert parse_skill(hp_skill, level=10).by_kind("attack_up")[0].condition


def test_form_marker_is_not_treated_as_a_condition() -> None:
    """图鉴里未解析的形态标记（unknown）不是敌人特性，不能排掉无条件的自身增益。"""
    skill = _skill(
        "怪力",
        1,
        [
            _buff_func(
                "addStateShort",
                "self",
                [_buff("upAtk", detail="攻击力提升")],
                [500] * 10,
                [3] * 10,
                functvals=[{"id": 600710, "name": "unknown"}],
            )
        ],
    )
    assert parse_skill(skill, level=10).by_kind("attack_up")[0].condition == ""


def test_build_skill_table_records_coverage(tmp_path: Path) -> None:
    atlas = tmp_path / "atlas.json"
    atlas.write_text(
        json.dumps(
            [
                {
                    "name": "测试从者",
                    "className": "caster",
                    "collectionNo": 1,
                    "starGen": 100,
                    "starAbsorb": 50,
                    "cards": ["1", "1", "1", "2", "2"],
                    "hitsDistribution": {},
                    "skills": [_skill("测试技能", 1, [_func("addStateShort", "self", ["upAtk"], [300] * 10, [3] * 10)])],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    payload = build_skill_table(atlas)
    assert payload["source"]["entries"] == 1
    servant = payload["servants"][0]
    assert servant["normalized_name"] == "测试从者"
    assert servant["skills"][0]["effects"][0]["kind"] == "attack_up"


@pytest.mark.skipif(not ATLAS_CACHE.exists(), reason="本机未找到 Atlas 缓存")
def test_real_catalog_values_match_official_skill_text() -> None:
    """用官方技能文案核对解析结果，避免缩放或目标域出错。"""
    table = build_skill_table(ATLAS_CACHE)

    def find(name: str, class_name: str, slot: int):
        # 只在本用例内复用同一套匹配规则
        store = SkillTableStore.__new__(SkillTableStore)
        store._payload = table
        store._index = None
        return store.skill(name, class_name, slot)

    waver = find("诸葛孔明〔埃尔梅罗Ⅱ世〕", "Caster", 1)
    charges = [e for e in waver["effects"] if e["kind"] == "charge"]
    assert charges and charges[0]["value"] == pytest.approx(0.3)
    assert charges[0]["target"] == "ally_one"

    skadi = find("斯卡哈·斯卡蒂", "Caster", 3)
    charges = [e for e in skadi["effects"] if e["kind"] == "charge"]
    assert charges and charges[0]["value"] == pytest.approx(0.5)

    olga = find("Ｕ－奥尔加玛丽", "Beast", 1)
    sources = {e["source"] for e in olga["effects"] if e["kind"] == "control"}
    assert {"others_locked", "shuffle"} <= sources
    assert any(e["kind"] == "stars" and e["value"] == 50 for e in olga["effects"])

    bb = find("BB", "MoonCancer", 3)
    if bb and any(e["source"] == "hand_fixed" for e in bb["effects"]):
        assert any(e["kind"] == "stars_per_turn" for e in bb["effects"])

    kawakami = find("河上彦斋", "Assassin", 2)
    weights = [e for e in kawakami["effects"] if e["kind"] == "star_weight_up"]
    assert weights and weights[0]["value"] == pytest.approx(500)
    assert all(e["target"] == "self" for e in weights)

    # 光之高扬斯卡娅「杀戮技巧（人）A」实际是两条条件特攻（〔人类〕+〔人之力〕），
    # 曾经被当成两条无条件增伤叠加，虚增了 +100%。
    fox = find("光之高扬斯卡娅", "Assassin", 2)
    power = [e for e in fox["effects"] if e["kind"] == "power_modifier"]
    assert len(power) == 2
    assert {e["condition"] for e in power} == {"human", "attributeHuman"}

    # 雨之魔女梣「逆境的魅力 A」只有一条无条件攻击力提升，其余是按血量阈值生效的。
    morgan = find("雨之魔女梣", "Caster", 2)
    attack = [e for e in morgan["effects"] if e["kind"] == "attack_up"]
    assert sum(1 for e in attack if not e["condition"]) == 1
    assert sum(1 for e in attack if e["condition"]) == 4
