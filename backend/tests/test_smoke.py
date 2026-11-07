"""核心接口冒烟测试（临时 DB + mock 外部服务）。"""
from __future__ import annotations


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["services"]["ollama"] is True
    assert payload["services"]["comfyui"] is True


def test_data_retention_default(client):
    response = client.get("/api/settings/data-retention")
    assert response.status_code == 200
    assert response.json()["days"] == 0


def test_service_supervision_default(client):
    response = client.get("/api/settings/service-supervision")
    assert response.status_code == 200
    payload = response.json()
    assert set(("auto_start", "auto_restart", "interval_seconds", "max_failures")) <= set(payload)


def test_service_supervision_update_returns_status_shape(client):
    response = client.post(
        "/api/settings/service-supervision",
        json={"auto_start": False, "auto_restart": True, "interval_seconds": 15, "max_failures": 3},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "consecutive" in payload
    assert "restarting" in payload
    assert "ollama" in payload["consecutive"]
    assert "comfyui" in payload["consecutive"]


def test_train_history_empty(client):
    response = client.get("/api/train/history")
    assert response.status_code == 200
    assert response.json()["jobs"] == []


def test_services_status(client):
    response = client.get("/api/services")
    assert response.status_code == 200
    assert response.json() == {"ollama": True, "comfyui": True}
