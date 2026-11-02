"""Companion chat must use precise resources instead of global busy blocking."""
from __future__ import annotations

import database
import task_registry
import task_resources
from routers import companion


def test_companion_text_runs_alongside_draw(client, monkeypatch):
    persona_id = database.insert_companion_persona(
        {
            "name": "测试角色",
            "source": "测试作品",
            "relationship": "朋友",
            "gender": "女",
        }
    )
    session_id = database.create_companion_session(persona_id)
    monkeypatch.setattr(
        companion,
        "_settings",
        lambda: {
            "content_restriction": "0",
            "medical_disabled": "1",
            "dependency_reminder": "0",
            "minor_protection": "0",
            "online_search_enabled": "0",
            "model_provider": "local",
            "cloud_base_url": "",
            "cloud_api_key": "",
            "cloud_model": "",
        },
    )
    monkeypatch.setattr(companion, "_retrieve_memories", lambda *_args: [])
    monkeypatch.setattr(companion, "_detect_emotion", lambda *_args: "")
    monkeypatch.setattr(companion.llm, "is_available", lambda: True)
    monkeypatch.setattr(
        companion.llm,
        "stream_chat",
        lambda _messages: iter([("answer", "测试回复")]),
    )
    task_registry.register(
        "draw",
        "draw-companion-api-peer",
        resources=task_resources.for_kind("draw"),
    )
    try:
        response = client.post(
            "/api/companion/chat",
            json={
                "message": "你好",
                "session_id": session_id,
                "persona_id": persona_id,
            },
        )
        assert response.status_code == 200, response.text
        assert "测试回复" in response.text
        assert {
            item["type"] for item in task_registry.running_tasks()
        } == {"draw"}
    finally:
        task_registry.finish("draw", "draw-companion-api-peer", "done")
