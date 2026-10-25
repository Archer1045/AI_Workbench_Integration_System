"""Outfit Set preview snapshot and content-hash invalidation tests."""
from __future__ import annotations

import pytest

import preset_asset_pipeline as pipeline
import preset_asset_service as service
import preset_registry


def test_outfit_is_a_preview_asset_kind(client) -> None:
    assert "outfit" in preset_registry.PRESET_KIND_BY_KEY
    assert preset_registry.PRESET_KIND_BY_KEY["outfit"].image_directory == "outfit-presets"
    assert service.target_for("outfit")["output_size"] == (384, 576)
    metadata = client.get("/api/preset-types").json()["items"]
    outfit_metadata = next(item for item in metadata if item["kind"] == "outfit")
    assert outfit_metadata["supports_thumbnail"] is True
    assert outfit_metadata["composition_enabled"] is False
    response = client.get(
        "/api/preset-assets/catalog/query",
        params={"kind": "outfit"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 10
    items = body["items"][0]["items"]
    assert any(
        item["preset_id"] == "outfit_campus_cream"
        for item in items
    )


def test_outfit_snapshot_uses_final_combination_and_four_candidates(client) -> None:
    snapshot = pipeline.build_prompt_snapshot(
        "outfit",
        "outfit_campus_cream",
        {
            "candidate_count": 4,
            "generate_at_output_size": False,
        },
    )
    assert snapshot["preset_type"] == "outfit"
    assert snapshot["candidate_count"] == 4
    assert snapshot["generation_width"] == 768
    assert snapshot["generation_height"] == 1152
    assert snapshot["prompt_layers"]["preset_draw_prompt"]
    assert "school uniform" in snapshot["prompt_positive"].lower()
    assert snapshot["content_hash"]
    assert snapshot["preset_version"] == 1


def test_outfit_candidate_rejects_old_content_hash(client) -> None:
    preset = service.resolve_preset("outfit", "outfit_campus_cream")
    with pytest.raises(service.PresetAssetError, match="content hash"):
        service._assert_current_character_version(
            {
                "preset_type": "outfit",
                "preset_id": "outfit_campus_cream",
                "params": {"content_hash": "old"},
            }
        )
    service._assert_current_character_version(
        {
            "preset_type": "outfit",
            "preset_id": "outfit_campus_cream",
            "params": {"content_hash": preset["content_hash"]},
        }
    )


def test_outfit_preview_api_queues_four_candidates(client, monkeypatch) -> None:
    captured: dict = {}

    def fake_create_job(items, *, idempotency_key=None):
        captured["items"] = items
        captured["idempotency_key"] = idempotency_key
        return {"job_id": "outfit-preview-job", "status": "queued"}

    monkeypatch.setattr(pipeline, "create_job", fake_create_job)
    response = client.post(
        "/api/preset-assets/presets/outfit/outfit_campus_cream/candidates/ai",
        json={"params": {"candidate_count": 4}},
        headers={"Idempotency-Key": "outfit-preview-test"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["job_id"] == "outfit-preview-job"
    assert captured["idempotency_key"] == "outfit-preview-test"
    assert captured["items"] == [
        {
            "preset_type": "outfit",
            "preset_id": "outfit_campus_cream",
            "mode": "ai",
            "params": {"candidate_count": 4},
        }
    ]
