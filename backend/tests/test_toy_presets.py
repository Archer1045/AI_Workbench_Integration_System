"""Toy preset catalog and API contract tests."""
from __future__ import annotations

import toy_presets


def test_toy_preset_data_is_complete() -> None:
    assert len(toy_presets.TOY_PRESETS) == 13
    ids = [item["id"] for item in toy_presets.TOY_PRESETS]
    assert len(ids) == len(set(ids))
    for item in toy_presets.TOY_PRESETS:
        assert item["category"] in toy_presets.CATEGORIES
        assert item["rating"] == "R18"
        assert item["intensity"] in toy_presets.INTENSITIES
        assert item["form_factor"] in toy_presets.FORM_FACTORS
        assert item["material_appearance"] in toy_presets.MATERIAL_APPEARANCES
        assert item["visual_only"] is True
        assert item["has_image"] is False
        assert item["image"] is None
        assert item["draw_prompt"]


def test_toy_presets_api(client) -> None:
    response = client.get("/api/prompt-agent/toy-presets")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 13
    assert body["items"]
    assert body["categories"]
    assert body["form_factors"]
    assert body["material_appearances"]
    assert all(item["rating"] == "R18" for item in body["items"])
    assert all(item["has_image"] is False for item in body["items"])


def test_toy_presets_are_in_catalog_and_composition(client) -> None:
    catalog = client.get("/api/prompt-agent/preset-catalog").json()
    assert len(catalog["toys"]) == 13
    composed = client.post(
        "/api/prompt-agent/compose-presets",
        json={
            "pose_id": "gentle_lap_rest_younger_male_consensual",
            "toys": [{"id": "toy_wand_vibrator", "scope": "all"}],
        },
    )
    assert composed.status_code == 200
    assert "toy_wand_vibrator" in composed.json()["used_ids"]
