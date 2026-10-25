from __future__ import annotations

import json
from pathlib import Path

import pytest

from game_assistant.account_domain import ServantRecordInput
from game_assistant.account_store import AccountSnapshotStore
from game_assistant.combat_domain import (
    CraftEssenceConfirmation,
    ExecutionPreflightRequest,
    RecommendationConstraints,
    RecommendationRequest,
)
from game_assistant.combat_recommender import (
    class_multiplier,
    dominant_enemy_class,
    recommend,
    relation_encoding,
)
from game_assistant.combat_store import CombatStore
from game_assistant.craft_essence_confirmation import CraftEssenceConfirmationStore
from game_assistant.execution_preflight import preflight
from game_assistant.quest_profile_import import (
    build_profile,
    find_quest_section,
    parse_quest_section,
)
from game_assistant.servant_stats import ServantStatsStore

SECTION_HTML = Path(__file__).resolve().parent / "data" / "mooncell_90pp_section.html"
QUEST_HEADING = "神剑改_燃烧吧翡翠剑"


def _real_profile():
    html = SECTION_HTML.read_text(encoding="utf-8")
    parsed = parse_quest_section(find_quest_section(html, QUEST_HEADING))
    return build_profile(
        parsed,
        quest_id="test-90pp",
        event_id="test-event",
        quest_name="神剑改 燃烧吧翡翠剑（90++）",
        source_ids=["src-test"],
        source_url="https://fgo.wiki/w/example",
    )


def _synthetic_stats(tmp_path: Path) -> ServantStatsStore:
    payload = {
        "source": {"name": "test"},
        "servants": [
            {
                "name": "优势杀手",
                "battle_name": "",
                "class_name": "Assassin",
                "rarity": 5,
                "lv_max": 90,
                "atk_max": 12000,
                "atk_growth": [9000] * 90 + [12000] * 30,
                "hp_max": 13000,
                "np_card": 2,
                "np_target_type": "对人宝具",
                "np_damage_values": [12000, 16000, 18000, 19000, 20000],
            },
            {
                "name": "备选杀手",
                "battle_name": "",
                "class_name": "Assassin",
                "rarity": 4,
                "lv_max": 80,
                "atk_max": 9000,
                "atk_growth": [7000] * 80 + [9000] * 40,
                "hp_max": 11000,
                "np_card": 3,
                "np_target_type": "对人宝具",
                "np_damage_values": [12000, 16000, 18000, 19000, 20000],
            },
            {
                "name": "辅助宝具从者",
                "battle_name": "",
                "class_name": "Assassin",
                "rarity": 4,
                "lv_max": 80,
                "atk_max": 10000,
                "atk_growth": [8000] * 80 + [10000] * 40,
                "hp_max": 12000,
                "np_card": 1,
                "np_target_type": "对军宝具",
                "np_damage_values": [],
            },
        ],
    }
    path = tmp_path / "servant_stats.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return ServantStatsStore(path)


def _synthetic_account(tmp_path: Path) -> AccountSnapshotStore:
    store = AccountSnapshotStore(tmp_path / "account.db")
    entries = [
        ("优势杀手", "Assassin", 5, 90, 3, 10),
        ("备选杀手", "Assassin", 4, 80, 5, 10),
        ("辅助宝具从者", "Assassin", 4, 80, 2, 10),
    ]
    for name, class_name, rarity, level, np_level, skill in entries:
        store.upsert_servant(
            ServantRecordInput(
                name=name,
                class_name=class_name,
                rarity=rarity,
                level=level,
                max_level=90,
                np_level=np_level,
                skill_1=skill,
                skill_2=skill,
                skill_3=skill,
            )
        )
    return store


# --- Class relations ------------------------------------------------------


def test_class_multiplier_follows_the_fgo_triangles() -> None:
    # 克制倍率还要乘 Atlas 职阶攻击率（Assassin 0.9）。
    assert class_multiplier("Assassin", "Rider") == pytest.approx(1.8)
    assert class_multiplier("Rider", "Assassin") == 0.5
    assert class_multiplier("Caster", "Assassin") == pytest.approx(1.8)
    assert class_multiplier("Saber", "Lancer") == 2.0
    assert class_multiplier("Berserker", "Rider") == pytest.approx(1.65)
    assert class_multiplier("Berserker", "Shielder") == pytest.approx(1.1)
    # 额外职阶来自 Atlas 全量表：Ruler 攻击率 1.1、Beast 对 Rider 1.5。
    assert class_multiplier("Ruler", "Rider") == pytest.approx(1.1)
    assert class_multiplier("Assassin", "Beast") == pytest.approx(0.45)
    assert class_multiplier("Beast", "Rider") == pytest.approx(1.5)
    assert class_multiplier("", "Rider") == 1.0


def test_relation_encoding_matches_simulator_buckets() -> None:
    assert relation_encoding(2.0) == ("advantage", 1.0)
    relation, modifier = relation_encoding(1.5)
    assert relation == "advantage"
    assert round(modifier * 2.0, 4) == 1.5
    assert relation_encoding(1.0) == ("neutral", 1.0)
    assert relation_encoding(0.5) == ("disadvantage", 1.0)


# --- Quest parsing --------------------------------------------------------


def test_parse_90pp_section_extracts_real_waves() -> None:
    html = SECTION_HTML.read_text(encoding="utf-8")
    parsed = parse_quest_section(find_quest_section(html, QUEST_HEADING))
    assert parsed.recommended_level == "90++"
    assert parsed.ap_cost == 40
    assert [wave.wave_index for wave in parsed.waves] == [1, 2, 3]
    assert [[enemy.hp for enemy in wave.enemies] for wave in parsed.waves] == [
        [71861],
        [475056, 40748],
        [66784, 984960],
    ]
    assert all(enemy.class_name == "Rider" for wave in parsed.waves for enemy in wave.enemies)
    assert parsed.total_enemy_hp == 1_639_409
    assert parsed.warnings == []


def test_built_profile_is_real_but_unverified() -> None:
    profile = _real_profile()
    assert profile.mock is False
    assert profile.verified is False
    assert profile.ap_cost == 40
    assert profile.total_enemy_hp == 1_639_409
    assert profile.source_ids == ["src-test"]
    assert any("游戏内实测确认" in note for note in profile.notes)
    assert dominant_enemy_class(profile) == "Rider"


def test_find_quest_section_rejects_missing_heading() -> None:
    with pytest.raises(ValueError):
        find_quest_section("<html></html>", "不存在的关卡")


# --- Recommendation -------------------------------------------------------


def test_recommend_prefers_class_advantage_and_reports_gates(tmp_path: Path) -> None:
    profile = _real_profile()
    store = CombatStore(tmp_path / "combat")
    store.save_profile(profile)
    result = recommend(
        RecommendationRequest(quest_id=profile.quest_id),
        store=store,
        account_store=_synthetic_account(tmp_path),
        stats=_synthetic_stats(tmp_path),
    )
    assert result.profile_mock is False
    assert result.profile_verified is False
    assert result.dominant_enemy_class == "Rider"
    assert result.options, "至少应生成一个候选方案"

    option = result.options[0]
    assert option.required_servants[0].name == "优势杀手"
    assert all(
        servant.damage_multiplier == pytest.approx(1.8)
        for servant in option.required_servants
    )
    assert option.bond_slots >= 2
    assert option.simulation.total_turns >= 1
    assert option.assumptions and option.failure_conditions and option.missing_data
    assert option.required_craft_essences
    assert option.plan.quest_id == profile.quest_id
    assert len(option.plan.combatants) == len(option.required_servants)
    # 每名主力每回合一个宝具动作，外加打手的倍卡礼装动作；
    # 第 5 步起每个回合还要吃满 3 个卡位（宝具占 1 位，其余由指令卡补位）。
    np_actions = [action for action in option.plan.actions if action.action_type == "np"]
    assert len(np_actions) == 3 * len(option.required_servants)
    assert any("event-ce" in action.action_id for action in option.plan.actions)
    per_turn: dict[int, int] = {}
    for action in option.plan.actions:
        if action.action_type in {"np", "attack"}:
            per_turn[action.turn] = per_turn.get(action.turn, 0) + 1
    assert per_turn == {1: 3, 2: 3, 3: 3}, per_turn


def test_recommend_skips_support_only_noble_phantasms(tmp_path: Path) -> None:
    profile = _real_profile()
    store = CombatStore(tmp_path / "combat")
    store.save_profile(profile)
    result = recommend(
        RecommendationRequest(quest_id=profile.quest_id),
        store=store,
        account_store=_synthetic_account(tmp_path),
        stats=_synthetic_stats(tmp_path),
    )
    used = {servant.name for option in result.options for servant in option.required_servants}
    assert "辅助宝具从者" not in used
    assert any("辅助型" in note for note in result.notes)


def test_recommend_respects_required_servant_limit(tmp_path: Path) -> None:
    profile = _real_profile()
    store = CombatStore(tmp_path / "combat")
    store.save_profile(profile)
    result = recommend(
        RecommendationRequest(
            quest_id=profile.quest_id,
            constraints=RecommendationConstraints(max_required_servants=2, max_options=2),
        ),
        store=store,
        account_store=_synthetic_account(tmp_path),
        stats=_synthetic_stats(tmp_path),
    )
    assert len(result.options) == 2
    assert all(len(option.required_servants) <= 2 for option in result.options)
    assert all(option.bond_slots >= 4 for option in result.options)


def test_recommend_rejects_unknown_quest(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        recommend(
            RecommendationRequest(quest_id="missing-quest"),
            store=CombatStore(tmp_path / "combat"),
            account_store=_synthetic_account(tmp_path),
            stats=_synthetic_stats(tmp_path),
        )


def test_recommended_plan_is_persisted_so_preflight_can_reference_it(tmp_path: Path) -> None:
    profile = _real_profile()
    store = CombatStore(tmp_path / "combat")
    store.save_profile(profile)
    result = recommend(
        RecommendationRequest(quest_id=profile.quest_id),
        store=store,
        account_store=_synthetic_account(tmp_path),
        stats=_synthetic_stats(tmp_path),
    )
    plan_id = result.options[0].plan.plan_id
    # 推荐生成的 TeamPlan 必须落盘，否则执行预检会因找不到 plan_id 而报 400。
    assert store.get_plan(plan_id) is not None
    pre = preflight(
        ExecutionPreflightRequest(quest_id=profile.quest_id, plan_id=plan_id),
        store=store,
        confirmations=CraftEssenceConfirmationStore(tmp_path / "confirmations.json"),
    )
    assert pre.plan_id == plan_id
    assert any(check.check_id == "profile_verified" for check in pre.checks)


def test_mock_profile_is_flagged_in_recommendation(tmp_path: Path) -> None:
    store = CombatStore(tmp_path / "combat")
    result = recommend(
        RecommendationRequest(quest_id="free_ikeda_1_90pp_mock"),
        store=store,
        account_store=_synthetic_account(tmp_path),
        stats=_synthetic_stats(tmp_path),
    )
    assert result.profile_mock is True
    assert any("mock" in note for note in result.notes)


# --- Craft Essence confirmation ------------------------------------------


def test_confirmation_store_round_trip_and_missing_logic(tmp_path: Path) -> None:
    store = CraftEssenceConfirmationStore(tmp_path / "confirmations.json")
    assert store.get("plan-a") is None

    partial = store.save(
        CraftEssenceConfirmation(
            plan_id="plan-a",
            quest_id="quest-a",
            required_essences=["攻击力礼装", "充能礼装"],
            available_essences=["攻击力礼装"],
            confirmed=True,
        )
    )
    assert partial.missing_essences == ["充能礼装"]
    assert partial.is_satisfied is False
    assert partial.updated_at

    reloaded = store.get("plan-a")
    assert reloaded is not None
    assert reloaded.missing_essences == ["充能礼装"]

    full = store.save(
        CraftEssenceConfirmation(
            plan_id="plan-a",
            required_essences=["攻击力礼装", "充能礼装"],
            available_essences=["攻击力礼装", "充能礼装"],
            confirmed=True,
            confirmed_by="tester",
        )
    )
    assert full.is_satisfied is True
    assert store.delete("plan-a") is True
    assert store.get("plan-a") is None


def test_preflight_uses_per_plan_craft_essence_confirmation(tmp_path: Path) -> None:
    request = ExecutionPreflightRequest(
        quest_id="free_ikeda_1_90pp_mock",
        plan_id="mock-90pp-3t-plan",
    )
    confirmations = CraftEssenceConfirmationStore(tmp_path / "confirmations.json")

    # 没有任何确认记录时退回全局假设：仍然阻塞执行。
    baseline = preflight(request, confirmations=confirmations)
    check = next(item for item in baseline.checks if item.check_id == "craft_essence_confirmation")
    assert check.status == "blocked"
    assert baseline.can_execute is False

    # 已确认但仍缺必需礼装：继续阻塞，并列出缺项。
    confirmations.save(
        CraftEssenceConfirmation(
            plan_id="mock-90pp-3t-plan",
            required_essences=["攻击力礼装", "充能礼装"],
            available_essences=["攻击力礼装"],
            confirmed=True,
        )
    )
    partial = preflight(request, confirmations=confirmations)
    check = next(item for item in partial.checks if item.check_id == "craft_essence_confirmation")
    assert check.status == "blocked"
    assert "充能礼装" in check.detail

    # 全部确认后，礼装检查通过；执行仍被未验证的战斗档案阻塞。
    confirmations.save(
        CraftEssenceConfirmation(
            plan_id="mock-90pp-3t-plan",
            required_essences=["攻击力礼装", "充能礼装"],
            available_essences=["攻击力礼装", "充能礼装"],
            confirmed=True,
            confirmed_by="tester",
        )
    )
    satisfied = preflight(request, confirmations=confirmations)
    check = next(item for item in satisfied.checks if item.check_id == "craft_essence_confirmation")
    assert check.status == "ok"
    assert satisfied.can_execute is False
    assert any(item.check_id == "profile_verified" and item.status == "blocked" for item in satisfied.checks)


# --- API surface ----------------------------------------------------------


def test_recommend_api_returns_options(client, monkeypatch, tmp_path: Path) -> None:
    # 推荐会把 TeamPlan 落盘，必须隔离到临时目录，否则会污染真实 combat 数据目录。
    from game_assistant import combat_router

    store = CombatStore(tmp_path / "combat")
    monkeypatch.setattr(combat_router, "get_combat_store", lambda: store)
    response = client.post(
        "/api/game-assistant/fgo/3t/recommend",
        json={"quest_id": "free_ikeda_1_90pp_mock"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["quest_id"] == "free_ikeda_1_90pp_mock"
    assert payload["profile_mock"] is True
    # 计划写到临时目录，而不是真实目录。
    assert list((tmp_path / "combat").glob("*.plan.json"))


def test_recommend_api_rejects_unknown_quest(client) -> None:
    response = client.post(
        "/api/game-assistant/fgo/3t/recommend",
        json={"quest_id": "does-not-exist"},
    )
    assert response.status_code == 400


def test_find_quest_section_handles_a_daily_quest_table_anchor() -> None:
    """每日任务页（迦勒底之门）的难度是用 `<table id="…">` 标的（不是标题 span），
    而且表是嵌套的 ⇒ 切片要数嵌套深度、切到**这个**表的闭合为止，不能把下一个难度吃进来。"""
    html = (
        '<h2><span class="mw-headline" id="打开宝物库之门">打开宝物库之门</span></h2>'
        '<table class="wikitable logo" id="打开宝物库之门&#95;极级"><tbody><tr>'
        '<th>推荐Lv.60</th><th>AP40</th></tr><tr><th>BATTLE 1/3</th>'
        '<td><a href="/w/Caster" title="敌人一览">霸者之门</a>)HP23,027<br />Lv.31</td>'
        '<td><table><tbody><tr><td>嵌套的敌人小表</td></tr></tbody></table></td>'
        '</tr></tbody></table>'
        '<table class="wikitable logo" id="打开宝物库之门&#95;超级"><tbody>'
        '<tr><th>推荐Lv.70</th><th>AP40</th></tr><tr><th>BATTLE 1/3</th>'
        '<td><a href="/w/Caster" title="敌人一览">超级敌人</a>)HP99,999<br />Lv.70</td>'
        '</tr></tbody></table>'
    )

    section = find_quest_section(html, "打开宝物库之门&#95;极级")
    parsed = parse_quest_section(section)

    assert "超级敌人" not in section, "不能把下一个难度的表吃进来"
    assert parsed.ap_cost == 40 and parsed.recommended_level == "60"
    assert [wave.wave_index for wave in parsed.waves] == [1]
    assert parsed.waves[0].enemies[0].class_name == "Caster"
    other = parse_quest_section(find_quest_section(html, "打开宝物库之门&#95;超级"))
    assert other.waves[0].enemies[0].hp == 99999 and other.waves[0].enemies[0].level == 70


def test_combat_profile_import_api_saves_an_unverified_profile(client, monkeypatch, tmp_path: Path) -> None:
    """档案导入：贴 Mooncell 页面 HTML ⇒ 落一份 mock=false / verified=false 的档案（用真夹具）。"""
    from game_assistant import combat_router

    store = CombatStore(tmp_path / "combat-import")
    monkeypatch.setattr(combat_router, "get_combat_store", lambda: store)
    payload = {
        "quest_id": "imported-90pp",
        "quest_name": "神剑改 燃烧吧翡翠剑（90++）",
        "heading_id": QUEST_HEADING,
        "event_id": "fgo-cn-2026-gudaguda9",
        "html": SECTION_HTML.read_text(encoding="utf-8"),
    }

    response = client.post("/api/game-assistant/fgo/3t/combat-profiles/import", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    profile = body["profile"]
    assert profile["quest_id"] == "imported-90pp" and len(profile["waves"]) == 3
    assert profile["mock"] is False and profile["verified"] is False, "公开 wiki 数据不许自动标成已核对"
    assert store.get_profile("imported-90pp") is not None, "要真的落盘（推荐器才看得到）"
    assert any("verify" in note or "确认" in note for note in profile["notes"])

    # 已有同名档案：默认 409 拦住，显式 overwrite 才覆盖
    again = client.post("/api/game-assistant/fgo/3t/combat-profiles/import", json=payload)
    assert again.status_code == 409 and "overwrite" in again.json()["detail"]
    overwritten = client.post(
        "/api/game-assistant/fgo/3t/combat-profiles/import", json={**payload, "overwrite": True}
    )
    assert overwritten.status_code == 200


def test_combat_profile_import_api_rejects_bad_input(client, monkeypatch, tmp_path: Path) -> None:
    from game_assistant import combat_router

    monkeypatch.setattr(combat_router, "get_combat_store", lambda: CombatStore(tmp_path / "c"))
    base = {"quest_id": "q", "quest_name": "n", "heading_id": QUEST_HEADING}

    assert client.post("/api/game-assistant/fgo/3t/combat-profiles/import", json=base).status_code == 400, "没给 url/html"
    missing_heading = client.post(
        "/api/game-assistant/fgo/3t/combat-profiles/import",
        json={**base, "heading_id": "不存在的关卡", "html": "<html></html>"},
    )
    assert missing_heading.status_code == 400 and "没有找到关卡标题" in missing_heading.json()["detail"]


def test_craft_essence_confirmation_api_round_trip(client, monkeypatch, tmp_path: Path) -> None:
    from game_assistant import combat_router
    from game_assistant.craft_essence_confirmation import CraftEssenceConfirmationStore

    store = CraftEssenceConfirmationStore(tmp_path / "api-confirmations.json")
    monkeypatch.setattr(combat_router, "get_craft_essence_confirmation_store", lambda: store)

    missing = client.get("/api/game-assistant/fgo/3t/craft-essence-confirmation/plan-x")
    assert missing.status_code == 404

    response = client.put(
        "/api/game-assistant/fgo/3t/craft-essence-confirmation",
        json={
            "plan_id": "plan-x",
            "quest_id": "free_ikeda_1_90pp_mock",
            "required_essences": ["攻击力礼装"],
            "available_essences": ["攻击力礼装"],
            "confirmed": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["confirmed"] is True

    fetched = client.get("/api/game-assistant/fgo/3t/craft-essence-confirmation/plan-x")
    assert fetched.status_code == 200
    assert fetched.json()["required_essences"] == ["攻击力礼装"]
