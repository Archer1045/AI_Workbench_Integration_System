"""Checkpointed long-video segment orchestration on top of Wan I2V."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import config
import database
import storyboard_tools
import task_registry
import video_worker


class LongVideoError(RuntimeError):
    pass


_JOB_LOCKS: dict[str, threading.Lock] = {}
_LOCK = threading.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _job_root(job_id: str) -> Path:
    return config.LONG_VIDEO_ROOT / job_id


def state_path(job_id: str) -> Path:
    return _job_root(job_id) / "checkpoint.json"


def _write_state(state: dict[str, Any]) -> None:
    path = state_path(str(state["job_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_state(job_id: str) -> dict[str, Any]:
    path = state_path(job_id)
    if not path.is_file():
        raise LongVideoError("长视频任务检查点不存在。")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LongVideoError(f"长视频检查点损坏：{exc}") from exc
    if not isinstance(state, dict) or state.get("job_id") != job_id:
        raise LongVideoError("长视频检查点格式不正确。")
    return state


def create_state(job_id: str, params: dict[str, Any]) -> dict[str, Any]:
    root = _job_root(job_id)
    (root / "segments").mkdir(parents=True, exist_ok=True)
    (root / "frames").mkdir(parents=True, exist_ok=True)
    segments = [
        {
            "index": index,
            "prompt": str(prompt),
            "seed": int(params["segment_seeds"][index - 1]),
            "status": "pending",
            "attempts": 0,
            "video_name": "",
            "error": "",
        }
        for index, prompt in enumerate(params["prompts"], start=1)
    ]
    state = {
        "version": 1,
        "job_id": job_id,
        "status": "running",
        "created_at": _now(),
        "updated_at": _now(),
        "error": "",
        "params": params,
        "segments": segments,
        "final_video_name": "",
        "final_url": "",
    }
    _write_state(state)
    return state


def _job_lock(job_id: str) -> threading.Lock:
    with _LOCK:
        return _JOB_LOCKS.setdefault(job_id, threading.Lock())


def _stop_requested(job_id: str) -> bool:
    job = task_registry.get("video_long", job_id)
    return bool(job and job.get("stop_requested"))


def request_stop(job_id: str) -> dict[str, Any]:
    job = task_registry.get("video_long", job_id)
    if not job:
        raise LongVideoError("长视频任务不存在。")
    task_registry.update("video_long", job_id, stop_requested=True)
    video_worker._interrupt_comfy()
    return {"job_id": job_id, "status": "stopping"}


def _segment_file(state: dict[str, Any], segment: dict[str, Any]) -> Path:
    return _job_root(str(state["job_id"])) / "segments" / str(segment["video_name"])


def _first_incomplete(state: dict[str, Any]) -> int:
    for index, segment in enumerate(state["segments"], start=1):
        if segment.get("status") != "ready":
            return index
        path = _segment_file(state, segment)
        if not path.is_file():
            return index
    return len(state["segments"]) + 1


def resume_index(job_id: str, from_segment: int | None = None) -> int:
    state = load_state(job_id)
    start = int(from_segment or _first_incomplete(state))
    total = len(state["segments"])
    if start < 1 or start > total + 1:
        raise LongVideoError(f"恢复片段必须在 1-{total} 之间。")
    if start > 1:
        previous = state["segments"][start - 2]
        if previous.get("status") != "ready" or not _segment_file(state, previous).is_file():
            raise LongVideoError("前一段尚未完成，不能从该片段继续。")
    return start


def prepare_resume(job_id: str, from_segment: int | None = None) -> dict[str, Any]:
    state = load_state(job_id)
    start = resume_index(job_id, from_segment)
    for segment in state["segments"][start - 1 :]:
        segment["status"] = "pending"
        segment["error"] = ""
        segment["video_name"] = ""
    state["status"] = "running"
    state["error"] = ""
    state["updated_at"] = _now()
    _write_state(state)
    return state


def _extract_last_frame(video_path: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(
        [
            str(storyboard_tools.ffmpeg_path()),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-sseof",
            "-0.15",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-update",
            "1",
            str(target),
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if process.returncode != 0 or not target.is_file():
        raise LongVideoError(
            "无法提取上一段尾帧："
            + process.stderr.decode("utf-8", errors="replace")[-500:]
        )
    return target


def run_job(job_id: str) -> None:
    """Run or resume one long-video job while preserving ready segments."""
    lock = _job_lock(job_id)
    if not lock.acquire(blocking=False):
        return
    active_index = 0
    started = time.time()
    try:
        state = load_state(job_id)
        params = state["params"]
        total = len(state["segments"])
        start = _first_incomplete(state)
        if start > total:
            _finish_success(job_id, state, started)
            return
        for segment in state["segments"]:
            if segment.get("status") == "running":
                segment["status"] = "pending"
        state["status"] = "running"
        state["error"] = ""
        _write_state(state)
        task_registry.update(
            "video_long",
            job_id,
            status="running",
            error=None,
            done=start - 1,
            total=total,
            stop_requested=False,
            current=f"准备第 {start}/{total} 段",
        )
        for segment in state["segments"][start - 1 :]:
            index = int(segment["index"])
            active_index = index
            if _stop_requested(job_id):
                raise video_worker.VideoGenerationStopped("用户取消")
            if index == 1:
                keyframe_name = str(params["keyframe_name"])
            else:
                previous = state["segments"][index - 2]
                previous_path = _segment_file(state, previous)
                if previous.get("status") != "ready" or not previous_path.is_file():
                    raise LongVideoError("上一段成片缺失，无法保持片段连续性。")
                keyframe_name = str(
                    _extract_last_frame(
                        previous_path,
                        _job_root(job_id)
                        / "frames"
                        / f"segment_{index:03d}_start.png",
                    )
                )
            segment["status"] = "running"
            segment["attempts"] = int(segment.get("attempts") or 0) + 1
            segment["error"] = ""
            state["updated_at"] = _now()
            _write_state(state)
            task_registry.update(
                "video_long",
                job_id,
                current=f"第 {index}/{total} 段生成中",
                done=index - 1,
                total=total,
            )
            segment_params = {
                key: value
                for key, value in params.items()
                if key
                not in {
                    "prompts",
                    "segment_seeds",
                }
            }
            segment_params.update(
                {
                    "positive_prompt": segment["prompt"],
                    "seed": int(segment["seed"]),
                    "keyframe_name": keyframe_name,
                    "filename_prefix": (
                        f"long_{job_id[:8]}_s{index:03d}_"
                        f"a{segment['attempts']}_{segment['seed']}"
                    ),
                    "output_dir": str(_job_root(job_id) / "segments"),
                }
            )
            target = video_worker.generate_video_output(
                f"{job_id}_s{index:03d}",
                segment_params,
                progress=lambda current, index=index: task_registry.update(
                    "video_long",
                    job_id,
                    current=f"第 {index}/{total} 段 · {current}",
                ),
                should_stop=lambda: _stop_requested(job_id),
            )
            segment["status"] = "ready"
            segment["video_name"] = target.name
            segment["error"] = ""
            state["updated_at"] = _now()
            _write_state(state)
            task_registry.update(
                "video_long",
                job_id,
                done=index,
                total=total,
                current=f"第 {index}/{total} 段已落盘",
            )
        active_index = 0
        _finish_success(job_id, state, started)
    except video_worker.VideoGenerationStopped:
        state = load_state(job_id)
        if active_index:
            segment = state["segments"][active_index - 1]
            if segment.get("status") == "running":
                segment["status"] = "pending"
                segment["error"] = "用户取消"
        state["status"] = "stopped"
        state["error"] = "用户取消"
        state["updated_at"] = _now()
        _write_state(state)
        database.update_video_record_result(job_id, "stopped", error="用户取消")
        task_registry.finish("video_long", job_id, "stopped", "用户取消")
    except Exception as exc:  # noqa: BLE001 - persist a resumable terminal state
        try:
            state = load_state(job_id)
            if active_index:
                segment = state["segments"][active_index - 1]
                segment["status"] = "failed"
                segment["error"] = str(exc)[-1000:]
            state["status"] = "error"
            state["error"] = str(exc)[-1000:]
            state["updated_at"] = _now()
            _write_state(state)
        except Exception:
            pass
        database.update_video_record_result(job_id, "error", error=str(exc)[-1000:])
        task_registry.finish("video_long", job_id, "error", str(exc)[-1000:])
    finally:
        lock.release()


def _finish_success(job_id: str, state: dict[str, Any], started: float) -> None:
    ready_paths: list[tuple[Path, str]] = []
    for segment in state["segments"]:
        path = _segment_file(state, segment)
        if segment.get("status") != "ready" or not path.is_file():
            raise LongVideoError("仍有片段未完成，不能合并长视频。")
        ready_paths.append((path, path.name))
    task_registry.update(
        "video_long",
        job_id,
        current="合并已完成片段",
    )
    merged = storyboard_tools.merge_videos(
        ready_paths,
        output_dir=config.VIDEO_OUTPUT_DIR,
    )
    state["status"] = "done"
    state["error"] = ""
    state["final_video_name"] = merged["filename"]
    state["final_url"] = f"/api/video/file/{merged['filename']}"
    state["updated_at"] = _now()
    _write_state(state)
    database.update_video_record_result(
        job_id,
        "done",
        video_name=merged["filename"],
        duration_seconds=round(time.time() - started, 1),
    )
    task_registry.update(
        "video_long",
        job_id,
        done=len(state["segments"]),
        total=len(state["segments"]),
        current=merged["filename"],
    )
    task_registry.finish("video_long", job_id, "done")
