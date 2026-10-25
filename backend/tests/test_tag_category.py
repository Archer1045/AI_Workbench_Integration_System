"""Local dictionary, vector fallback, and layered split tests."""
from __future__ import annotations

import app  # noqa: F401  (adds project agent/knowledge-base paths before router imports)
import tag_category
from routers import prompt as prompt_module


def test_dictionary_covers_common_categories():
    cases = {
        "1girl": "character",
        "white hair": "character",
        "school uniform": "character",
        "black lace long gloves": "character",
        "standing": "action",
        "holding hands": "action",
        "sex": "action",
        "simple background": "background",
        "white background": "background",
        "masterpiece": "style",
        "best quality": "style",
        "anime coloring": "style",
        "uncensored": "other",
        "onee-shota": "other",
    }
    for tag, expected in cases.items():
        assert tag_category.dictionary_category(tag) == expected, tag


def test_dictionary_returns_none_for_unknown_tag():
    assert tag_category.dictionary_category("totally_unknown_zzz") is None


def test_dictionary_classifies_malformed_or_meta_text_as_other():
    assert tag_category.dictionary_category("@rella") == "other"
    assert tag_category.dictionary_category("-----") == "other"
    assert tag_category.dictionary_category("completely consumed by the act of devouring the Damselette shadow") == "other"


def test_dictionary_normalizes_weighted_and_underscored_tags():
    assert tag_category.dictionary_category("(masterpiece:1.2)") == "style"
    assert tag_category.dictionary_category("White_Hair_(long)") == "character"
    assert tag_category.dictionary_category("Firefly (Honkai: Star Rail)") == "character"
    assert tag_category.dictionary_category("best-quality") == "style"


def test_best_vector_category_returns_closest():
    labeled = [
        ("character", [1.0, 0.0, 0.0]),
        ("action", [0.0, 1.0, 0.0]),
        ("background", [0.0, 0.0, 1.0]),
    ]
    assert tag_category.best_vector_category([0.9, 0.2, 0.1], labeled) == "character"


def test_best_vector_category_respects_threshold():
    labeled = [("character", [1.0, 0.0, 0.0])]
    assert tag_category.best_vector_category([0.4, 0.3, 0.3], labeled, min_similarity=0.8) is None


def test_split_uses_dictionary_without_external_layers(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        prompt_module.tag_category,
        "vector_category",
        lambda tag: calls.append(str(tag)) or "style",
    )
    monkeypatch.setattr(
        prompt_module,
        "_split_unresolved_with_llm",
        lambda tags: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )
    groups = prompt_module._split_tags(
        ["1girl", "masterpiece", "standing", "simple background"]
    )
    assert calls == []
    assert groups["character"] == ["1girl"]
    assert groups["style"] == ["masterpiece"]
    assert groups["action"] == ["standing"]
    assert groups["background"] == ["simple background"]


def test_split_uses_vector_fallback_before_llm(monkeypatch):
    monkeypatch.setattr(
        prompt_module.tag_category,
        "vector_category",
        lambda tag: "style" if "mystyle" in tag else None,
    )
    monkeypatch.setattr(
        prompt_module,
        "_split_unresolved_with_llm",
        lambda tags: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )
    groups = prompt_module._split_tags(["1girl", "special_mystyle_tag"])
    assert groups["character"] == ["1girl"]
    assert groups["style"] == ["special_mystyle_tag"]


def test_split_uses_llm_only_for_unresolved_tags(monkeypatch):
    unresolved_seen: list[list[str]] = []
    monkeypatch.setattr(prompt_module.tag_category, "vector_category", lambda tag: None)

    def fake_llm(unresolved: list[str]) -> dict[str, list[str]]:
        unresolved_seen.append(unresolved)
        return {"character": ["unknown_tag_xyz"]}

    monkeypatch.setattr(prompt_module, "_split_unresolved_with_llm", fake_llm)
    groups = prompt_module._split_tags(["1girl", "unknown_tag_xyz"])
    assert unresolved_seen == [["unknown_tag_xyz"]]
    assert groups["character"] == ["1girl", "unknown_tag_xyz"]


def test_split_puts_unresolved_to_other_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(prompt_module.tag_category, "vector_category", lambda tag: None)
    monkeypatch.setattr(prompt_module, "_split_unresolved_with_llm", lambda tags: {})
    groups = prompt_module._split_tags(["unknown_tag_xyz", "1girl"])
    assert groups["character"] == ["1girl"]
    assert groups["other"] == ["unknown_tag_xyz"]


def test_split_api_keeps_five_category_keys(client, monkeypatch):
    monkeypatch.setattr(prompt_module.tag_category, "vector_category", lambda tag: None)
    monkeypatch.setattr(prompt_module, "_split_unresolved_with_llm", lambda tags: {})
    response = client.post(
        "/api/prompt-agent/split",
        json={"text": "1girl, masterpiece, standing, simple background, unknown_xyz"},
    )
    assert response.status_code == 200
    groups = response.json()["groups"]
    assert set(groups) == set(prompt_module.SPLIT_CATEGORIES)
    assert groups["character"] == ["1girl"]
    assert groups["style"] == ["masterpiece"]
    assert groups["action"] == ["standing"]
    assert groups["background"] == ["simple background"]
    assert groups["other"] == ["unknown_xyz"]
