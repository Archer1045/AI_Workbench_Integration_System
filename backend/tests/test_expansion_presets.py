"""Expansion preset data, API, and composition tests."""
from __future__ import annotations

import expansion_presets


def test_expansion_preset_data_is_complete() -> None:
    assert len(expansion_presets.EXPANSION_PRESETS) == 8
    ids = [item["id"] for item in expansion_presets.EXPANSION_PRESETS]
    assert len(ids) == len(set(ids))
    states = {item["state"] for item in expansion_presets.EXPANSION_PRESETS}
    assert states == set(expansion_presets.STATES)
    for item in expansion_presets.EXPANSION_PRESETS:
        assert item["category"] in expansion_presets.CATEGORIES
        assert item["rating"] == "R18"
        assert item["intensity"] in expansion_presets.INTENSITIES
        assert item["visual_only"] is True
        assert item["execution_allowed"] is False
        assert item["has_image"] is False
        assert item["image"] is None
        assert item["draw_prompt"]


def test_expansion_presets_api(client) -> None:
    response = client.get("/api/prompt-agent/expansion-presets")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 8
    assert body["items"]
    assert body["categories"]
    assert body["states"]
    assert all(item["rating"] == "R18" for item in body["items"])
    assert all(item["has_image"] is False for item in body["items"])


def test_expansion_presets_are_in_catalog_and_composition(client) -> None:
    catalog = client.get("/api/prompt-agent/preset-catalog").json()
    assert len(catalog["expansions"]) == 8
    composed = client.post(
        "/api/prompt-agent/compose-presets",
        json={
            "pose_id": "gentle_lap_rest_younger_male_consensual",
            "expansions": [
                {"id": "expansion_vaginal_liquid_fill", "scope": "all"}
            ],
        },
    )
    assert composed.status_code == 200
    assert "expansion_vaginal_liquid_fill" in composed.json()["used_ids"]
