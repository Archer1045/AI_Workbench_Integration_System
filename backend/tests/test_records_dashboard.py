from __future__ import annotations

import preset_asset_service


def _preset_summary() -> dict:
    return {
        "total": 10,
        "formal_count": 7,
        "versioned_count": 6,
        "candidate_only_count": 2,
        "missing_count": 1,
        "formal_percent": 70.0,
        "with_candidates_percent": 90.0,
        "candidate_count": 3,
        "candidate_status_counts": {"ready": 2, "failed": 1},
        "ready_count": 2,
        "running_count": 0,
        "failed_count": 1,
        "adopted_count": 4,
        "rolled_back_count": 1,
        "discarded_count": 2,
        "template_versions": {"thumbnail_template_v25": 3},
        "template_missing_count": 0,
        "preset_version_counts": {"known": 2, "missing": 1, "malformed": 0},
        "version_missing_count": 1,
        "by_kind": [
            {
                "kind": "pose",
                "label": "体位",
                "total": 10,
                "formal_count": 7,
                "versioned_count": 6,
                "candidate_only_count": 2,
                "missing_count": 1,
                "formal_percent": 70.0,
                "with_candidates_percent": 90.0,
            }
        ],
    }


def test_dashboard_v3_aggregates_draw_and_preset_assets(client, monkeypatch):
    import database

    monkeypatch.setattr(preset_asset_service, "dashboard_summary", _preset_summary)
    record_id = database.insert_draw_start(
        prompt="test prompt",
        prompt_translation="",
        negative_prompt="",
        negative_translation="",
        width=1024,
        height=1024,
        steps=28,
        cfg=7.0,
        model="model-a",
        lora_anima_turbo=False,
        lora_high_contrast=False,
        loras=["style-a.safetensors", "style-b.safetensors"],
    )
    database.finish_draw(record_id, 12.5, "a.png", "/a.png", 42, "success")

    response = client.get("/api/records/dashboard/v3")
    assert response.status_code == 200
    body = response.json()
    assert body["draw"]["total"] == 1
    assert body["draw"]["lora_counts"] == {"style-a": 1, "style-b": 1}
    assert body["overview"]["preset_assets"]["formal_count"] == 7
    assert body["preset_assets"]["version_missing_count"] == 1


def test_module_summary_v2_remains_available(client):
    response = client.get("/api/records/module-summary/v2")
    assert response.status_code == 200
    assert "train" in response.json()


def test_preset_dashboard_summary_separates_coverage_and_versions(monkeypatch):
    import database

    monkeypatch.setattr(
        preset_asset_service,
        "_build_catalog_items_by_kind",
        lambda _restriction: {
            "pose": [
                {
                    "has_image": True,
                    "active_version": {"version": 1},
                    "ready_count": 0,
                    "candidate_status_counts": {"ready": 0},
                },
                {
                    "has_image": False,
                    "active_version": None,
                    "ready_count": 1,
                    "candidate_status_counts": {"ready": 1},
                },
                {
                    "has_image": False,
                    "active_version": None,
                    "ready_count": 0,
                    "candidate_status_counts": {},
                },
            ]
        },
    )
    monkeypatch.setattr(
        database,
        "list_preset_asset_candidate_version_rows",
        lambda: [
            {
                "params_json": '{"preset_version": 1}',
                "template_version": "thumbnail_template_v25",
            },
            {"params_json": "{}", "template_version": ""},
            {"params_json": "{broken", "template_version": "thumbnail_template_v24"},
        ],
    )
    monkeypatch.setattr(
        database,
        "summarize_preset_asset_audit_events",
        lambda: {"candidate_adopted": 2, "version_rolled_back": 1},
    )

    result = preset_asset_service.dashboard_summary()
    assert result["total"] == 3
    assert result["formal_count"] == 1
    assert result["candidate_only_count"] == 1
    assert result["missing_count"] == 1
    assert result["preset_version_counts"] == {
        "known": 1,
        "missing": 1,
        "malformed": 1,
    }
    assert result["template_missing_count"] == 1
    assert result["adopted_count"] == 2
    assert result["rolled_back_count"] == 1
