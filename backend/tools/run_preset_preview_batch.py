#!/usr/bin/env python
"""Submit one scheduled preset-preview batch without adopting candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import requests


DEFAULT_API_BASE = "http://127.0.0.1:8500/api"
API_BASE = os.environ.get("PRESET_API_BASE", DEFAULT_API_BASE).rstrip("/")
MAX_ITEMS_PER_JOB = 50


def _api(method: str, path: str, *, payload: dict | None = None, headers: dict | None = None) -> dict:
    response = requests.request(
        method,
        f"{API_BASE}{path}",
        json=payload,
        headers=headers,
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"{method} {path} failed: {response.status_code} {response.text[:1000]}"
        )
    return response.json()


def _catalog_state() -> dict[tuple[str, str], dict]:
    catalog = _api("GET", "/preset-assets/catalog")
    return {
        (str(item["preset_type"]), str(item["preset_id"])): item
        for kind in catalog.get("items") or []
        for item in kind.get("items") or []
    }


def _state_path(manifest_path: Path) -> Path:
    return manifest_path.with_name(f"{manifest_path.stem}_execution.json")


def _write_state(path: Path, payload: dict) -> None:
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _chunk_key(batch_id: str, chunk_index: int, items: list[dict]) -> str:
    item_ids = "\n".join(
        f"{item['preset_type']}:{item['preset_id']}" for item in items
    )
    digest = hashlib.sha256(item_ids.encode("utf-8")).hexdigest()[:16]
    return f"{batch_id}-{chunk_index:03d}-{digest}"


def submit(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    state_path = _state_path(manifest_path)
    state = None
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("status") == "submitted":
            print(json.dumps({"already_submitted": True, **state}, ensure_ascii=False, indent=2))
            return state

    params = dict(manifest.get("params") or {})
    if int(params.get("candidate_count") or 0) != 4:
        raise RuntimeError("批处理 manifest 必须固定 candidate_count=4")

    current = _catalog_state()
    eligible = []
    skipped = []
    for item in manifest.get("items") or []:
        key = (str(item["preset_type"]), str(item["preset_id"]))
        preset = current.get(key)
        if not preset:
            skipped.append({**item, "skip_reason": "preset_missing"})
            continue
        if preset.get("has_image"):
            skipped.append({**item, "skip_reason": "formal_preview_exists"})
            continue
        if int(preset.get("ready_count") or 0) > 0:
            skipped.append({**item, "skip_reason": "ready_candidate_exists"})
            continue
        eligible.append(item)

    processed = {
        preset_id
        for job in (state or {}).get("jobs", [])
        for preset_id in job.get("preset_ids", [])
    }
    remaining = [
        item
        for item in eligible
        if f"{item['preset_type']}:{item['preset_id']}" not in processed
    ]
    resumed = state is not None
    if state is None:
        state = {
            "batch_id": manifest["batch_id"],
            "manifest": str(manifest_path),
            "scheduled_for": manifest.get("scheduled_for"),
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "status": "running",
            "planned_items": len(manifest.get("items") or []),
            "eligible_items": len(eligible),
            "skipped_items": skipped,
            "jobs": [],
        }
    else:
        state["status"] = "running"
        state["resumed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        state["resume_eligible_items"] = len(remaining)
        state["resume_skipped_items"] = len(skipped)
        state["error"] = None
    _write_state(state_path, state)

    first_new_chunk = len(state.get("jobs") or [])
    try:
        for ordinal, offset in enumerate(range(0, len(remaining), MAX_ITEMS_PER_JOB)):
            chunk_index = first_new_chunk + ordinal
            chunk = remaining[offset : offset + MAX_ITEMS_PER_JOB]
            key = _chunk_key(manifest["batch_id"], chunk_index, chunk)
            payload = {
                "items": [
                    {
                        "preset_type": item["preset_type"],
                        "preset_id": item["preset_id"],
                        "mode": "ai",
                        "params": params,
                    }
                    for item in chunk
                ]
            }
            job = _api(
                "POST",
                "/preset-assets/jobs",
                payload=payload,
                headers={"Idempotency-Key": key},
            )
            state["jobs"].append(
                {
                    "chunk": chunk_index,
                    "idempotency_key": key,
                    "job_id": job["job_id"],
                    "preset_count": len(chunk),
                    "candidate_count": len(chunk) * 4,
                    "preset_ids": [
                        f"{item['preset_type']}:{item['preset_id']}"
                        for item in chunk
                    ],
                }
            )
            _write_state(state_path, state)
            print(
                f"submitted chunk {chunk_index + 1}: "
                f"job={job['job_id']} presets={len(chunk)}"
            )
    except Exception as exc:
        state["status"] = "failed"
        state["error"] = str(exc)
        state["failed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _write_state(state_path, state)
        raise

    state["status"] = "submitted"
    state["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    state["error"] = None
    if resumed:
        state["resumed_submission_complete"] = True
    _write_state(state_path, state)
    return state


def status(manifest_path: Path) -> dict:
    state_path = _state_path(manifest_path)
    if not state_path.exists():
        return {"status": "not_submitted", "manifest": str(manifest_path)}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    jobs = []
    for item in state.get("jobs") or []:
        job = _api("GET", f"/preset-assets/jobs/{item['job_id']}")
        jobs.append(
            {
                "job_id": item["job_id"],
                "status": job.get("status"),
                "total": job.get("total"),
                "done": job.get("done"),
                "error": job.get("error"),
            }
        )
    return {**state, "jobs": jobs}


def dry_run(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    current = _catalog_state()
    eligible = 0
    skipped = 0
    for item in manifest.get("items") or []:
        preset = current.get((str(item["preset_type"]), str(item["preset_id"])))
        if (
            preset
            and not preset.get("has_image")
            and int(preset.get("ready_count") or 0) == 0
        ):
            eligible += 1
        else:
            skipped += 1
    return {
        "batch_id": manifest["batch_id"],
        "scheduled_for": manifest.get("scheduled_for"),
        "planned_items": len(manifest.get("items") or []),
        "eligible_items": eligible,
        "skipped_items": skipped,
        "candidate_count": eligible * 4,
        "chunks": (eligible + MAX_ITEMS_PER_JOB - 1) // MAX_ITEMS_PER_JOB,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.status:
        result = status(args.manifest)
    elif args.execute:
        result = submit(args.manifest)
    else:
        result = dry_run(args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
