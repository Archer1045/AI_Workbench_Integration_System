"""Appearance preset CRUD, application, import, and reference safety tests."""
from __future__ import annotations


def _create_preset(client, preset_id: str = "test_appearance_preset"):
    response = client.post(
        "/api/prompt-agent/appearance-presets",
        json={
            "preset_id": preset_id,
            "name": "Test Appearance",
            "work": "Test Work",
            "category": "脸部",
            "appearance_tags": ["silver hair", "red eyes"],
            "clothing_tags": ["black coat"],
            "expression_tags": ["focused gaze"],
            "note": "manual preset",
        },
    )
    assert response.status_code == 200
    return response.json()["item"]


def test_appearance_preset_crud_and_versioning(client):
    created = _create_preset(client)
    assert created["version"] == 1
    assert created["source"] == "user"

    updated = client.put(
        f"/api/prompt-agent/appearance-presets/{created['preset_id']}",
        json={
            "name": "Updated Appearance",
            "appearance_tags": ["white hair"],
            "enabled": False,
        },
    )
    assert updated.status_code == 200
    edited = updated.json()["item"]
    assert edited["version"] == 2
    assert edited["name"] == "Updated Appearance"
    assert edited["appearance_tags"] == ["white hair"]
    assert edited["clothing_tags"] == ["black coat"]
    assert edited["enabled"] is False

    listed = client.get("/api/prompt-agent/appearance-presets", params={"keyword": "Updated"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["version"] == 2

    detail = client.get(f"/api/prompt-agent/appearance-presets/{created['preset_id']}")
    assert detail.status_code == 200
    assert detail.json()["item"]["version"] == 2

    old_version = client.get(
        f"/api/prompt-agent/appearance-presets/{created['preset_id']}",
        params={"version": 1},
    )
    assert old_version.status_code == 200
    assert old_version.json()["item"]["name"] == "Test Appearance"


def test_appearance_preset_work_filter_and_works(client):
    created = _create_preset(client, "test_appearance_work_filter")
    try:
        listed = client.get(
            "/api/prompt-agent/appearance-presets",
            params={"work": "Test Work"},
        )
        assert listed.status_code == 200
        body = listed.json()
        assert body["total"] >= 1
        assert all(item["work"] == "Test Work" for item in body["items"])

        catalog = client.get("/api/prompt-agent/appearance-presets")
        assert catalog.status_code == 200
        assert "Test Work" in catalog.json()["works"]

        missing = client.get(
            "/api/prompt-agent/appearance-presets",
            params={"work": "Missing Work"},
        )
        assert missing.status_code == 200
        assert missing.json()["total"] == 0
    finally:
        client.delete(f"/api/prompt-agent/appearance-presets/{created['preset_id']}")


def test_appearance_preset_apply_duplicate_and_delete(client):
    created = _create_preset(client)

    applied = client.post(
        f"/api/prompt-agent/appearance-presets/{created['preset_id']}/apply",
        json={"version": created["version"]},
    )
    assert applied.status_code == 200
    body = applied.json()
    assert body["preset_ref"] == {
        "preset_id": created["preset_id"],
        "version": created["version"],
    }
    assert body["appearance"] == ["silver hair", "red eyes"]
    assert body["clothing"] == ["black coat"]
    assert body["expression"] == ["focused gaze"]

    duplicated = client.post(
        f"/api/prompt-agent/appearance-presets/{created['preset_id']}/duplicate",
        json={"name": "Copy"},
    )
    assert duplicated.status_code == 200
    copy = duplicated.json()["item"]
    assert copy["preset_id"] != created["preset_id"]
    assert copy["name"] == "Copy"
    assert copy["appearance_tags"] == created["appearance_tags"]

    deleted_copy = client.delete(f"/api/prompt-agent/appearance-presets/{copy['preset_id']}")
    assert deleted_copy.status_code == 200
    deleted_original = client.delete(f"/api/prompt-agent/appearance-presets/{created['preset_id']}")
    assert deleted_original.status_code == 200


def test_builtin_preset_edits_as_copy_and_cannot_be_deleted(client):
    builtin_id = "builtin_soft_anime_girl"

    edited = client.put(
        f"/api/prompt-agent/appearance-presets/{builtin_id}",
        json={"name": "My Anime Look", "appearance_tags": ["custom face"]},
    )
    assert edited.status_code == 200
    body = edited.json()
    assert body["created_copy"] is True
    assert body["item"]["source"] == "user"
    assert body["item"]["name"] == "My Anime Look"

    deleted = client.delete(f"/api/prompt-agent/appearance-presets/{builtin_id}")
    assert deleted.status_code == 403


def test_preset_referenced_by_prompt_set_cannot_be_deleted(client):
    created = _create_preset(client, "test_referenced_appearance")
    document = {
        "mode": "structured",
        "characters": [
            {
                "id": "hero",
                "role_id": "girlA",
                "display_name": "Hero",
                "gender": "女",
                "appearance": {
                    "preset_refs": [
                        {"preset_id": created["preset_id"], "version": created["version"]}
                    ]
                },
            }
        ],
    }
    saved = client.post(
        "/api/prompt-sets",
        json={
            "name": "Referenced appearance",
            "type": "角色",
            "content": "hero",
            "translation": "英雄",
            "prompt_document": document,
        },
    )
    assert saved.status_code == 200

    deleted = client.delete(f"/api/prompt-agent/appearance-presets/{created['preset_id']}")
    assert deleted.status_code == 409
    assert "仍被 1 处引用" in deleted.json()["detail"]


def test_legacy_character_cache_can_be_imported_as_preset(client):
    saved = client.put(
        "/api/prompt-agent/character-appearance",
        json={
            "character_name": "Legacy Hero",
            "work": "Legacy Work",
            "appearance": ["long hair", "blue eyes"],
            "clothing": ["white dress"],
            "expression": ["smile"],
            "note": "legacy cache",
        },
    )
    assert saved.status_code == 200

    imported = client.post(
        "/api/prompt-agent/appearance-presets/import-character-cache",
        json={
            "character_name": "Legacy Hero",
            "work": "Legacy Work",
            "category": "自由备注",
        },
    )
    assert imported.status_code == 200
    item = imported.json()["item"]
    assert item["source"] == "legacy_cache"
    assert item["appearance_tags"] == ["long hair", "blue eyes"]
    assert item["clothing_tags"] == ["white dress"]
