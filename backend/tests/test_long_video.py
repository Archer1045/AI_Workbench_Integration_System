"""Checkpointed long-video orchestration tests without calling a GPU."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

import config
import database
import long_video
import storyboard_tools
import task_registry
import task_resources
import video_worker


def _make_video(path: Path, color: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(
        [
            str(storyboard_tools.ffmpeg_path()),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=64x64:r=10:d=0.6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    return path


def test_long_video_preserves_ready_segment_and_resumes_failed_segment(
    client, tmp_path, monkeypatch
) -> None:
    from routers import video as video_router

    keyframe_dir = tmp_path / "keyframes"
    keyframe_dir.mkdir()
    (keyframe_dir / "key.png").write_bytes(b"fake-keyframe")
    monkeypatch.setattr(video_router, "VIDEO_KEYFRAME_DIR", keyframe_dir)
    monkeypatch.setattr(video_worker, "VIDEO_KEYFRAME_DIR", keyframe_dir)
    monkeypatch.setattr(config, "LONG_VIDEO_ROOT", tmp_path / "long-jobs")
    monkeypatch.setattr(config, "VIDEO_OUTPUT_DIR", tmp_path / "videos")
    monkeypatch.setattr(video_worker, "VIDEO_OUTPUT_DIR", tmp_path / "videos")

    calls: list[str] = []
    failed_once = {"second": False}

    def fake_generate(job_id, params, **kwargs):
        prompt = str(params["positive_prompt"])
        calls.append(prompt)
        if prompt == "second segment" and not failed_once["second"]:
            failed_once["second"] = True
            raise RuntimeError("synthetic second-segment failure")
        output = (
            Path(params["output_dir"])
            / f"{params['filename_prefix']}.mp4"
        )
        return _make_video(output, "red" if prompt == "first segment" else "blue")

    monkeypatch.setattr(video_worker, "generate_video_output", fake_generate)
    payload = {
        "keyframe_name": "key.png",
        "prompts": ["first segment", "second segment"],
        "negative_prompt": "static",
        "frames": 33,
        "fps": 24,
        "width": 512,
        "height": 512,
        "steps": 1,
        "cfg": 1,
        "denoise": 1,
        "seed": 42,
    }
    started = client.post("/api/video/long/jobs", json=payload)
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]

    state = {}
    for _ in range(200):
        state = long_video.load_state(job_id)
        if state["status"] == "error":
            break
        time.sleep(0.05)
    assert state["status"] == "error"
    assert state["segments"][0]["status"] == "ready"
    assert state["segments"][0]["video_name"]
    assert state["segments"][1]["status"] == "failed"
    assert "synthetic second-segment failure" in state["segments"][1]["error"]
    for _ in range(50):
        if task_resources.list_job_claims(job_id, active_only=True) == []:
            break
        time.sleep(0.02)
    assert task_resources.list_job_claims(job_id, active_only=True) == []
    first_video = (
        tmp_path
        / "long-jobs"
        / job_id
        / "segments"
        / state["segments"][0]["video_name"]
    )
    assert first_video.is_file()

    resumed = client.post(
        f"/api/video/long/jobs/{job_id}/resume",
        json={"from_segment": 2},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["from_segment"] == 2

    for _ in range(300):
        state = long_video.load_state(job_id)
        if state["status"] == "done":
            break
        time.sleep(0.05)
    assert state["status"] == "done", state
    assert [segment["status"] for segment in state["segments"]] == [
        "ready",
        "ready",
    ]
    assert state["segments"][0]["attempts"] == 1
    assert state["segments"][1]["attempts"] == 2
    assert calls == ["first segment", "second segment", "second segment"]
    assert state["final_video_name"]
    final_video = tmp_path / "videos" / state["final_video_name"]
    assert final_video.is_file()
    record = database.get_video_record_by_job(job_id)
    assert record and record["status"] == "done"
    assert record["video_name"] == state["final_video_name"]
    for _ in range(50):
        if task_resources.list_job_claims(job_id, active_only=True) == []:
            break
        time.sleep(0.02)
    assert task_resources.list_job_claims(job_id, active_only=True) == []


def test_long_video_rejects_excessive_total_frames(client, tmp_path, monkeypatch) -> None:
    from routers import video as video_router

    keyframe_dir = tmp_path / "keyframes"
    keyframe_dir.mkdir()
    (keyframe_dir / "key.png").write_bytes(b"fake-keyframe")
    monkeypatch.setattr(video_router, "VIDEO_KEYFRAME_DIR", keyframe_dir)
    monkeypatch.setattr(config, "LONG_VIDEO_MAX_TOTAL_FRAMES", 40)
    response = client.post(
        "/api/video/long/jobs",
        json={
            "keyframe_name": "key.png",
            "prompts": ["first", "second"],
            "frames": 33,
            "width": 512,
            "height": 512,
            "steps": 1,
            "cfg": 1,
            "denoise": 1,
        },
    )
    assert response.status_code == 400
    assert "总帧数" in response.json()["detail"]


def test_long_video_resumes_after_interrupted_task(
    client, tmp_path, monkeypatch
) -> None:
    from routers import video as video_router

    keyframe_dir = tmp_path / "keyframes"
    keyframe_dir.mkdir()
    (keyframe_dir / "key.png").write_bytes(b"fake-keyframe")
    monkeypatch.setattr(video_router, "VIDEO_KEYFRAME_DIR", keyframe_dir)
    monkeypatch.setattr(video_worker, "VIDEO_KEYFRAME_DIR", keyframe_dir)
    monkeypatch.setattr(config, "LONG_VIDEO_ROOT", tmp_path / "long-jobs")
    monkeypatch.setattr(config, "VIDEO_OUTPUT_DIR", tmp_path / "videos")
    monkeypatch.setattr(video_worker, "VIDEO_OUTPUT_DIR", tmp_path / "videos")

    job_id = "long-interrupted"
    params = {
        "keyframe_name": "key.png",
        "prompts": ["completed segment", "pending segment"],
        "segment_seeds": [100, 101],
        "negative_prompt": "static",
        "frames": 33,
        "fps": 24,
        "width": 512,
        "height": 512,
        "steps": 1,
        "cfg": 1,
        "denoise": 1,
        "lora_strength": 1,
        "timeout_seconds": 30,
        "use_lora": True,
    }
    state = long_video.create_state(job_id, params)
    first_name = "completed.mp4"
    _make_video(
        tmp_path / "long-jobs" / job_id / "segments" / first_name,
        "red",
    )
    state["segments"][0].update(
        {"status": "ready", "video_name": first_name, "attempts": 1}
    )
    state["segments"][1].update({"status": "running", "attempts": 1})
    long_video._write_state(state)
    database.insert_video_record(
        job_id,
        None,
        "key.png",
        "completed segment | pending segment",
        "static",
        config.VIDEO_MODEL,
        [config.VIDEO_LORA],
        100,
        512,
        512,
        66,
        24,
    )
    task_registry.register(
        "video_long",
        job_id,
        payload=params,
        total=2,
        resources=task_resources.for_kind("video_long"),
    )
    task_registry.finish("video_long", job_id, "interrupted", "synthetic restart")

    calls: list[str] = []

    def fake_generate(job_id, params, **kwargs):
        calls.append(str(params["positive_prompt"]))
        output = Path(params["output_dir"]) / f"{params['filename_prefix']}.mp4"
        return _make_video(output, "blue")

    monkeypatch.setattr(video_worker, "generate_video_output", fake_generate)
    resumed = client.post(f"/api/video/long/jobs/{job_id}/resume")
    assert resumed.status_code == 200, resumed.text
    for _ in range(300):
        state = long_video.load_state(job_id)
        if state["status"] == "done":
            break
        time.sleep(0.05)
    assert state["status"] == "done"
    assert calls == ["pending segment"]
    assert state["segments"][0]["video_name"] == first_name
    assert state["segments"][1]["attempts"] == 2
    for _ in range(50):
        if task_resources.list_job_claims(job_id, active_only=True) == []:
            break
        time.sleep(0.02)
    assert task_resources.list_job_claims(job_id, active_only=True) == []
