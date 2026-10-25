"""Action Composition catalog and compiler contract tests."""
from __future__ import annotations

import action_composer


def _base_recipe() -> dict:
    return {
        "direction_profile": "male_dominant",
        "dominant_role": "B",
        "receiving_role": "A",
        "roles": [
            {
                "slot": "A",
                "gender": "female",
                "base": "side_lying",
                "pelvis": "toward_partner",
                "near_leg": "extended",
                "far_leg": "raised",
                "arms": "support",
                "head": "look_back",
                "expression": "tense",
                "gaze": "look_partner",
            },
            {
                "slot": "B",
                "gender": "male",
                "base": "sitting",
                "pelvis": "toward_partner",
                "near_leg": "bent",
                "far_leg": "bent",
                "arms": "hold_partner_leg",
                "head": "lowered",
            },
        ],
        "interactions": [
            {
                "source_role": "B",
                "source_part": "hands",
                "action": "grab",
                "target_role": "A",
                "target_part": "breast",
            }
        ],
        "primary_action": "vaginal_insertion",
        "phase": "ongoing",
    }


def test_action_catalog_exposes_first_version_groups() -> None:
    catalog = action_composer.catalog()
    assert {"base_states", "actions", "target_parts", "direction_profiles"} <= set(catalog)
    assert any(item["id"] == "lick" for item in catalog["actions"])
    assert any(item["id"] == "breast" for item in catalog["target_parts"])


def test_compile_action_recipe_preserves_generic_action_and_target() -> None:
    result = action_composer.compile_recipe(_base_recipe())
    assert result["ok"] is True
    assert result["direction_profile"] == "male_dominant"
    assert "grabbing" in result["interaction_tags"]["action_tags"]
    assert "grabbing role A female breast" in result["interaction_tags"]["contact_tags"]
    assert "female breast" not in result["role_tags"]["A"]
    assert "tense expression" in result["expression_tags"]["A"]


def test_compile_action_recipe_blocks_female_target_parts_on_male() -> None:
    recipe = _base_recipe()
    recipe["interactions"][0]["target_role"] = "B"
    result = action_composer.compile_recipe(recipe)
    assert result["ok"] is False
    assert any("不适用于角色B" in error for error in result["errors"])


def test_compile_action_recipe_requires_same_sex_direction_profile() -> None:
    recipe = _base_recipe()
    recipe["roles"][1]["gender"] = "female"
    result = action_composer.compile_recipe(recipe)
    assert result["ok"] is False
    assert any("女女组合" in error for error in result["errors"])


def test_action_composer_api_contract(client) -> None:
    catalog = client.get("/api/prompt-agent/action-composer")
    assert catalog.status_code == 200
    assert "actions" in catalog.json()

    compiled = client.post(
        "/api/prompt-agent/compile-action-recipe",
        json=_base_recipe(),
    )
    assert compiled.status_code == 200
    assert compiled.json()["ok"] is True
    assert "expression_tags" in compiled.json()
