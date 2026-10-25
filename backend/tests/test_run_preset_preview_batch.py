import json
from pathlib import Path

from tools import run_preset_preview_batch


def test_partial_batch_resumes_only_unsubmitted_presets(tmp_path, monkeypatch) -> None:
    manifest_path = tmp_path / "batch.json"
    items = [
        {
            "preset_type": "clothing",
            "preset_id": f"preset_{index:03d}",
            "label": f"Preset {index}",
        }
        for index in range(120)
    ]
    manifest_path.write_text(
        json.dumps(
            {
                "batch_id": "resume-test",
                "scheduled_for": "2026-10-22T09:00:00+08:00",
                "params": {"candidate_count": 4},
                "items": items,
            }
        ),
        encoding="utf-8",
    )
    processed = [
        f"clothing:preset_{index:03d}" for index in range(100)
    ]
    state_path = run_preset_preview_batch._state_path(manifest_path)
    state_path.write_text(
        json.dumps(
            {
                "batch_id": "resume-test",
                "manifest": str(manifest_path),
                "status": "running",
                "jobs": [
                    {
                        "chunk": 0,
                        "job_id": "existing-a",
                        "preset_ids": processed[:50],
                    },
                    {
                        "chunk": 1,
                        "job_id": "existing-b",
                        "preset_ids": processed[50:],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        run_preset_preview_batch,
        "_catalog_state",
        lambda: {
            ("clothing", f"preset_{index:03d}"): {
                "has_image": False,
                "ready_count": 0,
            }
            for index in range(120)
        },
    )
    submitted = []

    def fake_api(method, path, *, payload=None, headers=None):
        submitted.append({"payload": payload, "headers": headers})
        return {"job_id": "new-job"}

    monkeypatch.setattr(run_preset_preview_batch, "_api", fake_api)
    result = run_preset_preview_batch.submit(manifest_path)

    assert result["status"] == "submitted"
    assert len(result["jobs"]) == 3
    assert len(submitted) == 1
    assert len(submitted[0]["payload"]["items"]) == 20
    assert result["resume_eligible_items"] == 20
    assert result["jobs"][-1]["chunk"] == 2
