"""Prompt-agent JSON parsing, busy guard, and LoRA purpose tests."""
from __future__ import annotations

import app  # noqa: F401
import comfy_worker
import prompt_agent
import task_registry
from routers import draw as draw_module
from routers import prompt as prompt_module


def test_extract_json_object_tolerates_fence_and_trailing_text():
    text = (
        '解释如下：\n```json\n{"groups":[{"label":"男A","items":["1boy","long hair"]}]}\n```\n'
        "以上是结果"
    )
    data = prompt_agent.extract_json_payload(text, "object")
    assert data["groups"][0]["label"] == "男A"


def test_extract_json_object_recovers_truncated_output():
    text = '{"groups":[{"label":"男A","items":["1boy","long hair"'
    data = prompt_agent.extract_json_payload(text, "object")
    assert data["groups"][0]["items"] == ["1boy", "long hair"]


def test_normalize_split_groups_drops_empty_and_duplicate_labels():
    groups = prompt_agent.normalize_split_groups(
        [
            {"label": "男A", "items": ["1boy", "long hair"]},
            {"label": "男A", "items": ["repeated"]},
            {"label": "其他", "items": []},
            {"label": "服装", "items": ["school uniform"]},
            "not-a-group",
        ]
    )
    assert groups == [
        {"label": "男A", "items": ["1boy", "long hair"]},
        {"label": "服装", "items": ["school uniform"]},
    ]


def test_role_split_falls_back_to_groups_when_llm_json_is_empty(monkeypatch):
    monkeypatch.setattr(
        prompt_agent.llm,
        "chat",
        lambda *args, **kwargs: '{"groups":[]}',
    )
    groups = prompt_agent.split_prompt_role_aware("一个蓝发男孩", ["1boy", "long hair", "standing"])
    assert groups
    assert any(group["label"] == "人物" for group in groups)
    assert any("standing" in group["items"] for group in groups)


def test_role_split_rescues_appearance_from_wrong_style_group():
    raw = [
        {"label": "画风", "items": ["1girl", "blue eyes", "long hair", "masterpiece"]},
        {"label": "服装", "items": ["school uniform"]},
        {"label": "动作", "items": ["standing", "looking at viewer"]},
        {"label": "场景", "items": ["simple background"]},
    ]
    groups = prompt_agent._complete_role_groups(raw, ["1girl", "blue eyes", "long hair", "masterpiece"])
    role = next(group for group in groups if group["label"] == "女A")
    assert set(role["items"]) == {"1girl", "blue eyes", "long hair"}
    style = next(group for group in groups if group["label"] == "画风")
    assert style["items"] == ["masterpiece"]


def test_prompt_llm_endpoints_block_while_draw_running(client):
    task_registry.register("draw", "draw-busy-prompt-1")
    try:
        response = client.post(
            "/api/prompt-agent/split",
            json={"text": "1girl, masterpiece"},
        )
        assert response.status_code == 409
        assert "AI 绘画" in response.json()["detail"]
    finally:
        task_registry.finish("draw", "draw-busy-prompt-1", "done")


def test_role_split_parse_error_returns_friendly_422(client, monkeypatch):
    monkeypatch.setattr(
        prompt_module.prompt_agent,
        "split_prompt_role_aware",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("JSON 解析失败")),
    )
    response = client.post(
        "/api/prompt-agent/split",
        json={"text": "1boy, long hair", "description": "蓝发男孩", "role_aware": True},
    )
    assert response.status_code == 422
    assert "模型输出不是有效 JSON" in response.json()["detail"]


def test_lora_purpose_marks_wan_video_lora_incompatible():
    purpose, compatible, reason = comfy_worker.classify_lora_purpose(
        "wan21_general_nsfw_e14_fixed.safetensors"
    )
    assert purpose == "video"
    assert compatible is False
    assert reason


def test_lora_purpose_uses_anima_metadata():
    metadata = {
        "modelspec.architecture": "anima-preview/lora",
        "ss_base_model_version": "anima",
    }
    purpose, compatible, reason = comfy_worker.classify_lora_purpose(
        "my_custom_comfy.safetensors",
        metadata,
        ["diffusion_model.blocks.0.cross_attn.k_proj.lora_A.weight"],
    )
    assert purpose == "drawing"
    assert compatible is True
    assert reason == ""


def test_get_loras_preserves_purpose_fields(client, monkeypatch):
    monkeypatch.setattr(
        draw_module,
        "list_loras",
        lambda: [
            {
                "name": "anima-turbo-lora-v0.2.safetensors",
                "size_mb": 142.0,
                "purpose": "drawing",
                "compatible": True,
                "incompatible_reason": None,
            },
            {
                "name": "wan21_general_nsfw_e14_fixed.safetensors",
                "size_mb": 585.0,
                "purpose": "video",
                "compatible": False,
                "incompatible_reason": "Wan 视频 LoRA",
            },
        ],
    )
    response = client.get("/api/loras")
    assert response.status_code == 200
    by_name = {item["name"]: item for item in response.json()["loras"]}
    assert by_name["anima-turbo-lora-v0.2.safetensors"]["compatible"] is True
    assert by_name["wan21_general_nsfw_e14_fixed.safetensors"]["compatible"] is False
    assert by_name["wan21_general_nsfw_e14_fixed.safetensors"]["purpose"] == "video"
