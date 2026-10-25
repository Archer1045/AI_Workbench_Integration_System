"""Water modifier catalog and API tests."""
from __future__ import annotations

import water_presets
import prompt_document


def test_water_catalog_has_reusable_character_and_environment_modifiers():
    items = water_presets.WATER_PRESETS

    assert len(items) == 12
    assert len({item["id"] for item in items}) == len(items)
    assert {item["target"] for item in items} == set(water_presets.TARGETS)
    assert {item["category"] for item in items} <= set(water_presets.CATEGORIES)
    assert {item["water_level"] for item in items} <= set(water_presets.WATER_LEVELS)
    assert all(item["tags"] for item in items)
    assert all(item["rating"] == "普通" for item in items)


def test_water_api_filters_and_preset_catalog(client):
    full = client.get("/api/prompt-agent/water-presets")
    assert full.status_code == 200
    assert full.json()["total"] == 12

    character = client.get(
        "/api/prompt-agent/water-presets",
        params={"target": "角色", "category": "浸水状态", "keyword": "半身"},
    )
    assert character.status_code == 200
    assert [item["id"] for item in character.json()["items"]] == [
        "water_half_submerged"
    ]

    environment = client.get(
        "/api/prompt-agent/water-presets",
        params={"target": "环境", "water_level": "环境"},
    )
    assert environment.status_code == 200
    ids = {item["id"] for item in environment.json()["items"]}
    assert {
        "water_surface_ripples",
        "water_splash",
        "water_steam",
        "water_misty_reflection",
    } <= ids

    catalog = client.get("/api/prompt-agent/preset-catalog").json()
    assert len(catalog["water"]) == 12


def test_prompt_document_resolves_water_refs_in_scene_and_character_state():
    resolved = prompt_document.resolve_document(
        {
            "mode": "structured",
            "global": {
                "scene": {
                    "tags": [],
                    "preset_refs": [
                        {"preset_id": "water_surface_ripples", "version": 1}
                    ],
                }
            },
            "characters": [
                {
                    "id": "hero",
                    "role_id": "girlA",
                    "display_name": "Hero",
                    "gender": "女",
                    "state": {
                        "tags": [],
                        "preset_refs": [
                            {"preset_id": "water_half_submerged", "version": 1}
                        ],
                    },
                }
            ],
        }
    )

    assert resolved["blocked"] is False
    assert "water surface ripples" in resolved["prompt"]
    assert "half-submerged body" in resolved["prompt"]
    assert {"water_surface_ripples", "water_half_submerged"} <= set(
        resolved["used_ids"]
    )
