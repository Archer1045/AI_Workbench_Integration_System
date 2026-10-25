"""别名解析 + 同名变体不静默取一只 的回归测试。"""
from __future__ import annotations

import json

import pytest

from game_assistant import alias as alias_mod
from game_assistant import battle_plan as plan_mod


def test_normalize_folds_full_width_and_brackets() -> None:
    assert alias_mod.normalize("莫德雷德（Rider）") == alias_mod.normalize("莫德雷德(rider)")
    assert alias_mod.normalize(" 泳装 C呆 ") == alias_mod.normalize("泳装C呆")
    assert alias_mod.normalize("贝拉·丽莎") == alias_mod.normalize("贝拉丽莎")


def test_user_alias_resolves_to_official_name(tmp_path) -> None:
    table = tmp_path / "alias_user.json"
    table.write_text(json.dumps({"aliases": [
        {"alias": "泳装C呆", "domain": "servant", "target": "阿尔托莉雅·卡斯特",
         "class_name": "Berserker", "confirmed": "2026-10-13"},
        {"alias": "贝拉丽莎", "domain": "craft_essence", "target": "贝拉·丽莎",
         "confirmed": "2026-10-13"},
    ]}, ensure_ascii=False), encoding="utf-8")

    hit = alias_mod.resolve("泳装C呆", user_path=table, servant_path=tmp_path / "none.json")
    assert hit.matched and hit.target == "阿尔托莉雅·卡斯特" and hit.class_name == "Berserker"
    # 域要对上：礼装别名在从者域里不该命中
    miss = alias_mod.resolve("贝拉丽莎", user_path=table, servant_path=tmp_path / "none.json")
    assert not miss.matched and miss.target == "贝拉丽莎"
    essence = alias_mod.resolve(
        "贝拉丽莎", domain=alias_mod.CRAFT_ESSENCE, user_path=table, servant_path=tmp_path / "none.json"
    )
    assert essence.matched and essence.target == "贝拉·丽莎"


def test_unknown_alias_passes_through_without_fuzzy_match(tmp_path) -> None:
    result = alias_mod.resolve("某个不存在的简称", user_path=tmp_path / "none.json",
                               servant_path=tmp_path / "none.json")
    assert not result.matched and not result.ambiguous
    assert result.target == "某个不存在的简称"


def test_same_alias_two_targets_is_ambiguous(tmp_path) -> None:
    table = tmp_path / "alias_user.json"
    table.write_text(json.dumps({"aliases": [
        {"alias": "呆毛", "domain": "servant", "target": "阿尔托莉雅·潘德拉贡", "class_name": "Saber"},
        {"alias": "呆毛", "domain": "servant", "target": "阿尔托莉雅·卡斯特", "class_name": "Caster"},
    ]}, ensure_ascii=False), encoding="utf-8")

    result = alias_mod.resolve("呆毛", user_path=table, servant_path=tmp_path / "none.json")
    assert result.ambiguous and not result.matched
    assert len(result.candidates) == 2


def test_alias_kind_is_reported(tmp_path) -> None:
    table = tmp_path / "alias_user.json"
    table.write_text(json.dumps({"aliases": [
        {"alias": "C呆", "domain": "servant", "target": "阿尔托莉雅·卡斯特",
         "class_name": "Caster", "kind": "abbr", "confirmed": "2026-10-13"},
    ]}, ensure_ascii=False), encoding="utf-8")

    hit = alias_mod.resolve("C呆", user_path=table, servant_path=tmp_path / "none.json")

    assert hit.matched and hit.kind == "abbr"
    assert "abbr" in hit.report()


def test_official_name_passes_through_and_unknown_alias_is_flagged(tmp_path) -> None:
    """第四态：既是别名表外、又不是正式名/账号名 ⇒ 明确标成"疑似未收录简称"。"""
    table = tmp_path / "alias_user.json"
    table.write_text(json.dumps({"aliases": []}, ensure_ascii=False), encoding="utf-8")

    # 正式名本身就在账号名表里（账号名→图鉴名，含职阶），所以它是"命中"而不是"未收录"
    official = alias_mod.resolve("阿尔托莉雅·卡斯特", user_path=table)
    assert official.matched and official.kind == "account" and not official.unknown_alias

    stranger = alias_mod.resolve("某个没收录的缩写xyz", user_path=table)
    assert stranger.unknown_alias and not stranger.matched
    assert "疑似" in stranger.report()


def test_apply_to_text_prefers_longest_alias(tmp_path) -> None:
    table = tmp_path / "alias_user.json"
    table.write_text(json.dumps({"aliases": [
        {"alias": "C呆", "domain": "servant", "target": "阿尔托莉雅·卡斯特", "class_name": "Caster"},
        {"alias": "泳装C呆", "domain": "servant", "target": "阿尔托莉雅·卡斯特", "class_name": "Berserker"},
    ]}, ensure_ascii=False), encoding="utf-8")

    text, changes = alias_mod.apply_to_text(
        "1T 泳装C呆开宝具，2T C呆开宝具", user_path=table, servant_path=tmp_path / "none.json"
    )

    assert text.startswith("1T 阿尔托莉雅·卡斯特(Berserker)开宝具")
    assert "阿尔托莉雅·卡斯特(Caster)开宝具" in text
    assert ("泳装C呆", "阿尔托莉雅·卡斯特(Berserker)") in changes


def test_apply_to_text_leaves_unknown_words_alone(tmp_path) -> None:
    table = tmp_path / "alias_user.json"
    table.write_text(json.dumps({"aliases": []}, ensure_ascii=False), encoding="utf-8")

    text, changes = alias_mod.apply_to_text(
        "随便一句没有别名的话", user_path=table, servant_path=tmp_path / "none.json"
    )

    assert text == "随便一句没有别名的话" and changes == []


def test_craft_essence_find_resolves_alias() -> None:
    from game_assistant import craft_essence

    store = craft_essence.get_craft_essence_store()
    if not store.available():
        pytest.skip("本机没有礼装库")

    item = store.find("贝拉丽莎")

    assert item is not None and item.get("name") == "贝拉·丽莎"


def test_guide_extraction_feeds_aliases_through_the_table() -> None:
    """攻略抽取的正文字段必须过别名表（防止以后重构时把这一步丢掉）。"""
    from pathlib import Path

    source = Path("game_assistant/source_service.py").read_text(encoding="utf-8")

    assert "alias_mod.apply_to_text(record.text" in source


def _skills_payload() -> dict:
    return {"servants": [
        {"name": "莫德雷德", "class_name": "Saber", "skills": [{"slot": 1, "name": "魔力放出 A"}]},
        {"name": "莫德雷德", "class_name": "Rider", "skills": [{"slot": 1, "name": "夏日冲浪 A"}]},
        {"name": "梅林", "class_name": "Caster", "skills": [{"slot": 1, "name": "幻术 A"}]},
    ]}


def test_skill_table_does_not_silently_pick_one_variant(tmp_path) -> None:
    path = tmp_path / "skills.json"
    path.write_text(json.dumps(_skills_payload(), ensure_ascii=False), encoding="utf-8")
    table = plan_mod.load_skill_table(path)

    assert table[plan_mod._norm("梅林")][0]["name"] == "幻术 A"
    assert plan_mod.AMBIGUOUS_MARK in table[plan_mod._norm("莫德雷德")][0]
    assert table[plan_mod._norm("莫德雷德(Rider)")][0]["name"] == "夏日冲浪 A"
    assert table[plan_mod._norm("莫德雷德(Saber)")][0]["name"] == "魔力放出 A"


def test_plan_rejects_bare_ambiguous_servant_name(tmp_path, monkeypatch) -> None:
    path = tmp_path / "skills.json"
    path.write_text(json.dumps(_skills_payload(), ensure_ascii=False), encoding="utf-8")
    table = plan_mod.load_skill_table(path)

    def spec(actor: str) -> dict:
        return {"quest_id": "q", "title": "t", "team": [{"name": actor}], "steps": [
            {"turn": 1, "actor": actor, "kind": "skill", "skill_slot": 1},
            {"turn": 1, "actor": actor, "kind": "np"},
            {"turn": 1, "actor": actor, "kind": "card", "card": "any", "position": "leftmost"},
            {"turn": 1, "actor": actor, "kind": "card", "card": "any", "position": "leftmost"},
        ]}

    with pytest.raises(plan_mod.PlanError, match="同名从者"):
        plan_mod.compile_plan(spec("莫德雷德"), skill_table=table)

    plan = plan_mod.compile_plan(spec("莫德雷德(Rider)"), skill_table=table)
    assert plan.actions[0].skill_index == 1
