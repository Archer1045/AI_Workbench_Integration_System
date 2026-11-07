"""Focused tests for the guide-only FGO Game Assistant slice."""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from game_assistant.domain import GuideGenerationRequest
from game_assistant import schedule
from game_assistant.service import GameAssistantService
from game_assistant.store import GameAssistantStore


def fixed_now() -> datetime:
    return datetime(2026, 9, 25, 6, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.fixture()
def service(tmp_path, monkeypatch) -> GameAssistantService:
    import llm
    import game_assistant.service as service_module

    class FakeProviderSettings:
        def guide_statuses(self):
            return []

        def runtime_config(self, provider: str) -> dict:
            return {
                "available": True,
                "base_url": "http://127.0.0.1:11434",
                "model": "qwen3:8b" if provider == "local" else "test-model",
                "api_key": "test-key",
            }

    monkeypatch.setattr(llm, "is_available", lambda: False)
    monkeypatch.setattr(service_module, "get_provider_settings_service", lambda: FakeProviderSettings())
    return GameAssistantService(
        store=GameAssistantStore(tmp_path / "game_assistant.db"),
        clock=fixed_now,
    )


def test_fixture_tracks_first_day_gate(service: GameAssistantService) -> None:
    bootstrap = service.bootstrap()
    event = bootstrap["event_view"]["event"]
    current = bootstrap["event_view"]["current_phase"]
    upcoming = bootstrap["event_view"]["next_phase"]

    assert event["event_id"] == "fgo-cn-2026-gudaguda9"
    assert event["revision"] == 2
    assert current["phase_id"] == "day0"
    assert upcoming["phase_id"] == "day1"
    assert upcoming["opens_at"].startswith("2026-09-25T17:00")
    assert any(item["quest_id"] == "free_ikeda_1" for item in bootstrap["event_view"]["upcoming_quests"])


def test_template_guide_and_plan_are_revisioned(service: GameAssistantService) -> None:
    result = service.generate_and_save(GuideGenerationRequest(provider="template"))

    assert result.provider_requested == "template"
    assert result.provider_used == "template"
    assert result.prompt_version == "fgo-guide-v1"
    assert len(result.guide.sections) >= 5
    assert result.guide.sections[0].heading == "活动机制"
    assert "90++" in result.markdown
    assert any(step.phase_id == "day1" for step in result.plan.steps)
    assert any(step.step_id == "final-90pp" for step in result.plan.steps)
    assert service.get_generation(result.generation_id) is not None


def test_local_provider_accepts_structured_json(
    service: GameAssistantService,
    monkeypatch,
) -> None:
    import game_assistant.service as service_module

    model_output = json.dumps(
        {
            "title": "本地模型攻略",
            "summary": "本地模型已按 JSON 结构返回。",
            "current_phase": "day0",
            "sections": [
                {
                    "heading": heading,
                    "summary": "结构化章节",
                    "bullets": ["仅使用事实包内容。"],
                    "citation_ids": ["S1"],
                }
                for heading in ["活动机制", "当前阶段", "当前可刷关卡", "后续解锁", "商店优先级"]
            ],
            "warnings": [],
            "citation_ids": ["S1"],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(service_module, "local_json_chat", lambda *args, **kwargs: model_output)

    result = service.generate(GuideGenerationRequest(provider="local"))

    assert result.provider_requested == "local"
    assert result.provider_used == "local"
    assert result.guide.sections[0].heading == "活动机制"


def test_model_failure_falls_back_to_template(service: GameAssistantService, monkeypatch) -> None:
    import config
    import game_assistant.service as service_module

    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(
        service_module,
        "deepseek_json_chat",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    result = service.generate(GuideGenerationRequest(provider="deepseek"))

    assert result.provider_requested == "deepseek"
    assert result.provider_used == "template"
    assert result.fallback_reason
    assert any("回退" in warning for warning in result.warnings)


def test_game_assistant_api_uses_service_singleton(client, tmp_path, monkeypatch) -> None:
    import game_assistant.service as service_module
    import llm

    monkeypatch.setattr(llm, "is_available", lambda: False)
    singleton = GameAssistantService(
        store=GameAssistantStore(tmp_path / "api_game_assistant.db"),
        clock=fixed_now,
    )
    monkeypatch.setattr(service_module, "_SERVICE", singleton)

    bootstrap = client.get("/api/game-assistant/fgo/bootstrap")
    assert bootstrap.status_code == 200
    assert bootstrap.json()["boundaries"]["account_connected"] is True

    generated = client.post(
        "/api/game-assistant/fgo/guides/generate",
        json={"provider": "template", "goal": "只生成当前阶段攻略"},
    )
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["event_id"] == "fgo-cn-2026-gudaguda9"
    assert payload["guide"]["sections"]
    assert payload["plan"]["steps"]

    fetched = client.get(f"/api/game-assistant/fgo/guides/{payload['generation_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["generation_id"] == payload["generation_id"]


def test_bootstrap_uses_scheduled_current_main_event(tmp_path) -> None:
    now = datetime(2026, 10, 23, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    service = GameAssistantService(
        store=GameAssistantStore(tmp_path / "game_assistant.db"),
        clock=lambda: now,
        schedule_loader=lambda: [
            schedule.UpcomingEvent(
                event_id="official-18491",
                title="终结·万圣节2026~于南瓜星闪耀的歌姬~",
                event_kind="main",
                starts_at=datetime(2026, 10, 22, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                ends_at=datetime(2026, 11, 12, 13, 59, tzinfo=ZoneInfo("Asia/Shanghai")),
                status=schedule.STATUS_CONFIRMED,
            )
        ],
    )

    bootstrap = service.bootstrap()

    assert bootstrap["event_data_status"] == "ready"
    assert bootstrap["event_view"]["data_status"] == "ready"
    assert bootstrap["event_view"]["event"]["event_id"] == "official-18491"
    assert bootstrap["event_view"]["current_phase"]["phase_id"] == "halloween_2026_phase_1"
    assert bootstrap["event_view"]["next_phase"]["phase_id"] == "halloween_2026_phase_2"


def test_bootstrap_reports_missing_current_event_facts(tmp_path) -> None:
    now = datetime(2026, 10, 23, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    service = GameAssistantService(
        store=GameAssistantStore(tmp_path / "game_assistant.db"),
        clock=lambda: now,
        schedule_loader=lambda: [
            schedule.UpcomingEvent(
                event_id="official-missing",
                title="尚未导入资料的本期活动",
                event_kind="main",
                starts_at=datetime(2026, 10, 22, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
                ends_at=datetime(2026, 11, 12, 13, 59, tzinfo=ZoneInfo("Asia/Shanghai")),
                status=schedule.STATUS_CONFIRMED,
            )
        ],
    )

    bootstrap = service.bootstrap()

    assert bootstrap["event_data_status"] == "missing_bundle"
    assert bootstrap["event_view"]["data_status"] == "missing_bundle"
    assert bootstrap["event_view"]["event"]["event_id"] == "official-missing"
    assert bootstrap["event_view"]["current_phase"] is None
    assert bootstrap["latest_generation"] is None


def test_runtime_guard_corrects_model_phase(service: GameAssistantService, monkeypatch) -> None:
    import game_assistant.service as service_module

    model_output = json.dumps(
        {
            "title": "模型攻略",
            "summary": "模型错误地把下一阶段当成当前阶段。",
            "current_phase": "第三话至第四话 / NEW新选组关卡1",
            "sections": [
                {
                    "heading": heading,
                    "summary": "测试",
                    "bullets": ["测试"],
                    "citation_ids": ["S1"],
                }
                for heading in ["活动机制", "当前阶段", "当前可刷关卡", "后续解锁", "商店优先级"]
            ],
            "warnings": [],
            "citation_ids": ["S1"],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(service_module, "local_json_chat", lambda *args, **kwargs: model_output)

    result = service.generate(GuideGenerationRequest(provider="local"))

    assert result.guide.current_phase == "序幕至第二话 / 首日自由本"
    assert any("规则引擎不一致" in warning for warning in result.warnings)
def test_90pp_team_request_uses_specialized_guide_and_plan(service: GameAssistantService) -> None:
    goal = "请帮我生成本次活动的90++副本的推荐组队"
    result = service.generate(GuideGenerationRequest(provider="template", goal=goal))

    assert "90++" in result.guide.title
    assert result.guide.current_phase.startswith("神剑改 燃起翡翠剑")
    assert any(section.heading == "敌方结构" for section in result.guide.sections)
    assert any("984,960" in bullet for section in result.guide.sections for bullet in section.bullets)
    assert any(step.step_id == "team-unlock" for step in result.plan.steps)
    assert result.plan.objective == goal
def test_account_snapshot_crud(client, tmp_path, monkeypatch) -> None:
    import game_assistant.account_router as account_router
    from game_assistant.account_store import AccountSnapshotStore

    store = AccountSnapshotStore(tmp_path / "private_account.db")
    monkeypatch.setattr(account_router, "_STORE", store)

    created = client.post(
        "/api/game-assistant/fgo/account/servants",
        json={
            "name": "河上彦斋",
            "class_name": "Assassin",
            "rarity": 5,
            "level": 100,
            "max_level": 100,
            "np_level": 2,
            "skill_1": 10,
            "skill_2": 10,
            "skill_3": 10,
            "append_2": 10,
            "source": "manual",
            "confidence": "confirmed",
            "notes": "测试记录",
        },
    )
    assert created.status_code == 200
    servant_id = created.json()["record_id"]

    updated = client.put(
        f"/api/game-assistant/fgo/account/servants/{servant_id}",
        json={
            "name": "河上彦斋",
            "class_name": "Assassin",
            "rarity": 5,
            "level": 100,
            "max_level": 100,
            "np_level": 3,
            "skill_1": 10,
            "skill_2": 10,
            "skill_3": 10,
            "append_2": 10,
            "source": "manual",
            "confidence": "confirmed",
            "notes": "已更新宝具等级",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["np_level"] == 3

    material = client.post(
        "/api/game-assistant/fgo/account/materials",
        json={
            "name": "鬼炎鬼灯",
            "category": "技能素材",
            "quantity": 42,
            "reserve_quantity": 10,
            "source": "manual",
            "confidence": "confirmed",
            "notes": "",
        },
    )
    assert material.status_code == 200
    material_id = material.json()["record_id"]

    summary = client.get("/api/game-assistant/fgo/account/summary")
    assert summary.status_code == 200
    assert summary.json()["servants"] == 1
    assert summary.json()["materials"] == 1

    assert client.delete(f"/api/game-assistant/fgo/account/servants/{servant_id}").status_code == 200
    assert client.delete(f"/api/game-assistant/fgo/account/materials/{material_id}").status_code == 200
    assert client.get("/api/game-assistant/fgo/account/summary").json() == {
        "servants": 0,
        "materials": 0,
        "confirmed_servants": 0,
        "candidate_servants": 0,
    }
