"""目录侧知识库回归测试（指令纹章 / 概念礼装 / 魔术礼装）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import config
from game_assistant.combat_store import CombatStore
from game_assistant.knowledge_base import LIBRARIES, OUTPUT, build_library
from game_assistant.craft_essence import CraftEssenceStore, get_craft_essence_store

KB_DIR = Path(config.AI_PRODUCT_DIR) / "game_assistant_kb"
ATLAS_DIR = Path(r"D:\workSpace\code\_research\fgo-py\atlas_cache")


def _load(library: str) -> dict:
    path = KB_DIR / OUTPUT[library]
    if not path.exists():
        pytest.skip(f"知识库尚未生成：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def test_command_codes_library_covers_the_catalog() -> None:
    payload = _load("command_codes")
    assert payload["library"] == "command_codes"
    assert payload["source"]["kept"] > 150
    names = {item["name"] for item in payload["items"]}
    assert "花之魔术师" in names, "指令纹章库必须包含花之魔术师"


def test_flower_magus_detail_keeps_the_charge_and_cooldown() -> None:
    """纹章机制只写在文案里：+10% 宝具值、使用后需等待 3 回合。"""
    item = next(x for x in _load("command_codes")["items"] if x["name"] == "花之魔术师")
    assert "宝具值增加10%" in item["detail"].replace(" ", "")
    assert "3回合" in item["detail"].replace(" ", "")


def test_craft_essence_library_has_effects_and_stats() -> None:
    payload = _load("craft_essences")
    assert payload["source"]["kept"] > 2000
    with_effects = [item for item in payload["items"] if item["effects"]]
    assert len(with_effects) > 1000, "多数礼装应当解析出效果"
    assert all("atk_max" in item for item in payload["items"])


def test_mystic_code_library_has_cooldown_reduction() -> None:
    """阿特拉斯院制服技能 3 = 技能冷却减少 2 回合（2T 的关键）。"""
    items = _load("mystic_codes")["items"]
    atlas = next(x for x in items if "阿特拉斯院制服" in x["name"])
    assert atlas["max_lv"] == 10
    skill3 = next(skill for skill in atlas["skills"] if skill["slot"] == 3)
    assert any(effect["value"] == pytest.approx(2.0) for effect in skill3["effects"])


def test_builder_is_rerunnable(tmp_path: Path) -> None:
    if not (ATLAS_DIR / "nice_command_code_cn.json").exists():
        pytest.skip("本机没有 Atlas 导出缓存")
    target = build_library("command_codes", ATLAS_DIR, tmp_path)
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["source"]["kept"] == len(payload["items"])
    assert set(LIBRARIES) == {
        "command_codes",
        "craft_essences",
        "mystic_codes",
        "materials",
        "events_cn",
        "events_jp",
        "class_boards",
    }


def test_class_board_library_has_nodes_and_costs() -> None:
    """职阶天赋树：每职阶一张，节点要能给出素材消耗与解锁闸门。"""
    payload = _load("class_boards")
    assert payload["source"]["kept"] == 15, "国服应有 15 个职阶的天赋树"
    saber = next(item for item in payload["items"] if item["name"] == "剑士")
    assert saber["square_count"] > 50
    # 树级解锁素材（星座开放道具）
    assert any(material["name"] == "星光之砂" for material in saber["board_materials"])
    first = next(square for square in saber["squares"] if square["costs"])
    assert any(cost["name"] == "量子" for cost in first["costs"])
    assert any(cost["name"] for cost in first["costs"])


def test_class_board_nodes_carry_effects_and_gates() -> None:
    """节点效果必须可读：被动强化带 name/detail，闸门带解锁道具，令咒节点标为已知缺口。

    背景（2026-10-11）：效果此前被当成 `functions`/`buffs` 读取 → 全部为空；
    实测效果内联在 `targetSkill`，而 `skillType` 只有 passive / commandSpell / none 三类。
    """
    payload = _load("class_boards")
    squares = [square for board in payload["items"] for square in board["squares"]]
    kinds = {square["effect_kind"] for square in squares}
    assert kinds == {"passive", "commandSpell", "gate"}

    passive = [square for square in squares if square["effect_kind"] == "passive"]
    assert len(passive) >= 600, "被动强化节点应有 600+ 个"
    assert all(square["effect"]["name"] for square in passive), "每个被动节点都要有技能名"
    assert any(square["effect"]["detail"] for square in passive), "至少要有可读的数值描述"
    assert any(square["effect"]["up_skill_lv"] for square in passive), "要记录强化到的等级"

    gates = [square for square in squares if square["effect_kind"] == "gate"]
    assert gates and all(square["effect_kind"] == "gate" for square in gates)
    assert any(
        any(item["name"] for item in square["lock_items"]) for square in gates
    ), "闸门节点要带解锁道具（例如新星火炬）"

    spells = [square for square in squares if square["effect_kind"] == "commandSpell"]
    assert spells, "令咒强化节点存在（效果表 Atlas CN 未提供，只留图标线索）"
    assert all(square["effect"]["icon"] for square in spells)


def test_event_war_names_resolve() -> None:
    """活动关联关卡名必须能解析（2026-10-11 修复）。

    背景：早前整批 `war_names` 为空，被记为"id 空间不符"的缺口；实测战争表里其实有这些 id，
    重新构建后日服 175/1491、国服 162/2073 条活动能解析出关卡名（点名的 war 8412 也能）。
    """
    jp = _load("events_jp")["items"]
    named = [row for row in jp if any(row.get("war_names") or [])]
    assert len(named) > 100, "日服应有 100+ 条活动能解析出关卡名"
    target = next((row for row in jp if 8412 in (row.get("war_ids") or [])), None)
    assert target is not None, "war 8412 所属活动应存在"
    assert len(target["war_names"]) == len(target["war_ids"]), "关卡名要与 war_ids 一一对应"
    assert any(name.strip() for name in target["war_names"]), "war 8412 应解析出名字"
    cn = _load("events_cn")["items"]
    assert len([row for row in cn if any(row.get("war_names") or [])]) > 100


def test_event_library_can_answer_material_queries() -> None:
    """「缺素材 X → 哪些活动给」必须可查：商店全量 + 奖励对象已解析成名字。"""
    jp = _load("events_jp")
    rows = [
        item
        for item in jp["items"]
        if item["type"] == "eventQuest" and (item["started_at"] or 0) >= 1_750_000_000
    ]
    assert rows, "应当有近期日服活动"
    # 商店不再截断在 40 项
    assert max(len(item["shop_items"]) for item in rows) > 40
    # 奖励对象解析出了素材名（否则等于查不了）
    named_rewards = [
        name
        for item in rows
        for _item_id, name, _type in item.get("reward_items") or []
        if name
    ]
    assert named_rewards, "奖励对象必须解析出名称"
    # 对照素材：伝承結晶 能在若干活动的商店里查到（证明查询链通）
    assert sum(1 for item in rows if any("伝承結晶" in s["name"] for s in item["shop_items"])) >= 1


def test_event_libraries_support_cn_future_candidates() -> None:
    """未来活动靠「日服有、国服无」的差集得到；国服条数应多于日服导出。"""
    from game_assistant.knowledge_base import cn_future_candidates

    cn, jp = _load("events_cn"), _load("events_jp")
    assert cn["source"]["kept"] > 1000 and jp["source"]["kept"] > 1000
    rows = cn_future_candidates(cn, jp, limit=5, since=0)
    assert rows, "应当能找出日服独有活动"
    assert all(item["war_ids"] for item in rows), "候选必须是带实际关卡的正式活动"
    assert [int(r["started_at"]) for r in rows] == sorted(
        (int(r["started_at"]) for r in rows), reverse=True
    ), "候选按时间倒序，最近的排前面"


def test_material_library_has_skill_up_materials() -> None:
    """素材名库必须能查到强化/再临素材（例：祸骨、虚影之尘）。"""
    payload = _load("materials")
    assert payload["source"]["kept"] > 500
    by_name = {item["name"]: item for item in payload["items"]}
    bone = by_name.get("祸骨")
    assert bone is not None and bone["type"] == "skillLvUp"
    assert "素材" in bone["detail"]
    # 掉落关卡信息不在 Atlas 里：库里只应有名称与说明，不该假装有 drop 表
    assert not any("drop_infos" in item for item in payload["items"])


def test_craft_essence_store_classifies_and_names_real_ces() -> None:
    """充能/增伤分类必须来自真实礼装库，并能给出真名（例：满充能 → 万华镜）。"""
    store = get_craft_essence_store()
    if not store.available():
        pytest.skip("概念礼装库尚未生成")
    by_name = {item["name"]: item for item in store.items}
    mankakyou = next((item for name, item in by_name.items() if "万华镜" in name), None)
    assert mankakyou is not None, "礼装库必须包含万华镜"
    assert store.starting_charge(mankakyou) >= 0.8

    label = store.label_for_charge(1.0)
    assert "宝具值" in label and "（+100% 宝具值）" in label
    chosen = store.best_starting_charge(0.5)
    assert chosen is not None and store.starting_charge(chosen) >= 0.5

    damaged = [item for item in store.items if store.damage_bonus(item) > 0.2]
    assert len(damaged) > 100, "应能识别出大量增伤礼装"


def test_charge_plan_uses_real_ce_name_when_library_exists() -> None:
    """规划器给出的礼装名应来自礼装库，而不是抽象档位。"""
    store = CraftEssenceStore()
    if not store.available():
        pytest.skip("概念礼装库尚未生成")
    from game_assistant.combat_recommender import _ce_requirements

    assert "倍卡" in _ce_requirements(1)[0]


def test_friend_support_considers_catalog_servants(tmp_path: Path) -> None:
    """`include_friend_support` 应把目录侧未持有的从者放进候选（借好友助战）。"""
    from game_assistant.account_domain import ServantRecordInput
    from game_assistant.account_store import AccountSnapshotStore
    from game_assistant.combat_domain import RecommendationConstraints, RecommendationRequest
    from game_assistant.combat_recommender import recommend

    profile = CombatStore().get_profile("fgo-cn-2026-gudaguda9-90pp")
    if profile is None:
        pytest.skip("缺少 90++ 战斗档案")
    account = AccountSnapshotStore(tmp_path / "account.db")
    account.upsert_servant(
        ServantRecordInput(
            name="玛修·基列莱特",
            class_name="Shielder",
            rarity=4,
            level=90,
            max_level=90,
            np_level=1,
            skill_1=10,
            skill_2=10,
            skill_3=10,
        )
    )
    result = recommend(
        RecommendationRequest(
            quest_id=profile.quest_id,
            constraints=RecommendationConstraints(include_friend_support=True, max_options=1),
        ),
        account_store=account,
    )
    assert result.options, "启用好友助战后仍应给出方案"
    names = {servant.name for option in result.options for servant in option.required_servants}
    assert any(name != "玛修·基列莱特" for name in names), "应当从目录侧补入助战/队友候选"
    assert any(
        "好友助战" in item
        for option in result.options
        for item in option.assumptions
    ), "方案必须写明助战投入是按保守假设评估的"
    assert any(
        combatant.servant_record_id.startswith("friend-")
        for option in result.options
        for combatant in option.plan.combatants
    ), "助战从者在计划里必须区分为 friend-"
