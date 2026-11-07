"""Caption task refresh recovery, progress parsing and idempotency."""
from __future__ import annotations

from pathlib import Path

import task_registry
import task_resources
from routers import train


class _NoopThread:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs

    def start(self) -> None:
        return None


def _clear_caption_jobs() -> None:
    for job_id in list(train.CAPTION_JOBS):
        task_registry.finish("caption", job_id, "stopped", "test cleanup")
    train.CAPTION_JOBS.clear()
    train.CAPTION_IDEMPOTENCY.clear()


def test_wd14_progress_uses_the_latest_completed_image_count() -> None:
    log = "\n".join(
        [
            "  0%|          | 0/101 [00:00<?, ?it/s]",
            " 27%|██▋       | 27/101 [00:54<02:29,  2.02s/it]",
            " 36%|███▌      | 36/101 [01:04<01:56,  1.80s/it]",
        ]
    )
    assert train._wd14_progress(log) == (36, 101)
    assert train._wd14_progress("no progress yet") is None


def test_caption_progress_updates_status_and_latest_endpoint(
    client,
    tmp_path: Path,
) -> None:
    _clear_caption_jobs()
    log_path = tmp_path / "wd14.log"
    log_path.write_text(
        " 42%|████▏     | 42/101 [01:10<01:39,  1.68s/it]\n",
        encoding="utf-8",
    )
    train.CAPTION_JOBS["caption-progress"] = {
        "job_id": "caption-progress",
        "mode": "wd14",
        "status": "running",
        "total": 101,
        "done": 0,
        "last_file": "",
        "log": "",
        "error": None,
        "cancelled": False,
        "process": None,
        "log_path": str(log_path),
        "created_at": "2026-10-27 02:04:01",
        "finished_at": None,
    }
    task_registry.register("caption", "caption-progress", total=101)
    try:
        status = client.get("/api/train/caption/caption-progress")
        assert status.status_code == 200
        assert status.json()["done"] == 42
        assert status.json()["total"] == 101
        assert task_registry.get("caption", "caption-progress")["done"] == 42

        latest = client.get("/api/train/caption/latest")
        assert latest.status_code == 200
        assert latest.json()["item"]["job_id"] == "caption-progress"
        assert latest.json()["item"]["done"] == 42
    finally:
        _clear_caption_jobs()


def test_caption_idempotency_reuses_the_running_job(
    client,
    tmp_path: Path,
    monkeypatch,
) -> None:
    _clear_caption_jobs()
    monkeypatch.setattr(train, "KOYA_PY", tmp_path / "python.exe")
    monkeypatch.setattr(train, "WD14_SCRIPT", tmp_path / "tagger.py")
    train.KOYA_PY.write_bytes(b"")
    train.WD14_SCRIPT.write_bytes(b"")
    monkeypatch.setattr(train.threading, "Thread", _NoopThread)

    payload = {"mode": "wd14", "skip_existing": False, "batch_size": 1}
    task_registry.register("merge", "merge-running")
    try:
        first = client.post(
            "/api/train/caption",
            json=payload,
            headers={"Idempotency-Key": "caption-request-1"},
        )
        assert first.status_code == 200
        first_body = first.json()
        assert first_body["status"] == "running"
    finally:
        task_registry.finish("merge", "merge-running", "done")

    duplicate = client.post(
        "/api/train/caption",
        json=payload,
        headers={"Idempotency-Key": "caption-request-1"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["job_id"] == first_body["job_id"]
    assert duplicate.json()["reused"] is True

    conflicting = client.post("/api/train/caption", json=payload)
    assert conflicting.status_code == 409
    _clear_caption_jobs()

    task_registry.register(
        "draw",
        "draw-holding-gpu",
        resources=task_resources.for_kind("draw"),
    )
    try:
        blocked = client.post(
            "/api/train/caption",
            json=payload,
            headers={"Idempotency-Key": "caption-request-2"},
        )
        assert blocked.status_code == 409
        assert "资源冲突" in blocked.json()["detail"]
    finally:
        task_registry.finish("draw", "draw-holding-gpu", "done")


def test_review_resource_conflict_does_not_leave_orphan_job(client) -> None:
    train.REVIEW_JOBS.clear()
    task_registry.register(
        "draw",
        "draw-review-conflict",
        resources=task_resources.for_kind("draw"),
    )
    try:
        response = client.post("/api/train/dataset/review", json={})
        assert response.status_code == 409
        assert "资源冲突" in response.json()["detail"]
        assert train.REVIEW_JOBS == {}
    finally:
        task_registry.finish("draw", "draw-review-conflict", "done")
