"""Expression preset catalog and prompt reference tests."""
from __future__ import annotations

import expression_presets
import prompt_document


def test_expression_catalog_is_complete_and_unambiguous():
    items = expression_presets.EXPRESSION_PRESETS

    assert len(items) == 24
    assert len({item["id"] for item in items}) == len(items)
    assert all(2 <= len(item["tags"]) <= 6 for item in items)
    assert all(item["label"] for item in items)
    assert all(item["translation"] for item in items)
    assert all(item["character_scope"] == ["通用"] for item in items)
    assert {
        item["category"] for item in items
    } <= set(expression_presets.CATEGORIES)
    assert {
        item["intensity"] for item in items
    } <= set(expression_presets.INTENSITIES)


def test_expression_api_filters_category_intensity_and_keyword(client):
    full = client.get("/api/prompt-agent/expression-presets")
    assert full.status_code == 200
    body = full.json()
    assert body["total"] == 24
    assert body["categories"] == list(expression_presets.CATEGORIES)

    filtered = client.get(
        "/api/prompt-agent/expression-presets",
        params={"keyword": "害羞", "category": "基础情绪", "intensity": "中"},
    )
    assert filtered.status_code == 200
    items = filtered.json()["items"]
    assert [item["id"] for item in items] == ["expression_shy_blush"]

    scoped = client.get(
        "/api/prompt-agent/expression-presets",
        params={"keyword": "closed mouth", "character_scope": "通用"},
    )
    assert scoped.status_code == 200
    assert {item["id"] for item in scoped.json()["items"]} == {
        "expression_soft_smile"
    }


def test_prompt_document_resolves_builtin_expression_reference():
    resolved = prompt_document.resolve_document(
        {
            "mode": "structured",
            "characters": [
                {
                    "id": "hero",
                    "role_id": "girlA",
                    "display_name": "Hero",
                    "gender": "女",
                    "expression": {
                        "preset_refs": [
                            {
                                "preset_id": "expression_soft_smile",
                                "version": 1,
                                "scope": "girlA",
                            }
                        ]
                    },
                }
            ],
        }
    )

    assert resolved["blocked"] is False
    assert "for the first girl (Hero): soft smile" in resolved["prompt"]
    assert "expression_soft_smile" in resolved["used_ids"]
