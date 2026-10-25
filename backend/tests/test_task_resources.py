"""统一任务资源租约与活动事件测试。"""
from __future__ import annotations

import pytest

import database
import task_registry
import task_resources


def _init(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "task_resources.db")
    database.init_db()


def test_exclusive_conflict_releases_on_finish(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    task_registry.register("draw", "draw-resource-1", resources=task_resources.for_kind("draw"))
    with pytest.raises(task_resources.ResourceConflictError):
        task_registry.register("train", "train-resource-1", resources=task_resources.for_kind("train"))
    task_registry.finish("draw", "draw-resource-1", "done")
    assert task_resources.list_job_claims("draw-resource-1") == []

    task_registry.register("train", "train-resource-1", resources=task_resources.for_kind("train"))
    task_registry.finish("train", "train-resource-1", "done")


def test_queued_task_claims_only_after_running(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    task_registry.register(
        "preset_asset",
        "preset-resource-1",
        status="queued",
        resources=task_resources.for_kind("preset_asset"),
    )
    assert database.list_active_task_resource_claims() == []

    task_registry.update("preset_asset", "preset-resource-1", status="running")
    claims = database.list_active_task_resource_claims()
    assert {item["resource_key"] for item in claims} == {"gpu", "comfyui"}

    task_registry.finish("preset_asset", "preset-resource-1", "done")
    assert database.list_active_task_resource_claims() == []


def test_shared_resource_allows_peers_but_blocks_exclusive(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    task_resources.claim_resources("shared-1", "game_assistant_plan", [{"key": "ollama", "mode": "shared"}])
    task_resources.claim_resources("shared-2", "game_assistant_plan", [{"key": "ollama", "mode": "shared"}])
    with pytest.raises(task_resources.ResourceConflictError):
        task_resources.claim_resources("exclusive-1", "game_assistant_vlm", [{"key": "ollama", "mode": "exclusive"}])
    task_resources.release_resources("shared-1")
    task_resources.release_resources("shared-2")


def test_conflict_message_names_the_holder_and_remaining_ttl(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    task_resources.claim_resources(
        "holder-run", "game_assistant_run", task_resources.for_kind("game_assistant_run")
    )
    with pytest.raises(task_resources.ResourceConflictError) as info:
        task_resources.claim_resources(
            "new-run", "game_assistant_run", task_resources.for_kind("game_assistant_run")
        )
    message = task_resources.conflict_message(info.value)
    assert "holder-run" in message
    assert "秒后过期" in message
    task_resources.release_resources("holder-run")


def test_restore_releases_running_claims(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    task_registry.register("draw", "draw-restore-1", resources=task_resources.for_kind("draw"))
    task_registry.restore_interrupted()
    assert task_registry.get("draw", "draw-restore-1")["status"] == "interrupted"
    assert database.list_active_task_resource_claims() == []


def test_activity_events_include_task_and_resource_lifecycle(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    task_registry.register("draw", "draw-events-1", resources=task_resources.for_kind("draw"))
    task_registry.finish("draw", "draw-events-1", "done")
    events = database.list_activity_events(job_id="draw-events-1", limit=50)
    event_types = {item["event_type"] for item in events}
    assert {"task.registered", "resource.acquired", "task.status_changed", "resource.released"} <= event_types


def test_resource_and_activity_api(client):
    task_registry.register("draw", "draw-api-resource-1", resources=task_resources.for_kind("draw"))
    try:
        resources = client.get("/api/system/resources")
        assert resources.status_code == 200
        payload = resources.json()
        gpu = next(item for item in payload["resources"] if item["key"] == "gpu")
        assert gpu["busy"] is True
        assert gpu["claims"][0]["job_id"] == "draw-api-resource-1"

        busy = client.get("/api/system/busy")
        assert busy.status_code == 200
        assert busy.json()["busy"] is True

        events = client.get("/api/system/activity-events", params={"job_id": "draw-api-resource-1"})
        assert events.status_code == 200
        assert any(item["event_type"] == "resource.acquired" for item in events.json()["items"])
    finally:
        task_registry.finish("draw", "draw-api-resource-1", "done")


def test_expired_claim_can_be_taken_over(tmp_path, monkeypatch):
    _init(tmp_path, monkeypatch)
    task_resources.claim_resources("expired-1", "draw", [{"key": "gpu", "mode": "exclusive"}], ttl_seconds=1)
    with database.get_connection() as conn:
        conn.execute("UPDATE task_resource_claims SET expires_at = ? WHERE job_id = ?", (0, "expired-1"))
    task_resources.claim_resources("takeover-1", "train", [{"key": "gpu", "mode": "exclusive"}], ttl_seconds=60)
    active = database.list_active_task_resource_claims()
    assert any(item["job_id"] == "takeover-1" for item in active)
    assert not any(item["job_id"] == "expired-1" for item in active)
    task_resources.release_resources("takeover-1")
