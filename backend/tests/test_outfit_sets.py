"""Outfit Set validation, persistence, and API contract tests."""
from __future__ import annotations

import pytest

import outfit_sets


def _payload(**overrides):
    value = {
        "name": "测试套装",
        "description": "组合测试",
        "category": "测试",
        "items": [
            {"clothing_id": "organza_overlay_shirt"},
            {"clothing_id": "tulle_tiered_midi_skirt"},
            {"clothing_id": "shoe_mary_janes"},
        ],
    }
    value.update(overrides)
    return value


def test_builtin_outfit_catalog_is_valid() -> None:
    assert 10 <= len(outfit_sets.BUILTIN_OUTFITS) <= 20
    assert sum(len(item["items"]) for item in outfit_sets.BUILTIN_OUTFITS) == 41
    ids = [item["preset_id"] for item in outfit_sets.BUILTIN_OUTFITS]
    assert len(ids) == len(set(ids))
    for item in outfit_sets.BUILTIN_OUTFITS:
        normalized = outfit_sets.normalize_outfit_payload(item)
        assert normalized["items"]
        assert normalized["prompt"]
        assert len(normalized["content_hash"]) == 64


def test_outfit_normalizes_slots_order_colors_and_hash() -> None:
    payload = _payload(
        items=[
            {
                "clothing_id": "shoe_mary_janes",
                "colors": {"primary": "cherry red"},
                "order": 2,
            },
            {
                "clothing_id": "tulle_tiered_midi_skirt",
                "order": 1,
            },
            {
                "clothing_id": "organza_overlay_shirt",
                "order": 0,
            },
        ]
    )
    result = outfit_sets.normalize_outfit_payload(payload)
    assert [item["slot"] for item in result["items"]] == [
        "top",
        "bottom",
        "footwear",
    ]
    assert [item["order"] for item in result["items"]] == [0, 1, 2]
    assert "primary color cherry red" in result["prompt"]
    assert result["content_hash"]

    changed = outfit_sets.normalize_outfit_payload(
        {
            **payload,
            "items": [
                {"clothing_id": "organza_overlay_shirt", "order": 0},
                {"clothing_id": "tulle_tiered_midi_skirt", "order": 1},
                {
                    "clothing_id": "shoe_black_stiletto_heels",
                    "colors": {"primary": "cherry red"},
                    "order": 2,
                },
            ],
        }
    )
    assert changed["content_hash"] != result["content_hash"]


def test_outfit_rejects_slot_conflicts_and_cross_slot_overlap() -> None:
    with pytest.raises(outfit_sets.OutfitSetError, match="槽位冲突"):
        outfit_sets.normalize_outfit_payload(
            _payload(
                items=[
                    {"clothing_id": "organza_overlay_shirt"},
                    {
                        "clothing_id": "chiffon_draped_blouse",
                        "slot": "top",
                    },
                ]
            )
        )

    with pytest.raises(outfit_sets.OutfitSetError, match="槽位冲突"):
        outfit_sets.normalize_outfit_payload(
            _payload(
                items=[
                    {"clothing_id": "evening_gown"},
                    {"clothing_id": "organza_overlay_shirt"},
                ]
            )
        )


def test_outfit_rejects_unknown_ids_orders_and_restricted_items() -> None:
    with pytest.raises(outfit_sets.OutfitSetError, match="不存在的服装"):
        outfit_sets.normalize_outfit_payload(
            _payload(items=[{"clothing_id": "missing_clothing"}])
        )
    with pytest.raises(outfit_sets.OutfitSetError, match="顺序重复"):
        outfit_sets.normalize_outfit_payload(
            _payload(
                items=[
                    {"clothing_id": "organza_overlay_shirt", "order": 0},
                    {"clothing_id": "tulle_tiered_midi_skirt", "order": 0},
                ]
            )
        )
    with pytest.raises(outfit_sets.OutfitSetError, match="不能加入 R18"):
        outfit_sets.normalize_outfit_payload(
            _payload(items=[{"clothing_id": "latex_dress"}]),
            restriction_enabled=True,
        )


def test_outfit_api_lists_seeded_sets(client) -> None:
    response = client.get("/api/prompt-agent/outfit-presets")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(outfit_sets.BUILTIN_OUTFITS)
    assert body["restricted"] is False
    assert body["max_items"] == outfit_sets.MAX_ITEMS
    assert any(item["preset_id"] == "outfit_campus_cream" for item in body["items"])
    assert {"value": "full_body", "label": "全身装"} in body["slots"]


def test_outfit_api_create_update_duplicate_and_delete(client) -> None:
    compose = client.post("/api/prompt-agent/outfit-presets/compose", json=_payload())
    assert compose.status_code == 200, compose.text
    assert compose.json()["content_hash"]

    created_response = client.post(
        "/api/prompt-agent/outfit-presets",
        json=_payload(),
    )
    assert created_response.status_code == 200, created_response.text
    created = created_response.json()["item"]
    assert created["source"] == "user"
    assert created["version"] == 1
    assert len(created["items"]) == 3

    updated_response = client.put(
        f"/api/prompt-agent/outfit-presets/{created['preset_id']}",
        json=_payload(name="更新后的套装"),
    )
    assert updated_response.status_code == 200, updated_response.text
    updated = updated_response.json()["item"]
    assert updated["version"] == 2
    assert updated["name"] == "更新后的套装"

    duplicated_response = client.post(
        "/api/prompt-agent/outfit-presets/outfit_campus_cream/duplicate",
        json={"name": "校园副本"},
    )
    assert duplicated_response.status_code == 200, duplicated_response.text
    duplicated = duplicated_response.json()["item"]
    assert duplicated["source"] == "user"
    assert duplicated["name"] == "校园副本"

    builtin_update = client.put(
        "/api/prompt-agent/outfit-presets/outfit_campus_cream",
        json=_payload(),
    )
    assert builtin_update.status_code == 409

    deleted = client.delete(
        f"/api/prompt-agent/outfit-presets/{duplicated['preset_id']}"
    )
    assert deleted.status_code == 200
    assert client.get(
        f"/api/prompt-agent/outfit-presets/{duplicated['preset_id']}"
    ).status_code == 404


def test_outfit_versions_and_append_only_rollback(client) -> None:
    created = client.post(
        "/api/prompt-agent/outfit-presets",
        json=_payload(name="回滚测试 v1"),
    ).json()["item"]
    preset_id = created["preset_id"]

    updated = client.put(
        f"/api/prompt-agent/outfit-presets/{preset_id}",
        json=_payload(
            name="回滚测试 v2",
            items=[
                {"clothing_id": "chiffon_draped_blouse"},
                {"clothing_id": "shoe_black_stiletto_heels"},
            ],
        ),
    )
    assert updated.status_code == 200
    second = updated.json()["item"]
    assert second["version"] == 2
    assert second["content_hash"] != created["content_hash"]

    versions = client.get(
        f"/api/prompt-agent/outfit-presets/{preset_id}/versions"
    )
    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()["items"]] == [2, 1]

    restored = client.post(
        f"/api/prompt-agent/outfit-presets/{preset_id}/rollback",
        json={"version": 1},
    )
    assert restored.status_code == 200
    third = restored.json()["item"]
    assert third["version"] == 3
    assert third["name"] == created["name"]
    assert third["content_hash"] == created["content_hash"]

    versions_after = client.get(
        f"/api/prompt-agent/outfit-presets/{preset_id}/versions"
    ).json()["items"]
    assert [item["version"] for item in versions_after] == [3, 2, 1]
    assert versions_after[1]["name"] == "回滚测试 v2"


def test_referenced_user_outfit_cannot_be_deleted(client) -> None:
    outfit = client.post(
        "/api/prompt-agent/outfit-presets",
        json=_payload(name="角色默认套装"),
    ).json()["item"]
    appearance = client.post(
        "/api/prompt-agent/appearance-presets",
        json={
            "name": "套装角色",
            "work": "Test Work",
            "category": "角色",
            "appearance_tags": ["test character"],
            "clothing_tags": [],
            "expression_tags": [],
            "outfit_id": "",
            "outfit_set_id": outfit["preset_id"],
            "outfit_set_version": outfit["version"],
        },
    )
    assert appearance.status_code == 200, appearance.text

    blocked = client.delete(
        f"/api/prompt-agent/outfit-presets/{outfit['preset_id']}"
    )
    assert blocked.status_code == 409
    assert "角色外观预设引用" in blocked.json()["detail"]

    preset_id = appearance.json()["item"]["preset_id"]
    removed_appearance = client.delete(
        f"/api/prompt-agent/appearance-presets/{preset_id}"
    )
    assert removed_appearance.status_code == 200
    deleted = client.delete(
        f"/api/prompt-agent/outfit-presets/{outfit['preset_id']}"
    )
    assert deleted.status_code == 200
