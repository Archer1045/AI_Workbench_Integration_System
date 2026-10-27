"""Persisted elapsed time returned by the draw batch status API."""
from __future__ import annotations

from datetime import datetime, timedelta

import app  # noqa: F401
from routers import draw as draw_router


def test_draw_batch_status_returns_stable_finished_elapsed(client) -> None:
    created_at = datetime.now().astimezone() - timedelta(seconds=90)
    finished_at = created_at + timedelta(seconds=37)
    batch_id = "draw-timer-finished"
    draw_router.BATCH_JOBS[batch_id] = {
        "batch_id": batch_id,
        "status": "done",
        "total": 2,
        "done": 2,
        "current_group": 0,
        "results": [],
        "error": None,
        "created_at": created_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "stop_requested": False,
    }
    try:
        response = client.get(f"/api/draw/batch/{batch_id}")
        assert response.status_code == 200
        assert response.json()["elapsed_seconds"] == 37
        assert response.json()["server_now"]
    finally:
        draw_router.BATCH_JOBS.pop(batch_id, None)


def test_draw_batch_status_elapsed_continues_while_running(client) -> None:
    created_at = datetime.now().astimezone() - timedelta(seconds=12)
    batch_id = "draw-timer-running"
    draw_router.BATCH_JOBS[batch_id] = {
        "batch_id": batch_id,
        "status": "running",
        "total": 4,
        "done": 1,
        "current_group": 0,
        "results": [],
        "error": None,
        "created_at": created_at.isoformat(timespec="seconds"),
        "finished_at": None,
        "stop_requested": False,
    }
    try:
        elapsed = client.get(f"/api/draw/batch/{batch_id}").json()["elapsed_seconds"]
        assert 12 <= elapsed <= 15
    finally:
        draw_router.BATCH_JOBS.pop(batch_id, None)
