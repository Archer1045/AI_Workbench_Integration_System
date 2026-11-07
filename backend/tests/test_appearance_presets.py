"""Appearance preset CRUD, application, import, and reference safety tests."""
from __future__ import annotations

import json

import database


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


def test_identity_tags_are_separate_from_visual_appearance(client):
    created = client.post(
        "/api/prompt-agent/appearance-presets",
        json={
            "preset_id": "test_identity_separation",
            "name": "Identity Test",
            "work": "Test Work",
            "category": "角色",
            "identity_tags": ["identity_test_(test_work)"],
            "appearance_tags": ["identity_test_(test_work)", "silver hair"],
            "clothing_tags": [],
            "expression_tags": [],
        },
    )
    assert created.status_code == 200
    item = created.json()["item"]
    assert item["identity_tags"] == ["identity_test_(test_work)"]
    assert item["appearance_tags"] == ["silver hair"]

    applied = client.post(
        f"/api/prompt-agent/appearance-presets/{item['preset_id']}/apply",
        json={},
    )
    assert applied.status_code == 200
    payload = applied.json()
    assert payload["identity"] == ["identity_test_(test_work)"]
    assert payload["visual_appearance"] == ["silver hair"]
    assert payload["appearance"] == ["identity_test_(test_work)", "silver hair"]

    edited = client.put(
        f"/api/prompt-agent/appearance-presets/{item['preset_id']}",
        json={"identity_tags": ["identity_test_v2_(test_work)"]},
    )
    assert edited.status_code == 200
    assert edited.json()["item"]["identity_tags"] == [
        "identity_test_v2_(test_work)"
    ]
    client.delete(f"/api/prompt-agent/appearance-presets/{item['preset_id']}")


def test_migration_backfills_identity_tags_without_guessing_visual_tags(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "identity_migration.db")
    with database.get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE character_appearance_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                preset_id TEXT NOT NULL,
                name TEXT NOT NULL,
                work TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '角色',
                appearance_tags TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        rows = [
            (
                "known",
                "known_character_(work)",
                '["known_character_(work)", "work", "long hair"]',
            ),
            (
                "original",
                "1girl",
                '["1girl", "long hair", "blue eyes"]',
            ),
        ]
        for preset_id, first, tags in rows:
            conn.execute(
                """
                INSERT INTO character_appearance_presets (
                    preset_id, name, work, appearance_tags
                ) VALUES (?, ?, 'Work', ?)
                """,
                (preset_id, preset_id, tags),
            )

        database._migration_036_character_identity_tags(conn)
        known = conn.execute(
            """
            SELECT identity_tags, appearance_tags
            FROM character_appearance_presets
            WHERE preset_id = 'known'
            """
        ).fetchone()
        original = conn.execute(
            """
            SELECT identity_tags, appearance_tags
            FROM character_appearance_presets
            WHERE preset_id = 'original'
            """
        ).fetchone()

    assert json.loads(known["identity_tags"]) == ["known_character_(work)"]
    assert json.loads(known["appearance_tags"]) == ["work", "long hair"]
    assert json.loads(original["identity_tags"]) == []
    assert json.loads(original["appearance_tags"]) == [
        "1girl",
        "long hair",
        "blue eyes",
    ]


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


def test_appearance_preset_pins_and_applies_default_outfit_set(client):
    outfit = client.post(
        "/api/prompt-agent/outfit-presets",
        json={
            "name": "角色套装 v1",
            "items": [
                {"clothing_id": "organza_overlay_shirt"},
                {"clothing_id": "tulle_tiered_midi_skirt"},
                {"clothing_id": "shoe_mary_janes"},
            ],
        },
    )
    assert outfit.status_code == 200, outfit.text
    outfit_v1 = outfit.json()["item"]

    created = client.post(
        "/api/prompt-agent/appearance-presets",
        json={
            "name": "带默认套装的角色",
            "work": "Test Work",
            "category": "角色",
            "appearance_tags": ["silver hair"],
            "clothing_tags": ["atomic fallback"],
            "expression_tags": [],
            "outfit_id": "outfit_test_atomic_fallback",
            "outfit_set_id": outfit_v1["preset_id"],
            "outfit_set_version": 1,
        },
    )
    assert created.status_code == 200, created.text
    item = created.json()["item"]
    assert item["outfit_id"] == "outfit_test_atomic_fallback"
    assert item["outfit_set_id"] == outfit_v1["preset_id"]
    assert item["outfit_set_version"] == 1
    assert item["outfit_set_name"] == "角色套装 v1"
    assert item["outfit_set_items"]

    updated_outfit = client.put(
        f"/api/prompt-agent/outfit-presets/{outfit_v1['preset_id']}",
        json={
            "name": "角色套装 v2",
            "items": [
                {"clothing_id": "chiffon_draped_blouse"},
                {"clothing_id": "shoe_black_stiletto_heels"},
            ],
        },
    )
    assert updated_outfit.status_code == 200

    applied_v1 = client.post(
        f"/api/prompt-agent/appearance-presets/{item['preset_id']}/apply",
        json={"version": item["version"]},
    )
    assert applied_v1.status_code == 200
    default_set = applied_v1.json()["default_outfit_set"]
    assert default_set["version"] == 1
    assert default_set["name"] == "角色套装 v1"
    assert default_set["content_hash"] == outfit_v1["content_hash"]

    pinned_v2 = client.put(
        f"/api/prompt-agent/appearance-presets/{item['preset_id']}",
        json={"outfit_set_version": 2},
    )
    assert pinned_v2.status_code == 200
    assert pinned_v2.json()["item"]["outfit_set_version"] == 2
    applied_v2 = client.post(
        f"/api/prompt-agent/appearance-presets/{item['preset_id']}/apply",
        json={"version": pinned_v2.json()["item"]["version"]},
    )
    assert applied_v2.status_code == 200
    assert applied_v2.json()["default_outfit_set"]["version"] == 2


def test_appearance_preset_rejects_missing_outfit_set_version(client):
    response = client.post(
        "/api/prompt-agent/appearance-presets",
        json={
            "name": "坏套装关联",
            "category": "角色",
            "appearance_tags": ["silver hair"],
            "outfit_set_id": "outfit_campus_cream",
            "outfit_set_version": 999,
        },
    )
    assert response.status_code == 400
    assert "套装或版本不存在" in response.json()["detail"]
