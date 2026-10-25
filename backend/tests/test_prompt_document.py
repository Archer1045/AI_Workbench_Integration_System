"""Structured prompt document validation and resolution tests."""
from __future__ import annotations

import pytest

import database
import prompt_document


def _base_document() -> dict:
    return {
        "version": 1,
        "mode": "structured",
        "global": {
            "quality": {"tags": ["masterpiece", "best quality"]},
            "style": {"tags": ["anime style"]},
        },
        "characters": [
            {
                "id": "character-2",
                "role_id": "girlB",
                "display_name": "女B",
                "gender": "女",
                "order": 1,
                "appearance": {"tags": ["short hair"]},
                "clothing": {"tags": ["blue dress"]},
                "expression": {"tags": ["calm smile"]},
            },
            {
                "id": "character-1",
                "role_id": "girlA",
                "display_name": "女A",
                "gender": "女",
                "order": 0,
                "appearance": {"tags": ["long hair", "long hair"]},
                "clothing": {"tags": ["red dress"]},
                "expression": {"tags": ["gentle smile"]},
            },
        ],
        "interaction": {
            "action_tags": ["holding hands"],
            "contact_tags": ["close contact"],
            "relationship_tags": ["friendship"],
            "composition_constraints": ["two people"],
        },
        "custom": {"global_tags": ["outdoor"], "user_notes": "keep both faces visible"},
        "negative": {
            "quality": {"tags": ["bad anatomy"]},
            "anatomy": {"tags": ["extra fingers"]},
        },
        "raw_override": {
            "prompt": "legacy prompt",
            "negative_prompt": "legacy negative",
        },
    }


def test_normalize_document_orders_characters_and_normalizes_blocks():
    normalized = prompt_document.normalize_document(_base_document())

    assert normalized["version"] == 1
    assert normalized["mode"] == "structured"
    assert [item["role_id"] for item in normalized["characters"]] == ["girlA", "girlB"]
    assert [item["order"] for item in normalized["characters"]] == [0, 1]
    assert normalized["characters"][0]["appearance"]["tags"] == ["long hair"]
    assert normalized["negative"]["quality"]["tags"] == ["bad anatomy"]
    assert normalized["raw_override"]["prompt"] == "legacy prompt"


def test_resolve_document_merges_blocks_and_keeps_role_context():
    resolved = prompt_document.resolve_document(_base_document())

    assert resolved["blocked"] is False
    assert resolved["rating"] == "普通"
    assert resolved["roles"] == [
        {"id": "character-1", "role_id": "girlA", "display_name": "女A", "order": 0},
        {"id": "character-2", "role_id": "girlB", "display_name": "女B", "order": 1},
    ]
    assert resolved["prompt"].startswith("masterpiece, best quality, anime style")
    assert "for the first girl (女A): long hair" in resolved["prompt"]
    assert "for the first girl (女A): red dress" in resolved["prompt"]
    assert "for the second girl (女B): short hair" in resolved["prompt"]
    assert "holding hands" in resolved["prompt"]
    assert "keep both faces visible" in resolved["prompt"]
    assert resolved["negative_prompt"] == "bad anatomy, extra fingers"


def test_duo_pose_requires_two_characters_and_adds_people_constraint():
    document = _base_document()
    document["interaction"]["pose_preset"] = {
        "preset_id": "duo_face_to_face_seated",
        "version": 1,
    }
    resolved = prompt_document.resolve_document(document)
    assert "exactly two people, two separate bodies" in resolved["prompt"]

    document["characters"] = document["characters"][:1]
    invalid = prompt_document.resolve_document(document)
    assert "双人体位需要 2 个角色，当前为 1 个" in invalid["errors"]


def test_body_profiles_default_to_none_and_resolve_independently():
    resolved = prompt_document.resolve_document(
        {
            "mode": "structured",
            "characters": [
                {
                    "id": "first",
                    "role_id": "girlA",
                    "display_name": "First",
                    "gender": "女",
                    "height_frame": "tall",
                    "body_build": "slim",
                    "appearance": {"tags": ["long hair"]},
                    "clothing": {"tags": ["red dress"]},
                },
                {
                    "id": "second",
                    "role_id": "girlB",
                    "display_name": "Second",
                    "gender": "女",
                    "height_frame": "petite_adult",
                    "body_build": "curvy",
                    "appearance": {"tags": ["short hair"]},
                    "clothing": {"tags": ["blue dress"]},
                },
            ],
        }
    )

    prompt = resolved["prompt"]
    first_appearance = prompt.index("for the first girl (First): long hair")
    first_height = prompt.index("for the first girl (First): tall adult woman")
    first_build = prompt.index("for the first girl (First): slender adult woman")
    first_clothing = prompt.index("for the first girl (First): red dress")
    second_height = prompt.index("for the second girl (Second): petite adult woman")
    second_build = prompt.index("for the second girl (Second): curvy adult woman")

    assert first_appearance < first_height < first_build < first_clothing
    assert second_height < second_build
    assert resolved["blocked"] is False


def test_body_profile_defaults_are_none_when_fields_are_missing():
    normalized = prompt_document.normalize_document(
        {
            "mode": "structured",
            "characters": [
                {
                    "id": "hero",
                    "role_id": "girlA",
                    "display_name": "Hero",
                    "gender": "女",
                }
            ],
        }
    )

    assert normalized["characters"][0]["height_frame"] == "none"
    assert normalized["characters"][0]["body_build"] == "none"


def test_slim_and_plump_emit_distinct_silhouette_tags():
    def resolve(body_build: str) -> str:
        return prompt_document.resolve_document(
            {
                "mode": "structured",
                "characters": [
                    {
                        "id": "hero",
                        "role_id": "girlA",
                        "display_name": "Hero",
                        "gender": "女",
                        "body_build": body_build,
                    }
                ],
            }
        )["prompt"]

    slim_prompt = resolve("slim")
    plump_prompt = resolve("plump")

    assert "slender adult woman" in slim_prompt
    assert "slim body" in slim_prompt
    assert "narrow waist" in slim_prompt
    assert "flat stomach" in slim_prompt
    assert "slender thighs" in slim_prompt

    assert "plump adult woman" in plump_prompt
    assert "soft rounded body" in plump_prompt
    assert "round belly" in plump_prompt
    assert "thick thighs" in plump_prompt
    assert "wide hips" in plump_prompt
    assert "soft waist" in plump_prompt


def test_unknown_body_profile_is_rejected():
    with pytest.raises(prompt_document.PromptDocumentError, match="height_frame"):
        prompt_document.resolve_document(
            {
                "mode": "structured",
                "characters": [
                    {
                        "id": "hero",
                        "role_id": "girlA",
                        "display_name": "Hero",
                        "gender": "女",
                        "height_frame": "definitely_missing",
                    }
                ],
            }
        )


def test_appearance_preset_reference_is_resolved_server_side(client):
    created = client.post(
        "/api/prompt-agent/appearance-presets",
        json={
            "preset_id": "test_prompt_document_appearance",
            "name": "Test Appearance",
            "category": "脸部",
            "appearance_tags": ["silver hair", "red eyes"],
            "clothing_tags": ["black coat"],
            "expression_tags": ["focused gaze"],
        },
    )
    assert created.status_code == 200
    preset = created.json()["item"]

    resolved = prompt_document.resolve_document(
        {
            "mode": "structured",
            "characters": [
                {
                    "id": "hero",
                    "role_id": "girlA",
                    "display_name": "Hero",
                    "gender": "女",
                    "appearance": {
                        "preset_refs": [{"preset_id": preset["preset_id"], "version": preset["version"]}]
                    },
                    "clothing": {
                        "preset_refs": [{"preset_id": preset["preset_id"], "version": preset["version"]}]
                    },
                    "expression": {
                        "preset_refs": [{"preset_id": preset["preset_id"], "version": preset["version"]}]
                    },
                }
            ],
        }
    )

    assert resolved["blocked"] is False
    assert "for the first girl (Hero): silver hair" in resolved["prompt"]
    assert "for the first girl (Hero): black coat" in resolved["prompt"]
    assert "for the first girl (Hero): focused gaze" in resolved["prompt"]
    assert resolved["used_ids"] == [preset["preset_id"]]


def test_preset_conflict_is_warning_and_non_blocking():
    resolved = prompt_document.resolve_document(
        {
            "mode": "structured",
            "characters": [
                {
                    "id": "hero",
                    "role_id": "girlA",
                    "display_name": "Hero",
                    "gender": "女",
                    "clothing": {
                        "preset_refs": [
                            {"preset_id": "latex_catsuit"},
                            {"preset_id": "sheer_clothing"},
                        ]
                    },
                }
            ],
        }
    )

    assert resolved["blocked"] is False
    assert any("冲突" in item for item in resolved["warnings"])
    assert not any("冲突" in item for item in resolved["errors"])

def test_restriction_blocks_r18_pose():
    poses = prompt_document.preset_composer._catalog_maps()[0]
    r18_id = next(
        preset_id
        for preset_id, preset in poses.items()
        if str(preset.get("rating") or ("R18" if preset.get("nsfw") else "普通")) == "R18"
    )

    resolved = prompt_document.resolve_document(
        {
            "mode": "structured",
            "characters": [
                {
                    "id": "hero",
                    "role_id": "girlA",
                    "display_name": "Hero",
                    "gender": "女",
                }
            ],
            "interaction": {"pose_preset": {"preset_id": r18_id}},
        },
        restriction_enabled=True,
    )

    assert resolved["rating"] == "R18"
    assert resolved["blocked"] is True
    assert any("内容限制已开启" in error for error in resolved["errors"])


def test_unknown_preset_id_raises_prompt_document_error():
    with pytest.raises(prompt_document.PromptDocumentError, match="不存在的体位 ID"):
        prompt_document.resolve_document(
            {
                "mode": "structured",
                "interaction": {"pose_preset": {"preset_id": "definitely_missing"}},
            }
        )


def test_legacy_prompt_normalization_keeps_original_override():
    normalized = prompt_document.normalize_legacy_prompt("1girl, city", "low quality")

    assert normalized["mode"] == "structured"
    assert normalized["custom"]["global_tags"] == ["1girl", "city"]
    assert normalized["raw_override"]["prompt"] == "1girl, city"
    assert normalized["raw_override"]["negative_prompt"] == "low quality"

    resolved = prompt_document.resolve_document(normalized)
    assert resolved["prompt"] == "1girl, city"
    assert resolved["negative_prompt"] == ""


def test_apply_appearance_preset_to_selected_roles_is_deep_copied():
    preset = database.get_character_appearance_preset("builtin_soft_anime_girl")
    assert preset is not None

    result = prompt_document.apply_appearance_preset(
        {
            "mode": "structured",
            "characters": [
                {"id": "a", "role_id": "girlA", "display_name": "A", "gender": "女"},
                {"id": "b", "role_id": "girlB", "display_name": "B", "gender": "女"},
            ],
        },
        preset,
        ["girlA"],
    )

    first, second = result["characters"]
    assert first["appearance"]["tags"] == preset["appearance_tags"]
    assert second["appearance"]["tags"] == []
    assert first["appearance"]["preset_refs"][0] == {
        "preset_id": preset["preset_id"],
        "version": preset["version"],
    }
    assert first["appearance"]["tags"] is not result["characters"][0]["clothing"]["tags"]


def test_prompt_composer_scope_is_shared_with_document_resolution():
    assert prompt_document.prompt_composer_scope("女A") == "girlA"
