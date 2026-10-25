"""共享测试夹具：临时 SQLite DB + 外部服务 mock。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(autouse=True)
def isolate_task_registry():
    """Prevent in-memory jobs from leaking busy state across tests."""
    import task_registry

    with task_registry._LOCK:
        task_registry._REGISTRY.clear()
    yield
    with task_registry._LOCK:
        task_registry._REGISTRY.clear()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """提供不触碰真实数据库、不依赖外部服务的 FastAPI TestClient。"""
    import auto_shutdown
    import app as app_module
    import database
    import services

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test_studio.db")
    monkeypatch.setattr(auto_shutdown, "_executor", lambda: None)
    monkeypatch.setattr(auto_shutdown, "start_watcher", lambda: None)
    monkeypatch.setattr(services, "start_supervisor", lambda: None)
    monkeypatch.setattr(services, "auto_start_services", lambda: None)
    monkeypatch.setattr(services, "is_ollama_up", lambda: True)
    monkeypatch.setattr(services, "is_comfyui_up", lambda: True)

    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as test_client:
        yield test_client
