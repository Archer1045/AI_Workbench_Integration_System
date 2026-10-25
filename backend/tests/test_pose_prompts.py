"""Pose prompt layering and composition defaults."""
from __future__ import annotations

import pose_prompts


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
