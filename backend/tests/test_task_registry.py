"""统一任务注册表测试。"""
from __future__ import annotations

import database
import task_registry


def test_register_update_finish(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "registry_test.db")
    database.init_db()
    task_registry.register("draw", "draw-1", total=3)
    running = task_registry.running_tasks()
    assert any(task["type"] == "draw" and task["job_id"] == "draw-1" for task in running)
    task_registry.update("draw", "draw-1", done=2)
    job = task_registry.get("draw", "draw-1")
    assert job["done"] == 2
    task_registry.finish("draw", "draw-1", "done")
    assert task_registry.get("draw", "draw-1")["status"] == "done"
    assert not any(task["job_id"] == "draw-1" for task in task_registry.running_tasks())


def test_restore_interrupted_marks_running(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "registry_restore_test.db")
    database.init_db()
    task_registry.register("caption", "cap-1")
    task_registry.restore_interrupted()
    job = task_registry.get("caption", "cap-1")
    assert job["status"] == "interrupted"
