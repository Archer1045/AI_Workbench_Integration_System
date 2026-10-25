from __future__ import annotations

import json
from datetime import datetime

import requests

import pytest

from game_assistant.provider_settings import (
    ProviderSettingsService,
    ProviderSettingsUpdate,
    ProviderSettingsError,
)
from game_assistant.secret_store import ProviderSecretStore
from game_assistant.source_domain import (
    EventRevisionPatch,
    RevisionDiff,
    SourceExtractionResult,
    SourceIngestRequest,
)
import game_assistant.source_service as source_module
from game_assistant.source_service import SourceError, SourceManager, _validate_public_url
from game_assistant.source_store import SourceStore
from game_assistant.store import GameAssistantStore


def provider_service(tmp_path) -> ProviderSettingsService:
    return ProviderSettingsService(
        tmp_path / "providers.json",
        ProviderSecretStore(tmp_path / "secrets.json"),
    )


def source_manager(tmp_path, providers: ProviderSettingsService) -> SourceManager:
    game_store = GameAssistantStore(tmp_path / "game.db")
    game_store.initialize(seed=True)
    return SourceManager(
        source_store=SourceStore(tmp_path / "sources"),
        game_store=game_store,
        provider_settings=providers,
    )


def test_provider_secret_is_not_returned_or_stored_plaintext(tmp_path) -> None:
    service = provider_service(tmp_path)
    updated = service.update(
        "deepseek",
        ProviderSettingsUpdate(
            base_url="https://api.deepseek.com/v1",
            model="deepseek-chat",
            api_key="sk-test-secret-value",
        ),
    )
    assert updated.api_key_configured is True
    assert "api_key" not in updated.model_dump()
    secret_text = (tmp_path / "secrets.json").read_text(encoding="utf-8")
    assert "sk-test-secret-value" not in secret_text
    assert service.runtime_config("deepseek")["api_key"] == "sk-test-secret-value"


def test_provider_connection_test_is_mocked(tmp_path, monkeypatch) -> None:
    service = provider_service(tmp_path)
    service.update(
        "openai_compatible",
        ProviderSettingsUpdate(
            base_url="https://example.test/v1",
            model="demo-model",
            api_key="demo-key",
        ),
    )

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"id": "demo-model"}]}

    monkeypatch.setattr("game_assistant.provider_settings.requests.get", lambda *args, **kwargs: Response())
    result = service.test("openai_compatible")
    assert result.ok is True
    assert "连接成功" in result.message


def test_source_url_rejects_loopback() -> None:
    with pytest.raises(SourceError):
        _validate_public_url("http://127.0.0.1:8000/private")


def test_manual_source_extract_and_publish(tmp_path, monkeypatch) -> None:
    providers = provider_service(tmp_path)
    providers.update(
        "openai_compatible",
        ProviderSettingsUpdate(
            base_url="https://example.test/v1",
            model="demo-model",
            api_key="",
        ),
    )
    manager = source_manager(tmp_path, providers)
    record = manager.ingest(
        SourceIngestRequest(
            text="活动新增一条说明：第三面有一个特殊目标。",
            source_type="guide",
            title="测试攻略",
        )
    )
    assert record.fetched_via == "manual"
    assert record.base_revision == 2

    monkeypatch.setattr(
        "game_assistant.source_service.openai_json_chat",
        lambda *args, **kwargs: json.dumps(
            {
                "event": {},
                "mechanics": [],
                "bonus_servants": [],
                "phases": [],
                "quests": [],
                "missions": [],
                "shop_items": [],
                "notes": ["第三面有一个特殊目标"],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
    )
    extraction = manager.extract(record.source_id, "openai_compatible")
    assert extraction.diff.summary
    assert extraction.patch.notes

    bundle = manager.publish(record.source_id, confirm=True)
    assert bundle.revision == 3
    assert any(item.source_id.startswith("WEB-") for item in bundle.sources)


def test_source_publish_can_create_a_new_event_bundle(tmp_path, monkeypatch) -> None:
    providers = provider_service(tmp_path)
    providers.update(
        "openai_compatible",
        ProviderSettingsUpdate(
            base_url="https://example.test/v1",
            model="demo-model",
            api_key="",
        ),
    )
    manager = source_manager(tmp_path, providers)
    record = manager.ingest(
        SourceIngestRequest(
            text="新活动从 2026-10-22 19:00 开始，到 2026-11-12 13:59 结束。",
            source_type="official",
            title="新活动官方公告",
            event_id="official-new",
        )
    )
    assert record.base_revision is None

    monkeypatch.setattr(
        "game_assistant.source_service.openai_json_chat",
        lambda *args, **kwargs: json.dumps(
            {
                "event": {
                    "title": "新活动",
                    "starts_at": "2026-10-22T19:00:00+08:00",
                    "ends_at": "2026-11-12T13:59:00+08:00",
                },
                "mechanics": [],
                "bonus_servants": [],
                "phases": [],
                "quests": [],
                "missions": [],
                "shop_items": [],
                "notes": [],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
    )
    manager.extract(record.source_id, "openai_compatible")
    bundle = manager.publish(record.source_id, confirm=True)

    assert bundle.event_id == "official-new"
    assert bundle.revision == 1
    assert bundle.title == "新活动"
    assert any(item.source_id.startswith("WEB-") for item in bundle.sources)


def test_source_extraction_context_is_compact(tmp_path, monkeypatch) -> None:
    providers = provider_service(tmp_path)
    providers.update(
        "openai_compatible",
        ProviderSettingsUpdate(
            base_url="https://example.test/v1",
            model="demo-model",
            api_key="",
        ),
    )
    manager = source_manager(tmp_path, providers)
    record = manager.ingest(
        SourceIngestRequest(
            text="活动机制说明。",
            source_type="guide",
            title="紧凑上下文测试",
            event_id="fgo-cn-2026-gudaguda9",
            revision=2,
        )
    )
    captured: dict = {}

    def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        return json.dumps(
            {
                "event": {},
                "mechanics": [],
                "bonus_servants": [],
                "phases": [],
                "quests": [],
                "missions": [],
                "shop_items": [],
                "notes": ["无新增结构化事实"],
                "warnings": [],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("game_assistant.source_service.openai_json_chat", fake_chat)
    manager.extract(record.source_id, "openai_compatible")
    prompt = "\n".join(item["content"] for item in captured["messages"])
    assert "existing_phase_ids" in prompt
    assert "existing_quest_ids" in prompt
    assert "enemy_waves" not in prompt
    assert len(prompt) < 20_000


def test_publish_requires_confirmation(tmp_path) -> None:
    providers = provider_service(tmp_path)
    manager = source_manager(tmp_path, providers)
    record = manager.ingest(SourceIngestRequest(text="正文", source_type="user_note", title="备注"))
    record.extraction = SourceExtractionResult(
        source_id=record.source_id,
        provider_used="openai_compatible",
        model="test",
        patch=EventRevisionPatch(notes=["备注"]),
        diff=RevisionDiff(summary="测试"),
        created_at=datetime.now().astimezone(),
    )
    manager.sources.save(record)
    with pytest.raises(SourceError):
        manager.publish(record.source_id, confirm=False)


def test_source_http_error_is_reported(tmp_path, monkeypatch) -> None:
    manager = source_manager(tmp_path, provider_service(tmp_path))
    monkeypatch.setattr(source_module, "_validate_public_url", lambda url: None)

    class Response:
        status_code = 403
        reason = "Forbidden"
        headers: dict = {}
        encoding = "utf-8"

        def close(self) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def raise_for_status(self) -> None:
            raise requests.HTTPError("403 Client Error")

    monkeypatch.setattr(source_module.requests, "get", lambda *args, **kwargs: Response())
    with pytest.raises(SourceError, match="HTTP 403"):
        manager._fetch_url("https://example.test/guide")


def test_image_only_source_keeps_image_urls(tmp_path, monkeypatch) -> None:
    manager = source_manager(tmp_path, provider_service(tmp_path))
    monkeypatch.setattr(source_module, "_validate_public_url", lambda url: None)
    html = "<html><head><title>图片攻略</title></head><body><img src=\"/a.jpg\"><img data-src=\"/b.png\"></body></html>".encode("utf-8")

    class Response:
        status_code = 200
        reason = "OK"
        headers = {"Content-Type": "text/html; charset=utf-8"}
        encoding = "utf-8"

        def close(self) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size):
            yield html

    monkeypatch.setattr(source_module.requests, "get", lambda *args, **kwargs: Response())
    result = manager._fetch_url("https://example.test/guide")
    assert result[3] == ""
    assert result[4] == ["https://example.test/a.jpg", "https://example.test/b.png"]
