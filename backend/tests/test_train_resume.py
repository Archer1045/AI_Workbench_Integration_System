from __future__ import annotations

import json
import os
import time
from pathlib import Path

from routers import train as train_router


def test_resume_command_replaces_old_resume_and_worker_flags(tmp_path: Path) -> None:
    state = tmp_path / "run-state"
    cmd = [
        "accelerate.exe",
        "launch",
        "train.py",
        "--resume",
        "old-state",
        "--max_data_loader_n_workers",
        "2",
        "--persistent_data_loader_workers",
        "--max_train_epochs",
        "5",
    ]
    result = train_router._resume_command(cmd, state)
    assert result[-4:] == ["--resume", str(state), "--max_data_loader_n_workers", "0"]
    assert result.count("--resume") == 1
    assert "--persistent_data_loader_workers" not in result
    assert result[-5] == "5"


def test_latest_resume_state_prefers_highest_step(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(train_router, "OUTPUT_DIR", tmp_path)
    for name, step in (("demo-000001-state", 1020), ("demo-000002-state", 2040)):
        state_dir = tmp_path / name
        state_dir.mkdir()
        (state_dir / "train_state.json").write_text(
            json.dumps({"current_epoch": step // 1020, "current_step": step}),
            encoding="utf-8",
        )
        (state_dir / "model.safetensors").write_bytes(b"model")
        (state_dir / "optimizer.bin").write_bytes(b"optimizer")
    (tmp_path / "incomplete-state").mkdir()
    (tmp_path / "incomplete-state" / "train_state.json").write_text(
        json.dumps({"current_step": 9999}), encoding="utf-8"
    )

    assert train_router._latest_resume_state("demo") == tmp_path / "demo-000002-state"
    assert train_router._latest_resume_state("missing") is None


def test_state_step_reads_current_step(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "train_state.json").write_text(
        json.dumps({"current_epoch": 3, "current_step": 3060}), encoding="utf-8"
    )
    assert train_router._state_step(state_dir) == 3060


def test_latest_resume_state_prefers_higher_epoch_when_step_resets(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(train_router, "OUTPUT_DIR", tmp_path)
    states = {
        "demo-000003-state": {"current_epoch": 3, "current_step": 3060},
        "demo-000004-state": {"current_epoch": 4, "current_step": 1020},
    }
    for name, progress in states.items():
        state_dir = tmp_path / name
        state_dir.mkdir()
        (state_dir / "train_state.json").write_text(json.dumps(progress), encoding="utf-8")
        (state_dir / "model.safetensors").write_bytes(b"model")
        (state_dir / "optimizer.bin").write_bytes(b"optimizer")

    # kohya 续训后 current_step 会从 0 重新计数，不能只看步数。
    assert train_router._latest_resume_state("demo") == tmp_path / "demo-000004-state"


class _RunningProc:
    pid = 123

    def poll(self):
        return None

    def kill(self):
        return None


def test_check_train_stall_marks_and_recovers(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "train.log"
    log_path.write_text("progress", encoding="utf-8")
    old = time.time() - 700
    os.utime(log_path, (old, old))
    monkeypatch.setattr(train_router, "TRAIN_STALL_SECONDS", 300)
    monkeypatch.setattr(train_router, "TRAIN_STALL_ABORT_SECONDS", 0)
    monkeypatch.setattr(train_router.database, "save_train_job", lambda job: None)
    job = {
        "job_id": "watch-job",
        "status": "running",
        "log_path": str(log_path),
        "process": _RunningProc(),
    }
    train_router.TRAIN_JOBS["watch-job"] = job
    try:
        assert train_router._check_train_stall("watch-job") is True
        assert job["stalled"] is True
        assert "11 分钟" in job["stall_reason"]

        log_path.write_text("progress again", encoding="utf-8")
        assert train_router._check_train_stall("watch-job") is False
        assert job["stalled"] is False
        assert job["stall_reason"] is None
    finally:
        train_router.TRAIN_JOBS.pop("watch-job", None)


def test_check_train_stall_auto_aborts_when_configured(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "train.log"
    log_path.write_text("progress", encoding="utf-8")
    old = time.time() - 700
    os.utime(log_path, (old, old))
    monkeypatch.setattr(train_router, "TRAIN_STALL_SECONDS", 300)
    monkeypatch.setattr(train_router, "TRAIN_STALL_ABORT_SECONDS", 600)
    monkeypatch.setattr(train_router.database, "save_train_job", lambda job: None)
    monkeypatch.setattr(train_router.task_registry, "finish", lambda *args, **kwargs: None)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        train_router.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command),
    )
    job = {
        "job_id": "abort-job",
        "status": "running",
        "log_path": str(log_path),
        "process": _RunningProc(),
    }
    train_router.TRAIN_JOBS["abort-job"] = job
    try:
        assert train_router._check_train_stall("abort-job") is True
        assert job["status"] == "error"
        assert job["registry_finished"] is True
        assert "已自动停止" in job["error"]
        assert calls and calls[0][:3] == ["taskkill", "/PID", "123"]
    finally:
        train_router.TRAIN_JOBS.pop("abort-job", None)


def _make_finished_job(tmp_path: Path, monkeypatch, job_id: str, output_name: str = "demo") -> dict:
    output_dir = tmp_path / "output"
    log_dir = tmp_path / "logs"
    output_dir.mkdir(exist_ok=True)
    log_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(train_router, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(train_router, "LOG_DIR", log_dir)
    monkeypatch.setattr(train_router.database, "save_train_job", lambda job: None)
    state_dir = output_dir / f"{output_name}-000003-state"
    state_dir.mkdir()
    (state_dir / "train_state.json").write_text(
        json.dumps({"current_epoch": 3, "current_step": 3060}), encoding="utf-8"
    )
    (state_dir / "model.safetensors").write_bytes(b"model")
    (state_dir / "optimizer.bin").write_bytes(b"optimizer")
    return {
        "job_id": job_id,
        "output_name": output_name,
        "status": "error",
        "error": "训练退出码 1",
        "log_path": str(log_dir / f"train_{job_id}.log"),
    }


def test_old_job_without_sidecar_is_not_resumable(tmp_path: Path, monkeypatch) -> None:
    job = _make_finished_job(tmp_path, monkeypatch, "legacy-job")

    public = train_router._public_train_job(job)

    assert public["resume_state"].endswith("demo-000003-state")
    assert public["resume_available"] is False


def test_job_with_sidecar_and_state_is_resumable(tmp_path: Path, monkeypatch) -> None:
    job = _make_finished_job(tmp_path, monkeypatch, "new-job")
    train_router._write_train_sidecar(
        "new-job",
        cmd=["accelerate.exe", "launch", "train.py"],
        output_name="demo",
        auto_convert=False,
        cwd=str(tmp_path),
    )

    public = train_router._public_train_job(job)

    assert public["resume_available"] is True
    assert public["resume_state"].endswith("demo-000003-state")


def test_public_job_adds_resume_step_offset(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "output"
    log_dir = tmp_path / "logs"
    output_dir.mkdir()
    log_dir.mkdir()
    monkeypatch.setattr(train_router, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(train_router, "LOG_DIR", log_dir)
    monkeypatch.setattr(train_router.database, "save_train_job", lambda job: None)
    log_path = log_dir / "train_offset-job.log"
    log_path.write_text("steps: 10/5100 [00:10<01:00, 1.0s/it]\n", encoding="utf-8")
    train_router._write_train_sidecar(
        "offset-job",
        cmd=["accelerate.exe", "launch", "train.py"],
        output_name="demo",
        auto_convert=False,
        cwd=str(tmp_path),
        steps_offset=3060,
    )

    public = train_router._public_train_job(
        {
            "job_id": "offset-job",
            "output_name": "demo",
            "status": "running",
            "log_path": str(log_path),
        }
    )

    assert public["steps_offset"] == 3060
    assert public["steps_done"] == 3070
    assert public["steps_total"] == 5100


def test_resume_endpoint_starts_a_tracked_job_from_latest_state(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "output"
    log_dir = tmp_path / "logs"
    output_dir.mkdir()
    log_dir.mkdir()
    monkeypatch.setattr(train_router, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(train_router, "LOG_DIR", log_dir)
    state_dir = output_dir / "demo-000003-state"
    state_dir.mkdir()
    (state_dir / "train_state.json").write_text(
        json.dumps({"current_epoch": 3, "current_step": 3060}), encoding="utf-8"
    )
    (state_dir / "model.safetensors").write_bytes(b"model")
    (state_dir / "optimizer.bin").write_bytes(b"optimizer")
    job_id = "old-job"
    train_router._write_train_sidecar(
        job_id,
        cmd=["accelerate.exe", "launch", "train.py", "--max_train_epochs", "5"],
        output_name="demo",
        auto_convert=False,
        cwd=str(tmp_path),
    )

    class _Proc:
        pid = 123
        returncode = None

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    train_router.TRAIN_JOBS[job_id] = {
        "job_id": job_id,
        "output_name": "demo",
        "status": "running",
        "process": _Proc(),
        "log_path": str(log_dir / "train_old-job.log"),
    }
    (log_dir / "train_old-job.log").write_text(
        "steps: 10/5100 [00:10<01:00, 1.0s/it]\n", encoding="utf-8"
    )
    captured: dict = {}

    class _NewProc:
        pid = 456

        def __init__(self, command, **kwargs):
            captured["command"] = command

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    monkeypatch.setattr(train_router.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(train_router.subprocess, "Popen", _NewProc)
    monkeypatch.setattr(train_router.task_registry, "finish", lambda *args, **kwargs: None)
    monkeypatch.setattr(train_router.task_registry, "register", lambda *args, **kwargs: None)
    monkeypatch.setattr(train_router.database, "save_train_job", lambda job: None)
    monkeypatch.setattr(train_router, "_watch_train_process", lambda job_id: None)
    try:
        result = train_router.resume_training(job_id)
    finally:
        train_router.TRAIN_JOBS.pop(job_id, None)
        train_router.TRAIN_JOBS.pop(result["job_id"], None) if "result" in locals() else None

    assert result["status"] == "running"
    assert result["resume_state"] == str(state_dir)
    assert captured["command"][-4:] == ["--resume", str(state_dir), "--max_data_loader_n_workers", "0"]
    sidecar = train_router._read_train_sidecar(result["job_id"])
    assert sidecar["resumed_from"] == str(state_dir)
    assert sidecar["steps_offset"] == 10
