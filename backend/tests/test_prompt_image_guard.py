"""Image-to-prompt structured fact guard tests."""
from __future__ import annotations

import base64
import json

import pytest

import app  # noqa: F401
import prompt_agent
from routers import prompt as prompt_module


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


def _payload(**overrides) -> dict:
    data = {
        "description": "昏暗卧室内，一名白发女性骑在男性身上并发生阴茎插入阴道，另一名男性站在床边观看。",
        "counts": {"girls": 1, "boys": 2, "others": 0, "total": 3},
        "scene": {
            "location": "bedroom",
            "evidence": "画面可见床垫、床单和枕头；没有海水、沙滩或海岸线。",
        },
        "actions": ["cowgirl position", "standing and watching"],
        "contact": ["penis inside vagina"],
        "rating": "r18",
        "tags": [
            "nude",
            "sex",
            "penis inside vagina",
            "cowgirl position",
            "dark background",
        ],
    }
    data.update(overrides)
    return data


def _mock_vlm(
    monkeypatch,
    outputs: list[dict | str],
    action_audit: dict | None = None,
) -> list[dict]:
    calls: list[dict] = []
    queue = list(outputs)
    last_primary_tags: list[str] = []

    def fake_post(url, **kwargs):
        nonlocal last_primary_tags
        calls.append({"url": url, **kwargs})
        if "动作事实复核器" in str(kwargs.get("json", {}).get("prompt") or ""):
            if action_audit is not None:
                return _Response({"response": json.dumps(action_audit, ensure_ascii=False)})
            actions = [
                {"tag": tag, "evidence": tag, "confidence": 0.9}
                for tag in last_primary_tags
                if tag in prompt_agent._CANONICAL_ACTION_TAGS
            ]
            return _Response({"response": json.dumps({"actions": actions}, ensure_ascii=False)})
        if not queue:
            raise AssertionError("unexpected extra VLM request")
        item = queue.pop(0)
        if isinstance(item, dict):
            last_primary_tags = [
                str(tag).strip().lower()
                for tag in item.get("tags") or []
                if str(tag).strip()
            ]
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return _Response({"response": text})

    monkeypatch.setattr(prompt_agent, "vlm_model", lambda: "test-vlm:latest")
    monkeypatch.setattr(prompt_agent.requests, "post", fake_post)
    return calls


def test_image_prompt_preserves_people_r18_and_verified_bedroom(monkeypatch):
    calls = _mock_vlm(monkeypatch, [_payload()])
    monkeypatch.setattr(prompt_agent, "_to_english_tags", lambda tags: tags)

    result = prompt_agent.image_to_prompt(b"fake-image")

    assert calls[0]["json"]["format"] == "json"
    assert calls[0]["json"]["model"] == "test-vlm:latest"
    assert result["analysis"]["counts"] == {"girls": 1, "boys": 2, "others": 0, "total": 3}
    assert result["analysis"]["scene"]["location"] == "bedroom"
    assert result["analysis"]["vlm_model"] == "test-vlm:latest"
    prompt = result["prompt"]
    for tag in (
        "1girl",
        "2boys",
        "r18",
        "explicit",
        "sex",
        "penis inside vagina",
        "bedroom",
        "on bed",
    ):
        assert tag in prompt
    assert "beach" not in prompt


def test_image_prompt_filters_repetitive_generic_tags(monkeypatch):
    payload = _payload(
        tags=[
            "nude",
            "sex",
            "penis inside vagina",
            "sexual activity",
            "sexual content",
            "sexual activity scene with multiple characters",
            "sexual activity scene with multiple characters and sexual positions and sexual content",
        ],
    )
    _mock_vlm(monkeypatch, [payload])
    monkeypatch.setattr(prompt_agent, "_to_english_tags", lambda tags: tags)

    result = prompt_agent.image_to_prompt(b"fake-image")

    prompt = result["prompt"]
    for tag in ("1girl", "2boys", "explicit", "sex", "penis inside vagina"):
        assert tag in prompt
    assert "sexual activity" not in prompt
    assert "sexual content" not in prompt


def test_image_prompt_normalizes_unknown_bed_scene_and_drops_low_value_tags(monkeypatch):
    payload = _payload(
        scene={"location": "unknown", "evidence": "画面可见床垫、床单和枕头"},
        tags=[
            "nude",
            "sex",
            "penis inside vagina",
            "female",
            "male",
            "multiple boys",
            "intimate interaction",
            "multiple",
            "intimate",
            "erotic",
            "r18",
            "3 people",
            "insertion",
            "one girl",
            "two boys",
        ],
    )
    _mock_vlm(monkeypatch, [payload])
    monkeypatch.setattr(prompt_agent, "_to_english_tags", lambda tags: tags)

    result = prompt_agent.image_to_prompt(b"fake-image")

    assert result["analysis"]["scene"]["location"] == "bedroom"
    prompt = result["prompt"]
    for tag in ("1girl", "2boys", "explicit", "sex", "penis inside vagina", "bedroom", "on bed"):
        assert tag in prompt
    for tag in (
        "female",
        "male",
        "multiple boys",
        "multiple girls",
        "intimate interaction",
        "multiple",
        "intimate",
        "erotic",
        "3 people",
        "insertion",
        "one girl",
        "two boys",
    ):
        assert tag not in prompt


def test_image_prompt_drops_explicit_tags_without_matching_evidence(monkeypatch):
    payload = _payload(
        description="一名女性与两名男性在卧室中，其中一人进行口交，另一人站立观看。",
        actions=["口交", "站立观看"],
        contact=["penis inside vagina"],
        tags=["nude", "sex", "oral sex", "penis inside vagina", "cowgirl position"],
    )
    _mock_vlm(
        monkeypatch,
        [payload],
        action_audit={
            "actions": [
                {"tag": "fellatio", "evidence": "口部与阴茎直接接触", "confidence": 0.85}
            ]
        },
    )
    monkeypatch.setattr(prompt_agent, "_to_english_tags", lambda tags: tags)

    result = prompt_agent.image_to_prompt(b"fake-image")

    assert "oral sex" not in result["prompt"]
    assert "fellatio" in result["prompt"]
    assert "penis inside vagina" not in result["prompt"]
    assert "cowgirl position" not in result["prompt"]


def test_image_prompt_rejects_beach_without_beach_evidence_and_retries(monkeypatch):
    invalid = _payload(
        description="昏暗背景中的男女。",
        scene={"location": "night beach", "evidence": "dark background only"},
        tags=["1girl", "2boys", "nude", "beach", "night beach"],
    )
    calls = _mock_vlm(monkeypatch, [invalid, invalid])

    with pytest.raises(ValueError, match="结构化事实或存在矛盾"):
        prompt_agent.image_to_prompt(b"fake-image")
    assert len(calls) == 2
    assert "scene.evidence" in calls[1]["json"]["prompt"]


def test_image_prompt_retries_truncated_json_then_accepts_complete_result(monkeypatch):
    truncated = '{"description":"卧室内","counts":{"girls":1'
    calls = _mock_vlm(monkeypatch, [truncated, _payload()])
    monkeypatch.setattr(prompt_agent, "_to_english_tags", lambda tags: tags)

    result = prompt_agent.image_to_prompt(b"fake-image")

    assert len(calls) == 3
    assert "JSON 不完整或被截断" in calls[1]["json"]["prompt"]
    assert result["analysis"]["counts"]["total"] == 3


def test_image_prompt_rejects_old_unstructured_output(monkeypatch):
    old = {"description": "床上三名角色", "tags": ["nude", "sex", "beach"]}
    calls = _mock_vlm(monkeypatch, [old, old])

    with pytest.raises(ValueError, match="缺少 counts"):
        prompt_agent.image_to_prompt(b"fake-image")
    assert len(calls) == 2


def test_image_prompt_retries_placeholder_actions(monkeypatch):
    invalid = _payload(actions=["可见动作或体位"])
    calls = _mock_vlm(monkeypatch, [invalid, _payload()])
    monkeypatch.setattr(prompt_agent, "_to_english_tags", lambda tags: tags)

    result = prompt_agent.image_to_prompt(b"fake-image")

    assert len(calls) == 3
    assert "actions 缺少具体可见动作或体位" in calls[1]["json"]["prompt"]
    assert result["analysis"]["actions"] == ["cowgirl position", "standing and watching"]


def test_chinese_tag_translation_cannot_drop_counts_or_r18_facts(monkeypatch):
    payload = _payload(
        description="昏暗卧室中一名女性和两名男性，发生性交。",
        scene={"location": "卧室", "evidence": "可见床垫、床单和枕头"},
        actions=["骑乘位"],
        contact=["阴茎插入阴道"],
        tags=["裸体", "性交", "骑乘位", "深色背景"],
    )
    _mock_vlm(
        monkeypatch,
        [payload],
        action_audit={
            "actions": [
                {"tag": "cowgirl position", "evidence": "女性骑在男性身上", "confidence": 0.85}
            ]
        },
    )
    monkeypatch.setattr(prompt_agent, "_to_english_tags", lambda tags: ["dark background"])

    result = prompt_agent.image_to_prompt(b"fake-image")

    prompt = result["prompt"]
    assert "1girl" in prompt
    assert "2boys" in prompt
    assert "explicit" in prompt
    assert "sex" in prompt
    assert "bedroom" in prompt


def test_image_prompt_derives_specific_action_and_drops_unsupported_insertion(monkeypatch):
    payload = _payload(
        description="昏暗卧室中，一名女性与两名男性，其中一名男性接受口交，另一名男性站立观看。",
        actions=["男性接受口交", "女性用手握住男性阴茎并套弄", "另一名男性站立观看"],
        contact=["女性手部与男性阴茎接触"],
        tags=[
            "nude",
            "sex",
            "oral sex",
            "handjob",
            "sexual intercourse",
            "insertion",
            "multiple",
            "intimate",
        ],
    )
    _mock_vlm(
        monkeypatch,
        [payload],
        action_audit={
            "actions": [
                {"tag": "fellatio", "evidence": "口部与阴茎直接接触", "confidence": 0.85},
                {"tag": "handjob", "evidence": "手部直接握住阴茎并套弄", "confidence": 0.9},
            ]
        },
    )
    monkeypatch.setattr(prompt_agent, "_to_english_tags", lambda tags: tags)

    result = prompt_agent.image_to_prompt(b"fake-image")

    prompt = result["prompt"]
    assert "fellatio" in prompt
    assert "handjob" in prompt
    assert "oral sex" not in prompt
    assert "insertion" not in prompt
    assert "sexual intercourse" not in prompt
    assert "multiple" not in prompt
    assert "intimate" not in prompt
    assert result["analysis"]["verified_actions"] == ["fellatio", "handjob"]


def test_image_prompt_uses_independent_action_audit_when_primary_facts_are_generic(monkeypatch):
    payload = _payload(
        description="昏暗卧室中三名角色发生性行为，但未描述具体动作。",
        actions=["亲密互动"],
        contact=["人物之间存在性接触"],
        rating="suggestive",
        tags=["nude", "sex", "multiple", "intimate"],
    )
    audit = {
        "actions": [
            {
                "tag": "handjob",
                "evidence": "女性右手直接握住站立男性的阴茎并进行套弄",
                "confidence": 0.86,
            }
        ]
    }
    calls = _mock_vlm(monkeypatch, [payload], action_audit=audit)
    monkeypatch.setattr(prompt_agent, "_to_english_tags", lambda tags: tags)

    result = prompt_agent.image_to_prompt(b"fake-image")

    assert len(calls) == 2
    prompt = result["prompt"]
    assert "handjob" in prompt
    assert "r18" in prompt
    assert "explicit" in prompt
    assert "sex" in prompt
    assert result["analysis"]["verified_actions"] == ["handjob"]


def test_image_prompt_rejects_explicit_result_without_verifiable_action(monkeypatch):
    payload = _payload(
        description="昏暗卧室中三名角色发生性行为，但未描述具体动作。",
        actions=["亲密互动"],
        contact=["人物之间存在性接触"],
        tags=["nude", "sex"],
    )
    audit = {"actions": [{"tag": "handjob", "evidence": "", "confidence": 0.9}]}
    calls = _mock_vlm(monkeypatch, [payload], action_audit=audit)
    monkeypatch.setattr(prompt_agent, "_to_english_tags", lambda tags: tags)

    with pytest.raises(ValueError, match="缺少独立动作证据"):
        prompt_agent.image_to_prompt(b"fake-image")
    assert len(calls) == 3


def test_from_image_records_effective_vlm_model(client, monkeypatch):
    captured: list[tuple] = []
    monkeypatch.setattr(prompt_module.prompt_agent, "is_available", lambda: True)
    monkeypatch.setattr(prompt_module.prompt_agent, "vlm_model", lambda: "custom-vlm:latest")
    monkeypatch.setattr(
        prompt_module.prompt_agent,
        "image_to_prompt",
        lambda image_bytes, filename, **_kwargs: {
            "description": "结构化描述",
            "prompt": "1girl, bedroom",
            "filename": filename,
        },
    )
    monkeypatch.setattr(prompt_module, "translate_text", lambda text: "")
    monkeypatch.setattr(
        prompt_module.database,
        "insert_prompt_record",
        lambda *args, **kwargs: captured.append(args) or 1,
    )

    response = client.post(
        "/api/prompt/from-image",
        json={"image_base64": base64.b64encode(b"fake-image").decode("ascii"), "filename": "test.png"},
    )

    assert response.status_code == 200
    assert captured and captured[0][5] == "custom-vlm:latest"
