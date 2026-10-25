"""AI 视频模块：迁移/工作流/接口校验测试。"""
from __future__ import annotations

import json

import database
import video_worker


def _fresh_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "video_test.db")
    with database.get_connection() as conn:
        conn.executescript(database._SCHEMA)


def test_video_tables_migrate_and_crud(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    database.run_migrations()
    version = database.get_connection().execute("PRAGMA user_version").fetchone()[0]
    assert version == database.SCHEMA_VERSION

    script_id = database.insert_video_script(
        "夜晚街道，少女转身回望",
        {"story": "测试", "prompt": "a girl turning around"},
        "qwen3:8b",
        False,
    )
    script = database.get_video_script(script_id)
    assert script["script"]["prompt"] == "a girl turning around"

    record_id = database.insert_video_record(
        "video-job-1",
        script_id,
        "key.png",
        "a girl turning around",
        "worst quality",
        "wan2.1_i2v_480p_14B_fp8_e4m3fn.safetensors",
        ["wan21_general_nsfw_e14_fixed.safetensors"],
        123,
        512,
        512,
        121,
        24,
    )
    row = database.get_video_record(record_id)
    assert row is not None
    assert row["loras"] == ["wan21_general_nsfw_e14_fixed.safetensors"]
    database.update_video_record_result("video-job-1", "done", video_name="video.webm", duration_seconds=10.5)
    assert database.get_video_record(record_id)["video_name"] == "video.webm"
    database.delete_video_record(record_id)
    assert database.get_video_record(record_id) is None


def test_build_workflow_replaces_params(tmp_path, monkeypatch):
    template = tmp_path / "wan_api.json"
    template.write_text(
        json.dumps(
            {
                "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "old.safetensors"}},
                "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["x", 0], "text": "old positive"}},
                "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["x", 0], "text": "old negative"}},
                "4": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
                "5": {"class_type": "WanImageToVideo", "inputs": {"width": 1, "height": 1, "length": 1}},
                "6": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 1, "cfg": 1, "denoise": 1}},
                "7": {"class_type": "SaveWEBM", "inputs": {"filename_prefix": "old", "fps": 1}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(database.config, "VIDEO_WORKFLOW_PATH", template)
    graph = video_worker.build_video_workflow(
        {
            "image_name": "workbench_video/key.png",
            "positive_prompt": "woman walking",
            "negative_prompt": "static",
            "model": "new_model.safetensors",
            "seed": 42,
            "steps": 30,
            "cfg": 6,
            "denoise": 1,
            "frames": 121,
            "width": 512,
            "height": 512,
            "fps": 24,
            "filename_prefix": "video_abc_42",
        }
    )
    assert graph["1"]["inputs"]["unet_name"] == "new_model.safetensors"
    assert graph["2"]["inputs"]["text"] == "woman walking"
    assert graph["3"]["inputs"]["text"] == "static"
    assert graph["4"]["inputs"]["image"] == "workbench_video/key.png"
    assert graph["5"]["inputs"]["length"] == 121
    assert graph["6"]["inputs"]["seed"] == 42
    assert graph["6"]["inputs"]["steps"] == 30
    assert graph["7"]["inputs"]["filename_prefix"] == "video_abc_42"


def _keyframe(tmp_path) -> None:
    target = tmp_path / "key.png"
    target.write_bytes(b"fake-png")


def test_video_generate_validation(client, tmp_path, monkeypatch):
    from routers import video as video_router

    keyframe_dir = tmp_path / "keyframes"
    keyframe_dir.mkdir()
    monkeypatch.setattr(video_router, "VIDEO_KEYFRAME_DIR", keyframe_dir)
    monkeypatch.setattr(video_worker, "VIDEO_KEYFRAME_DIR", keyframe_dir)
    monkeypatch.setattr(video_worker, "VIDEO_OUTPUT_DIR", tmp_path / "videos")
    monkeypatch.setattr(video_worker, "run_video_job", lambda job_id, params: None)
    _keyframe(keyframe_dir)

    response = client.post(
        "/api/video/generate",
        json={
            "prompt": "woman walking",
            "negative_prompt": "static",
            "keyframe_name": "missing.png",
        },
    )
    assert response.status_code == 404

    response = client.post(
        "/api/video/generate",
        json={
            "prompt": "loli walking",
            "negative_prompt": "",
            "keyframe_name": "key.png",
        },
    )
    assert response.status_code == 403

    response = client.post(
        "/api/video/generate",
        json={
            "prompt": "woman walking",
            "negative_prompt": "static",
            "keyframe_name": "key.png",
            "frames": 121,
            "width": 512,
            "height": 512,
            "steps": 20,
            "cfg": 6,
            "denoise": 1,
            "seed": 7,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"

    record = database.get_video_record_by_job(body["job_id"])
    assert record is not None
    assert record["seed"] == 7


def test_system_busy_includes_video_label(client):
    import task_registry

    task_registry.register("video", "video-busy-1")
    try:
        response = client.get("/api/system/busy")
        assert response.status_code == 200
        labels = {item["label"] for item in response.json()["tasks"]}
        assert "AI 视频" in labels
    finally:
        task_registry.finish("video", "video-busy-1", "done")
