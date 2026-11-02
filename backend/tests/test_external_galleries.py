"""External pose/costume gallery binding, catalogue and path-safety contracts."""
from __future__ import annotations

import io
import json

from PIL import Image

import config
import external_galleries


def _png_bytes(size=(96, 128), color=(20, 40, 60)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _patch_gallery_storage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        config,
        "EXTERNAL_GALLERY_CONFIG_PATH",
        tmp_path / "config" / "external_galleries.json",
    )
    monkeypatch.setattr(
        config,
        "EXTERNAL_GALLERY_CACHE_DIR",
        tmp_path / "cache",
    )
    monkeypatch.setattr(
        config,
        "EXTERNAL_GALLERY_ASSET_ROOT",
        tmp_path / "managed-assets",
    )
    monkeypatch.setattr(config, "EXTERNAL_GALLERY_MAX_ITEMS", 100)
    external_galleries.invalidate()


def _bind(client, kind: str, root) -> dict:
    response = client.put(
        f"/api/external-galleries/settings/{kind}",
        json={
            "directory": str(root),
            "confirmed_local_access": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["settings"]


def test_manifest_catalogue_uses_relative_urls_and_caches_thumbnails(
    client, tmp_path, monkeypatch
) -> None:
    _patch_gallery_storage(tmp_path, monkeypatch)
    root = tmp_path / "pose-library"
    (root / "data").mkdir(parents=True)
    (root / "images").mkdir()
    (root / "images" / "pose-01.png").write_bytes(_png_bytes())
    (root / "data" / "pose-zh.json").write_text(
        json.dumps(
            [
                {
                    "id": "pose-01",
                    "姿势名称": "侧身站姿",
                    "分类": "站姿",
                    "体系": "基础",
                    "角度": "侧面",
                    "标签": ["全身", "自然"],
                    "体位ID": "lying_back",
                    "原图": "images/pose-01.png",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    settings = _bind(client, "pose", root)
    assert settings["pose"]["configured"] is True
    assert settings["pose"]["available"] is True
    assert settings["pose"]["import_mode"] == "managed"
    assert settings["pose"]["item_count"] == 1
    assert settings["costume"]["configured"] is False

    response = client.get("/api/external-galleries/pose/catalogue")
    assert response.status_code == 200
    catalogue = response.json()
    assert catalogue["mode"] == "database"
    assert catalogue["manifest"] == "data/pose-zh.json"
    assert catalogue["count"] == 1
    item = catalogue["items"][0]
    assert item["name"] == "侧身站姿"
    assert item["path"] == "images/pose-01.png"
    assert item["asset_id"] > 0
    assert item["pose_preset_id"] == "lying_back"
    assert item["pose_preset_label"] == "仰躺"
    assert item["image_url"].startswith("/api/external-galleries/pose/assets/")
    assert str(root) not in json.dumps(catalogue, ensure_ascii=False)
    assert list((tmp_path / "managed-assets" / "pose").rglob("*.png"))

    original = client.get(item["image_url"])
    assert original.status_code == 200
    assert original.headers["content-type"].startswith("image/png")
    thumbnail = client.get(item["thumbnail_url"])
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"].startswith("image/jpeg")
    assert list(
        (tmp_path / "cache" / "thumbnails").glob("*.jpg")
    )


def test_pose_and_costume_bindings_are_independent(
    client, tmp_path, monkeypatch
) -> None:
    _patch_gallery_storage(tmp_path, monkeypatch)
    pose_root = tmp_path / "pose"
    costume_root = tmp_path / "costume"
    pose_root.mkdir()
    costume_root.mkdir()
    (pose_root / "pose.png").write_bytes(_png_bytes())
    (costume_root / "costume.png").write_bytes(_png_bytes())

    _bind(client, "pose", pose_root)
    settings = _bind(client, "costume", costume_root)

    assert settings["pose"]["directory"] == str(pose_root.resolve())
    assert settings["costume"]["directory"] == str(costume_root.resolve())
    pose_items = client.get(
        "/api/external-galleries/pose/catalogue"
    ).json()["items"]
    costume_items = client.get(
        "/api/external-galleries/costume/catalogue"
    ).json()["items"]
    assert [item["path"] for item in pose_items] == ["pose.png"]
    assert [item["path"] for item in costume_items] == ["costume.png"]

    unbound = client.delete("/api/external-galleries/settings/pose")
    assert unbound.status_code == 200
    assert unbound.json()["settings"]["pose"]["configured"] is False
    assert unbound.json()["settings"]["costume"]["configured"] is True


def test_broken_manifest_falls_back_to_folder_scan(
    client, tmp_path, monkeypatch
) -> None:
    _patch_gallery_storage(tmp_path, monkeypatch)
    root = tmp_path / "broken-manifest"
    (root / "data").mkdir(parents=True)
    (root / "nested").mkdir()
    (root / "data" / "pose-zh.json").write_text("{broken", encoding="utf-8")
    (root / "nested" / "image-01.png").write_bytes(_png_bytes())

    _bind(client, "pose", root)
    response = client.get("/api/external-galleries/pose/catalogue")

    assert response.status_code == 200
    catalogue = response.json()
    assert catalogue["mode"] == "database"
    assert catalogue["warning"].startswith("清单不可用")
    assert catalogue["items"][0]["category"] == "nested"


def test_binding_and_image_paths_reject_unsafe_inputs(
    client, tmp_path, monkeypatch
) -> None:
    _patch_gallery_storage(tmp_path, monkeypatch)
    root = tmp_path / "safe"
    root.mkdir()
    (root / "pose.png").write_bytes(_png_bytes())
    (root / "note.txt").write_text("not an image", encoding="utf-8")

    relative = client.put(
        "/api/external-galleries/settings/pose",
        json={
            "directory": "relative-folder",
            "confirmed_local_access": True,
        },
    )
    assert relative.status_code == 400
    assert "绝对路径" in relative.json()["detail"]

    unconfirmed = client.put(
        "/api/external-galleries/settings/pose",
        json={
            "directory": str(root),
            "confirmed_local_access": False,
        },
    )
    assert unconfirmed.status_code == 400
    assert "使用权" in unconfirmed.json()["detail"]

    _bind(client, "pose", root)
    for unsafe_path in ("../outside.png", str(root / "pose.png"), "note.txt"):
        response = client.get(
            "/api/external-galleries/pose/image",
            params={"path": unsafe_path},
        )
        assert response.status_code == 404, unsafe_path


def test_managed_gallery_accepts_empty_source_and_can_sync_later(
    client, tmp_path, monkeypatch
) -> None:
    _patch_gallery_storage(tmp_path, monkeypatch)
    root = tmp_path / "empty-pose"
    root.mkdir()

    settings = _bind(client, "pose", root)
    assert settings["pose"]["configured"] is True
    assert settings["pose"]["status"] == "empty"
    catalogue = client.get("/api/external-galleries/pose/catalogue").json()
    assert catalogue["mode"] == "database"
    assert catalogue["count"] == 0

    (root / "added.png").write_bytes(_png_bytes())
    synced = client.post("/api/external-galleries/pose/sync")
    assert synced.status_code == 200, synced.text
    assert synced.json()["count"] == 1
    assert synced.json()["items"][0]["name"] == "added"


def test_managed_gallery_favorite_and_recent_use_persist_in_database(
    client, tmp_path, monkeypatch
) -> None:
    _patch_gallery_storage(tmp_path, monkeypatch)
    root = tmp_path / "pose-activity"
    root.mkdir()
    (root / "pose.png").write_bytes(_png_bytes())
    _bind(client, "pose", root)
    item = client.get("/api/external-galleries/pose/catalogue").json()["items"][0]
    asset_id = item["asset_id"]

    favorite = client.post(
        f"/api/external-galleries/pose/assets/{asset_id}/favorite"
    )
    assert favorite.status_code == 200
    assert favorite.json()["favorite"] is True
    used = client.post(
        f"/api/external-galleries/pose/assets/{asset_id}/use"
    )
    assert used.status_code == 200
    assert used.json()["use_count"] == 1

    refreshed = client.get("/api/external-galleries/pose/catalogue").json()["items"][0]
    assert refreshed["favorite"] is True
    assert refreshed["use_count"] == 1
    assert refreshed["last_used_at"]

    linked = client.put(
        f"/api/external-galleries/pose/assets/{asset_id}/pose-link",
        json={"pose_preset_id": "kneeling"},
    )
    assert linked.status_code == 200
    assert linked.json()["pose_preset_id"] == "kneeling"
    linked_item = client.get(
        "/api/external-galleries/pose/catalogue"
    ).json()["items"][0]
    assert linked_item["pose_preset_id"] == "kneeling"
    assert linked_item["pose_preset_label"]

    invalid = client.put(
        f"/api/external-galleries/pose/assets/{asset_id}/pose-link",
        json={"pose_preset_id": "missing-pose-preset"},
    )
    assert invalid.status_code == 400
    assert "不存在" in invalid.json()["detail"]
