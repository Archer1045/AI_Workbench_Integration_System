"""Pose prompt layering and composition defaults."""
from __future__ import annotations

import pose_prompts
import pose_presets_20261102
import pose_presets_duo_r18_20261102_b
import pose_presets_r18_20261102
import prompt_agent


def test_pose_core_prompt_drops_boilerplate_but_keeps_action_and_consent():
    preset = {
        "tags": [
            "two adults",
            "same-age adult partners",
            "consensual",
            "missionary position",
            "knees bent",
            "uncensored",
        ],
        "draw_prompt": (
            "missionary position with bent knees; visible faces and separate "
            "bodies; no extra limbs"
        ),
        "people_count": 2,
        "people_prompt": "exactly 2 people, two separate bodies",
    }

    assert pose_prompts.pose_core_tags(preset) == [
        "missionary position",
        "knees bent",
        "adult characters",
        "consensual",
    ]
    core = pose_prompts.pose_prompt(preset, "core")
    assert core.startswith(
        "exactly 2 people, two separate bodies, missionary position"
    )
    assert "uncensored" not in core
    assert "no extra limbs" not in core
    full = pose_prompts.pose_prompt(preset, "full")
    assert "visible faces and separate bodies" in full
    assert len(core) < len(full)


def test_pose_api_exposes_core_and_full_prompts(client):
    response = client.get("/api/prompt-agent/pose-presets")
    assert response.status_code == 200
    items = response.json()["items"]
    pose = next(item for item in items if item["id"] == "group_triangle_three")

    assert pose["core_tags"] == [
        "triangular formation",
        "group pose",
        "separate bodies",
    ]
    assert "triangular formation" in pose["core_prompt"]
    assert "single continuous scene with anime rendering" not in pose["core_prompt"]
    assert "single continuous scene with anime rendering" in pose["full_prompt"]
    assert len(pose["core_prompt"]) < len(pose["full_prompt"])


def test_preset_composition_uses_short_pose_prompt_by_default(client):
    response = client.post(
        "/api/prompt-agent/compose-presets",
        json={
            "pose_id": "group_triangle_three",
            "role_order": ["角色A", "角色B", "角色C"],
        },
    )
    assert response.status_code == 200
    prompt = response.json()["prompt"]
    assert "triangular formation" in prompt
    assert "single continuous scene with anime rendering" not in prompt
    assert "separate opaque bodies with clear silhouettes" in prompt


def test_daily_pose_batch_adds_21_unique_non_previewed_presets():
    definitions = pose_presets_20261102.POSE_PRESET_DEFINITIONS
    ids = [item["id"] for item in definitions]
    assert len(definitions) == 21
    assert len(ids) == len(set(ids))

    by_id = {item["id"]: item for item in prompt_agent.POSE_PRESETS}
    assert len(prompt_agent.POSE_PRESETS) == 509
    assert set(ids) <= set(by_id)
    for preset_id in ids:
        preset = by_id[preset_id]
        assert preset["rating"] == "普通"
        assert preset["image"] is None
        assert preset["has_image"] is False
        assert preset["source"] == "builtin"
        assert preset["people_prompt"]
        assert pose_prompts.pose_prompt(preset)


def test_daily_pose_candidates_are_available_from_api_and_composable(client):
    response = client.get("/api/prompt-agent/pose-presets")
    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()["items"]}
    assert by_id["solo_walking_forward"]["label"] == "自然前行"
    assert by_id["duo_forehead_touch"]["people_count"] == 2
    assert by_id["duo_handshake"]["has_image"] is False

    composed = client.post(
        "/api/prompt-agent/compose-presets",
        json={
            "pose_id": "duo_forehead_touch",
            "role_order": ["角色A", "角色B"],
        },
    )
    assert composed.status_code == 200
    prompt = composed.json()["prompt"]
    assert "exactly two people" in prompt
    assert "forehead touch" in prompt


def test_adult_pose_batch_adds_22_non_mirror_presets():
    definitions = pose_presets_r18_20261102.POSE_PRESET_DEFINITIONS
    ids = [item["id"] for item in definitions]
    assert len(definitions) == 22
    assert len(ids) == len(set(ids))
    assert sum(item["kind"] == "solo" for item in definitions) == 11
    assert sum(item["kind"] == "duo" for item in definitions) == 6
    assert sum(item["kind"] == "group" for item in definitions) == 5
    serialized = repr(definitions).lower()
    assert "mirror" not in serialized
    assert "镜子" not in serialized

    by_id = {item["id"]: item for item in prompt_agent.POSE_PRESETS}
    assert len(prompt_agent.POSE_PRESETS) == 509
    assert len(prompt_agent.SOLO_R18_POSE_IDS) == 138
    assert set(ids) <= set(by_id)
    for preset_id in ids:
        preset = by_id[preset_id]
        assert preset["rating"] == "R18"
        assert preset["image"] is None
        assert preset["has_image"] is False
    for item in definitions:
        if item["kind"] == "group":
            preset = by_id[item["id"]]
            assert preset["people"] == "多人"
            assert preset["people_count"] == 3
            assert preset["role_slots"] == ["女A", "男A", "男B"]


def test_duo_sex_pose_batch_adds_20_adult_in_progress_presets(client):
    definitions = pose_presets_duo_r18_20261102_b.POSE_PRESET_DEFINITIONS
    ids = [item["id"] for item in definitions]
    assert len(definitions) == 20
    assert len(ids) == len(set(ids))
    assert sum(item["orientation"] == "男女" for item in definitions) == 16
    assert sum(item["orientation"] == "女女" for item in definitions) == 4

    by_id = {item["id"]: item for item in prompt_agent.POSE_PRESETS}
    assert len(by_id) == len(prompt_agent.POSE_PRESETS) == 509
    assert set(ids) <= set(by_id)
    for definition in definitions:
        preset = by_id[definition["id"]]
        assert preset["rating"] == "R18"
        assert preset["people"] == "双人"
        assert preset["people_count"] == 2
        assert len(preset["role_slots"]) == 2
        assert preset["orientation"] == definition["orientation"]
        assert preset["contact_points"] == definition["contact_points"]
        assert preset["image"] is None
        assert preset["has_image"] is False
        assert "sex in progress" in " ".join(preset["tags"]).lower()
        assert "consent" in " ".join(preset["tags"]).lower()
        assert preset["draw_prompt"]
        public_text = " ".join(
            [
                str(definition["id"]),
                str(definition["label"]),
                *map(str, definition["tags"]),
            ]
        ).lower()
        assert "mirror" not in public_text
        assert "镜子" not in public_text

    response = client.get("/api/prompt-agent/pose-presets")
    assert response.status_code == 200
    assert response.json()["total"] == 509
    api_by_id = {item["id"]: item for item in response.json()["items"]}
    assert api_by_id["duo_bathtub_edge_rear_embrace_r18"]["people_count"] == 2

    composed = client.post(
        "/api/prompt-agent/compose-presets",
        json={
            "pose_id": "lesbian_futon_scissors_r18",
            "role_order": ["女性角色A", "女性角色B"],
        },
    )
    assert composed.status_code == 200
    prompt = composed.json()["prompt"]
    assert "exactly two people" in prompt
    assert "two separate bodies" in prompt
    assert "lesbian sex in progress" in prompt
    assert "futon" in prompt


def test_two_men_one_woman_pose_is_composable(client):
    composed = client.post(
        "/api/prompt-agent/compose-presets",
        json={
            "pose_id": "threesome_mmf_round_bed_center_r18",
            "role_order": ["女A", "男A", "男B"],
        },
    )
    assert composed.status_code == 200
    prompt = composed.json()["prompt"]
    assert "exactly three people" in prompt
    assert "three separate bodies" in prompt
    assert "round bed" in prompt
