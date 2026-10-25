"""WD14 反推（提示词 Agent 图片反推的标签模式）测试。"""
from __future__ import annotations

import base64
import io

import pytest

import prompt_agent


def _prob(general_count: int, character_count: int, values: dict[int, float]) -> list[float]:
    """构造与真实模型同布局的 logits：前 4 个是 rating，随后 general，最后 character。"""
    prob = [0.0] * (4 + general_count + character_count)
    for index, value in values.items():
        prob[index] = value
    return prob


def test_select_wd14_tags_keeps_general_then_character_order() -> None:
    general = ["1girl", "solo", "long_hair"]
    character = ["bronya_zaychik"]
    prob = _prob(len(general), len(character), {4: 0.9, 5: 0.4, 6: 0.2, 7: 0.95})
    picked = prompt_agent._select_wd14_tags(prob, general, character, 0.35)
    assert picked["general"] == ["1girl", "solo"]  # 0.2 低于阈值被丢弃
    assert picked["character"] == ["bronya zaychik"]  # 去下划线，且 order 在 general 之后
    assert picked["general"] + picked["character"] == ["1girl", "solo", "bronya zaychik"]


def test_select_wd14_tags_respects_threshold_and_can_keep_underscores() -> None:
    general = ["1girl", "solo"]
    prob = _prob(len(general), 0, {4: 0.5, 5: 0.34})
    assert prompt_agent._select_wd14_tags(prob, general, [], 0.5)["general"] == ["1girl"]
    loose = prompt_agent._select_wd14_tags(prob, general, [], 0.3, remove_underscore=False)
    assert loose["general"] == ["1girl", "solo"]


def test_wd14_rating_mapping_matches_vlm_vocabulary() -> None:
    assert prompt_agent._wd14_rating({"rating": "explicit"}) == "r18"
    assert prompt_agent._wd14_rating({"rating": "questionable"}) == "r18"
    assert prompt_agent._wd14_rating({"rating": "sensitive"}) == "suggestive"
    assert prompt_agent._wd14_rating({"rating": "general"}) == "sfw"
    assert prompt_agent._wd14_rating({}) == "unknown"


def test_merge_wd14_tags_puts_wd14_first_and_dedupes() -> None:
    merged = prompt_agent._merge_wd14_tags(
        {"prompt": "1girl, solo, looking at viewer"},
        {"tags": ["1girl", "long hair", "bronya zaychik"]},
    )
    assert merged == "1girl, long hair, bronya zaychik, solo, looking at viewer"


def test_image_to_prompt_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        prompt_agent.image_to_prompt(b"", "x.png", mode="nope")


@pytest.mark.skipif(not prompt_agent.wd14_available(), reason="本地没有 WD14 模型文件")
def test_wd14_tags_runs_on_real_model() -> None:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (256, 384), (240, 240, 240)).save(buffer, format="PNG")
    result = prompt_agent.wd14_tags(buffer.getvalue())
    assert result["model"].startswith("wd14:")
    assert isinstance(result["tags"], list)
    assert set(result["rating_scores"]) == {"general", "sensitive", "questionable", "explicit"}
    assert result["rating"] in {"general", "sensitive", "questionable", "explicit"}


def _image_payload(mode: str) -> dict:
    return {
        "image_base64": base64.b64encode(b"fake-image").decode("ascii"),
        "filename": "test.png",
        "mode": mode,
    }


def test_from_image_wd14_mode_does_not_require_ollama(client, monkeypatch, tmp_path) -> None:
    from routers import prompt as prompt_module

    monkeypatch.setattr(prompt_module, "AI_PRODUCT_DIR", tmp_path)
    monkeypatch.setattr(prompt_module.prompt_agent, "is_available", lambda: False)
    monkeypatch.setattr(prompt_module.prompt_agent, "wd14_available", lambda: True)
    monkeypatch.setattr(
        prompt_module.prompt_agent,
        "image_to_prompt",
        lambda image_bytes, filename, **kwargs: {
            "description": "",
            "prompt": "1girl, solo",
            "filename": filename,
            "analysis": {"mode": "wd14", "model_label": "wd14:test@0.35"},
        },
    )
    monkeypatch.setattr(prompt_module, "translate_text", lambda text: "")
    monkeypatch.setattr(prompt_module.database, "insert_prompt_record", lambda *args, **kwargs: 1)

    response = client.post("/api/prompt/from-image", json=_image_payload("wd14"))
    assert response.status_code == 200
    assert response.json()["prompt"] == "1girl, solo"


def test_from_image_vlm_mode_requires_ollama(client, monkeypatch) -> None:
    from routers import prompt as prompt_module

    monkeypatch.setattr(prompt_module.prompt_agent, "is_available", lambda: False)
    response = client.post("/api/prompt/from-image", json=_image_payload("vlm"))
    assert response.status_code == 503
    assert "Ollama" in response.json()["detail"]


def test_from_image_rejects_unknown_mode(client) -> None:
    response = client.post("/api/prompt/from-image", json=_image_payload("nope"))
    assert response.status_code == 400
