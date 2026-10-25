"""Auto-shutdown state machine and API tests (executor always mocked)."""
from __future__ import annotations

import database
import task_state
import auto_shutdown


def _reset(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "auto_shutdown_test.db")
    monkeypatch.setattr(task_state, "running_tasks", lambda: [])
    database.init_db()
    auto_shutdown.update_settings({"enabled": False, "delay_seconds": 60})
    auto_shutdown.cancel()


def test_default_disabled(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    payload = auto_shutdown.status()
    assert payload["enabled"] is False
    assert payload["phase"] == "disabled"


def test_done_starts_pending_countdown(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    auto_shutdown.update_settings({"enabled": True, "delay_seconds": 30})
    auto_shutdown.notify_task_finished("draw", "draw-done-1", "done")
    payload = auto_shutdown.status()
    assert payload["phase"] == "pending"
    assert payload["task_label"] == "AI 绘画"
    assert payload["remaining_seconds"] is not None
    assert payload["remaining_seconds"] <= 30


def test_non_done_does_not_start_pending(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    auto_shutdown.update_settings({"enabled": True, "delay_seconds": 30})
    auto_shutdown.notify_task_finished("draw", "draw-error-1", "error")
    assert auto_shutdown.status()["phase"] == "idle"


def test_new_task_cancels_pending_and_next_done_rearms(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    auto_shutdown.update_settings({"enabled": True, "delay_seconds": 30})
    auto_shutdown.notify_task_finished("draw", "draw-1", "done")
    assert auto_shutdown.status()["phase"] == "pending"
    auto_shutdown.notify_task_started("train", "train-2")
    assert auto_shutdown.status()["phase"] == "idle"
    auto_shutdown.notify_task_finished("train", "train-2", "done")
    assert auto_shutdown.status()["phase"] == "pending"


def test_cancel_clears_pending(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    auto_shutdown.update_settings({"enabled": True, "delay_seconds": 30})
    auto_shutdown.notify_task_finished("draw", "draw-cancel-1", "done")
    assert auto_shutdown.status()["phase"] == "pending"
    auto_shutdown.cancel()
    payload = auto_shutdown.status()
    assert payload["phase"] == "idle"
    assert payload["remaining_seconds"] is None


def test_tick_executes_after_deadline(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(auto_shutdown, "_executor", lambda: calls.append("shutdown"))
    auto_shutdown.update_settings({"enabled": True, "delay_seconds": 30})
    auto_shutdown.notify_task_finished("merge", "merge-exec-1", "done")
    auto_shutdown._state["deadline_at"] = 0
    auto_shutdown._tick()
    payload = auto_shutdown.status()
    assert calls == ["shutdown"]
    assert payload["phase"] == "executed"


def test_settings_api_default_and_update(client):
    response = client.get("/api/settings/auto-shutdown")
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    try:
        updated = client.post(
            "/api/settings/auto-shutdown",
            json={"enabled": True, "delay_seconds": 30},
        )
        assert updated.status_code == 200
        assert updated.json()["enabled"] is True
        assert updated.json()["delay_seconds"] == 30
        cancelled = client.post("/api/system/auto-shutdown/cancel")
        assert cancelled.status_code == 200
    finally:
        auto_shutdown.update_settings({"enabled": False, "delay_seconds": 60})
