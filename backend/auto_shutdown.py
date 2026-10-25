"""Task-complete auto shutdown controller."""
from __future__ import annotations

import math
import subprocess
import threading
import time

import config
import database

ENABLED_KEY = "auto_shutdown_enabled"
DELAY_KEY = "auto_shutdown_delay_seconds"
MIN_DELAY = config.SETTINGS_AUTO_SHUTDOWN_DELAY_MIN
MAX_DELAY = config.SETTINGS_AUTO_SHUTDOWN_DELAY_MAX
OS_GRACE_SECONDS = 15

_state: dict = {
    "phase": "idle",
    "deadline_at": 0.0,
    "task_kind": None,
    "task_job_id": None,
    "last_done_key": None,
    "finished_at": None,
    "shutdown_at": None,
    "last_error": None,
}
_lock = threading.RLock()
_stop_event = threading.Event()
_watcher_thread = None


def _os_shutdown() -> None:
    flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags = subprocess.CREATE_NO_WINDOW
    subprocess.run(
        ["shutdown.exe", "/s", "/t", str(OS_GRACE_SECONDS)],
        check=True,
        timeout=30,
        creationflags=flags,
    )


_executor = _os_shutdown


def _now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def current_settings() -> dict:
    """Read persisted settings with safe defaults."""
    try:
        enabled = database.get_setting(ENABLED_KEY, "false") == "true"
        try:
            delay = max(
                MIN_DELAY,
                min(
                    MAX_DELAY,
                    int(
                        database.get_setting(
                            DELAY_KEY,
                            str(config.SETTINGS_AUTO_SHUTDOWN_DELAY_DEFAULT),
                        )
                        or config.SETTINGS_AUTO_SHUTDOWN_DELAY_DEFAULT
                    ),
                ),
            )
        except (TypeError, ValueError):
            delay = config.SETTINGS_AUTO_SHUTDOWN_DELAY_DEFAULT
        return {"enabled": enabled, "delay_seconds": delay}
    except Exception:
        return {
            "enabled": False,
            "delay_seconds": config.SETTINGS_AUTO_SHUTDOWN_DELAY_DEFAULT,
        }


def _task_label(kind: str | None) -> str:
    if not kind:
        return ""
    try:
        from task_state import TASK_LABELS

        return TASK_LABELS.get(kind, kind)
    except Exception:
        return kind


def _reset_locked() -> None:
    _state["phase"] = "idle"
    _state["deadline_at"] = 0.0
    _state["task_kind"] = None
    _state["task_job_id"] = None
    _state["finished_at"] = None
    _state["shutdown_at"] = None
    _state["last_error"] = None


def status() -> dict:
    settings = current_settings()
    with _lock:
        phase = "disabled" if not settings["enabled"] else _state["phase"]
        remaining = None
        if phase == "pending" and _state["deadline_at"]:
            remaining = max(0, math.ceil(_state["deadline_at"] - time.monotonic()))
        return {
            "enabled": settings["enabled"],
            "delay_seconds": settings["delay_seconds"],
            "phase": phase,
            "remaining_seconds": remaining,
            "task_type": _state["task_kind"],
            "task_label": _task_label(_state["task_kind"]),
            "finished_at": _state["finished_at"],
            "shutdown_at": _state["shutdown_at"],
            "last_error": _state["last_error"],
        }


def update_settings(payload: dict) -> dict:
    """Save auto shutdown settings and cancel any pending shutdown."""
    settings = current_settings()
    enabled = bool(payload.get("enabled", settings["enabled"]))
    try:
        delay = max(MIN_DELAY, min(MAX_DELAY, int(payload.get("delay_seconds", settings["delay_seconds"]))))
    except (TypeError, ValueError):
        raise ValueError("delay_seconds 必须是非负整数") from None
    database.set_setting(ENABLED_KEY, "true" if enabled else "false")
    database.set_setting(DELAY_KEY, str(delay))
    with _lock:
        if not enabled or _state["phase"] in ("executed", "error") or "delay_seconds" in payload:
            _reset_locked()
    return status()


def cancel() -> dict:
    """Cancel a pending auto shutdown countdown."""
    with _lock:
        _reset_locked()
    return status()


def notify_task_started(kind: str, job_id: str) -> None:
    """Called by task_registry when a task starts."""
    settings = current_settings()
    if not settings["enabled"]:
        return
    with _lock:
        if _state["phase"] == "pending":
            _reset_locked()
        _state["last_done_key"] = None


def notify_task_finished(kind: str, job_id: str, status_value: str) -> None:
    """Called by task_registry when a task reaches a terminal state."""
    settings = current_settings()
    if not settings["enabled"] or status_value != "done":
        return
    with _lock:
        done_key = (str(kind), str(job_id))
        if done_key == _state["last_done_key"]:
            return
        try:
            from task_state import running_tasks

            if running_tasks():
                return
        except Exception:
            pass
        _state["phase"] = "pending"
        _state["deadline_at"] = time.monotonic() + float(settings["delay_seconds"])
        _state["task_kind"] = str(kind)
        _state["task_job_id"] = str(job_id)
        _state["last_done_key"] = done_key
        _state["finished_at"] = _now_text()
        _state["shutdown_at"] = None
        _state["last_error"] = None


def _tick() -> None:
    settings = current_settings()
    with _lock:
        if not settings["enabled"]:
            if _state["phase"] in ("pending", "executed", "error"):
                _reset_locked()
            return
        if _state["phase"] != "pending":
            return
        if time.monotonic() < _state["deadline_at"]:
            return
        try:
            from task_state import running_tasks

            if running_tasks():
                _reset_locked()
                return
        except Exception:
            pass
        try:
            if _executor is not None:
                _executor()
            _state["phase"] = "executed"
            _state["deadline_at"] = 0.0
            _state["shutdown_at"] = _now_text()
            _state["last_error"] = None
        except Exception as exc:  # noqa: BLE001
            _state["phase"] = "error"
            _state["deadline_at"] = 0.0
            _state["last_error"] = str(exc)


def _loop() -> None:
    while not _stop_event.is_set():
        try:
            _tick()
        except Exception:
            pass
        _stop_event.wait(1)


def start_watcher() -> None:
    """Start the countdown watcher thread once."""
    global _watcher_thread
    if _watcher_thread is not None and _watcher_thread.is_alive():
        return
    _watcher_thread = threading.Thread(
        target=_loop,
        daemon=True,
        name="auto-shutdown-watcher",
    )
    _watcher_thread.start()


def set_executor_for_tests(executor) -> None:
    """Test hook: replace the OS shutdown command."""
    global _executor
    _executor = executor
