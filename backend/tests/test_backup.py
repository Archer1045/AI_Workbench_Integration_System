"""数据库备份接口测试。"""
from __future__ import annotations

import config


def test_backup_create_and_list(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BACKUP_ROOT", tmp_path / "backups")
    created = client.post("/api/system/backup")
    assert created.status_code == 200
    payload = created.json()
    assert payload["ok"] is True
    assert payload["backup"]["path"].endswith(".db")

    listed = client.get("/api/system/backups")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["name"].startswith("rider_studio_")
