from __future__ import annotations

import prompt_agent
import prompt_profiles


def test_model_prompt_rules_remain_distinct() -> None:
    general = prompt_profiles.resolve_prompt_profile("general")
    qwen = prompt_profiles.resolve_prompt_profile("qwen_image_edit")
    flux = prompt_profiles.resolve_prompt_profile("flux2_edit")
    storyboard = prompt_profiles.resolve_prompt_profile("storyboard")

    assert len({general.instruction, qwen.instruction, flux.instruction, storyboard.instruction}) == 4
    assert "保持不变" in qwen.instruction
    assert "避免复述" in flux.instruction
    assert "每个镜头必须独立" in storyboard.instruction


def test_refine_profile_rules_are_injected_without_changing_core_call(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_refine(description, current_prompt, requirements, pose_tags):
        captured.update(
            {
                "description": description,
                "current_prompt": current_prompt,
                "requirements": requirements,
                "pose_tags": pose_tags,
            }
        )
        return {"prompt": "final prompt", "groups": []}

    monkeypatch.setattr(prompt_agent, "_refine_prompt_legacy", fake_refine)
    result = prompt_agent.refine_prompt(
        "description",
        "current",
        "replace the background",
        ["standing"],
        "flux2_edit",
    )

    assert result["profile_id"] == "flux2_edit"
    assert result["profile_label"] == "FLUX.2 图像编辑"
    assert "避免复述" in str(captured["requirements"])
    assert "replace the background" in str(captured["requirements"])


def test_prompt_profile_catalog_is_exposed(client) -> None:
    response = client.get("/api/prompt-agent/prompt-profiles")
    assert response.status_code == 200
    body = response.json()
    assert body["default"] == "general"
    assert {item["id"] for item in body["items"]} == {
        "general",
        "qwen_image_edit",
        "flux2_edit",
        "storyboard",
    }
