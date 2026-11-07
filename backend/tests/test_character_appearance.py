"""Character appearance cache/LLM-draft API and new draw-limit tests."""
from __future__ import annotations

import app  # noqa: F401  (must resolve agent module before router imports)
from routers import draw as draw_module
from routers import prompt as prompt_module


def test_character_appearance_manual_save_and_cache(client):
    response = client.put(
        "/api/prompt-agent/character-appearance",
        json={
            "character_name": "Test Girl",
            "work": "Example Work",
            "appearance": ["long hair", "blue eyes"],
            "clothing": ["white dress"],
            "note": "manual",
        },
    )
    assert response.status_code == 200
    saved = response.json()
    assert saved["source"] == "manual"
    assert saved["corrected"] is True

    cached = client.get(
        "/api/prompt-agent/character-appearance",
        params={"character_name": "test girl", "work": "example work"},
    )
    assert cached.status_code == 200
    assert cached.json()["source"] == "cache"
    assert cached.json()["appearance"] == ["long hair", "blue eyes"]


def test_character_appearance_unknown_draft_returns_no_hardcoded_tags(client, monkeypatch):
    monkeypatch.setattr(prompt_module.prompt_agent, "is_available", lambda: True)

    def fake_generate(name, work=""):
        return {
            "character_name": name,
            "work": work,
            "known": False,
            "confidence": 0.05,
            "appearance": [],
            "clothing": [],
            "full_prompt": "",
            "source": "llm",
            "note": "unknown",
        }

    monkeypatch.setattr(prompt_module.prompt_agent, "generate_character_appearance", fake_generate)
    response = client.get(
        "/api/prompt-agent/character-appearance",
        params={"character_name": "Obscure Character", "work": "Unknown Work"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["appearance"] == []
    assert body["clothing"] == []
    assert body["full_prompt"] == ""
    assert body["confidence"] <= 0.1


def test_draw_batch_new_limits_return_friendly_400(client):
    assert draw_module.MAX_GROUP_COUNT == 20
    assert draw_module.MAX_TOTAL_COUNT == 100
    response = client.post(
        "/api/draw/batch",
        json={
            "model": "chosenIrisesMix_v20Anima.safetensors",
            "groups": [{"prompt": "1girl", "count": 21}],
        },
    )
    assert response.status_code == 400
    assert (
        f"每组张数必须在 {draw_module.GROUP_COUNT_MIN}-{draw_module.MAX_GROUP_COUNT} 张之间"
        in response.json()["detail"]
    )


def test_character_generate_requires_available_ollama(client, monkeypatch):
    monkeypatch.setattr(prompt_module.prompt_agent, "is_available", lambda: False)
    response = client.get(
        "/api/prompt-agent/character-appearance",
        params={"character_name": "Any", "work": ""},
    )
    assert response.status_code == 503
    assert "Ollama" in response.json()["detail"]
