"""Preset thumbnail workshop API."""
from __future__ import annotations

import base64
import binascii
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Header, Query
from fastapi.responses import Response

import database
import preset_asset_pipeline as pipeline
import preset_asset_service as service
from routers.settings_router import content_restriction_enabled

router = APIRouter(prefix="/api/preset-assets", tags=["preset-assets"])


def _restricted() -> bool:
    return content_restriction_enabled()


def _ensure_candidate_access(candidate_id: int) -> dict[str, Any]:
    candidate = database.get_preset_asset_candidate(candidate_id)
    if not candidate:
        raise service.PresetAssetError("候选不存在", status_code=404)
    service.ensure_restricted_access(
        str(candidate["preset_type"]),
        str(candidate["preset_id"]),
        _restricted(),
    )
    return candidate


def _ensure_source_access(source_id: int) -> dict[str, Any]:
    source = database.get_preset_asset_source(source_id)
    if not source:
        raise service.PresetAssetError("源图不存在", status_code=404)
    service.ensure_restricted_access(
        str(source["preset_type"]),
        str(source["preset_id"]),
        _restricted(),
    )
    return source


def _ensure_version_access(version_id: int) -> dict[str, Any]:
    version = database.get_preset_asset_version(version_id)
    if not version:
        raise service.PresetAssetError("版本不存在", status_code=404)
    service.ensure_restricted_access(
        str(version["preset_type"]),
        str(version["preset_id"]),
        _restricted(),
    )
    return version


def _ensure_job_access(job: dict[str, Any]) -> None:
    if not _restricted():
        return
    seen: set[tuple[str, str]] = set()
    for item in job.get("items") or []:
        key = (str(item.get("preset_type") or ""), str(item.get("preset_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        service.ensure_restricted_access(key[0], key[1], True)


def _job_accessible(job: dict[str, Any]) -> bool:
    try:
        _ensure_job_access(job)
    except service.PresetAssetError as exc:
        if exc.status_code == 403:
            return False
        raise
    return True


def _decode_data_url(value: str) -> tuple[bytes, str | None]:
    text = str(value or "").strip()
    if not text:
        raise service.PresetAssetError("图片数据不能为空", status_code=400)
    mime_type = None
    if text.startswith("data:"):
        header, separator, encoded = text.partition(",")
        if not separator:
            raise service.PresetAssetError("图片 data URL 格式错误", status_code=400)
        mime_type = header[5:].split(";", 1)[0] or None
        text = encoded
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise service.PresetAssetError("图片 base64 格式错误", status_code=400) from exc
    return data, mime_type


def _file_response(path: Path) -> Response:
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return Response(
        path.read_bytes(),
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return service.settings_payload()


@router.put("/settings")
def update_settings(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    values = payload.get("defaults") if isinstance(payload.get("defaults"), dict) else payload
    return service.save_settings(values)


@router.get("/catalog")
def get_catalog() -> dict[str, Any]:
    return service.catalog(_restricted())


@router.get("/catalog/query")
def query_catalog(
    kind: str = Query("pose"),
    keyword: str = Query(""),
    resource: str = Query("all"),
    rating: str = Query(""),
    category_group: str = Query(""),
    subcategory: str = Query(""),
    candidate_status: str = Query(""),
    task_status: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(40, ge=1, le=100),
    sort: str = Query("default"),
) -> dict[str, Any]:
    return service.catalog_query(
        kind=kind,
        keyword=keyword,
        resource=resource,
        rating=rating,
        category_group=category_group,
        subcategory=subcategory,
        candidate_status=candidate_status,
        task_status=task_status,
        page=page,
        page_size=page_size,
        sort=sort,
        restriction=_restricted(),
    )


@router.get("/presets/{preset_type}/{preset_id}")
def get_preset(preset_type: str, preset_id: str) -> dict[str, Any]:
    return service.preset_detail(preset_type, preset_id, _restricted())


@router.get("/presets/{preset_type}/{preset_id}/history")
def get_preset_history(
    preset_type: str,
    preset_id: str,
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    service.ensure_restricted_access(preset_type, preset_id, _restricted())
    return {
        "versions": [
            service._version_payload(item)
            for item in database.list_preset_asset_versions(
                preset_type, preset_id, limit=limit
            )
        ],
        "audit": database.list_preset_asset_audit(
            preset_type, preset_id, limit=limit
        ),
    }


@router.post("/presets/{preset_type}/{preset_id}/sources/import")
def import_preset_source(
    preset_type: str,
    preset_id: str,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    service.ensure_restricted_access(preset_type, preset_id, _restricted())
    data, detected_mime = _decode_data_url(str(payload.get("data") or ""))
    mime_type = str(payload.get("mime_type") or detected_mime or "").strip() or None
    return service.import_source(
        preset_type,
        preset_id,
        data,
        mime_type=mime_type,
        source_kind="upload",
    )


@router.post("/presets/{preset_type}/{preset_id}/candidates/crop")
def create_crop_candidate(
    preset_type: str,
    preset_id: str,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    preset = service.ensure_restricted_access(
        preset_type,
        preset_id,
        _restricted(),
    )
    params = dict(payload.get("params") or {})
    if preset_type == "character":
        params["preset_version"] = int(preset.get("version") or 1)
    return service.create_crop_candidate(
        preset_type,
        preset_id,
        source_id=(
            int(payload["source_id"])
            if payload.get("source_id") not in (None, "")
            else None
        ),
        crop=dict(payload.get("crop") or {}),
        params=params,
    )


@router.post("/presets/{preset_type}/{preset_id}/candidates/ai")
def create_ai_candidate(
    preset_type: str,
    preset_id: str,
    payload: dict[str, Any] = Body(...),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    service.ensure_restricted_access(preset_type, preset_id, _restricted())
    return pipeline.create_job(
        [
            {
                "preset_type": preset_type,
                "preset_id": preset_id,
                "mode": "ai",
                "params": payload.get("params") or payload,
            }
        ],
        idempotency_key=idempotency_key,
    )


@router.post("/jobs")
def create_jobs(
    payload: dict[str, Any] = Body(...),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise service.PresetAssetError("items 必须是数组", status_code=400)
    for item in items:
        if not isinstance(item, dict):
            raise service.PresetAssetError("任务项格式错误", status_code=400)
        service.ensure_restricted_access(
            str(item.get("preset_type") or ""),
            str(item.get("preset_id") or ""),
            _restricted(),
        )
    return pipeline.create_job(items, idempotency_key=idempotency_key)


@router.get("/jobs")
def list_jobs(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    jobs: list[dict[str, Any]] = []
    for row in database.list_background_jobs(
        kind=pipeline.JOB_KIND,
        status=status,
        limit=limit,
    ):
        job = pipeline.job_status(str(row["job_id"]))
        if _job_accessible(job):
            jobs.append(job)
    return {"items": jobs}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = pipeline.job_status(job_id)
    _ensure_job_access(job)
    return job


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    job = pipeline.job_status(job_id)
    _ensure_job_access(job)
    return pipeline.cancel_job(job_id)


@router.post("/jobs/{job_id}/retry-failed")
def retry_failed_job(job_id: str) -> dict[str, Any]:
    job = pipeline.job_status(job_id)
    _ensure_job_access(job)
    return pipeline.retry_failed_job(job_id)


@router.post("/jobs/{job_id}/items/{item_index}/retry")
def retry_failed_job_item(job_id: str, item_index: int) -> dict[str, Any]:
    job = pipeline.job_status(job_id)
    _ensure_job_access(job)
    return pipeline.retry_failed_job(job_id, {item_index})


@router.post("/candidates/{candidate_id}/adopt")
def adopt_candidate(
    candidate_id: int,
    payload: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    _ensure_candidate_access(candidate_id)
    expected = (payload or {}).get("expected_revision")
    return service.adopt_candidate(
        candidate_id,
        int(expected) if expected not in (None, "") else None,
    )


@router.post("/candidates/{candidate_id}/discard")
def discard_candidate(candidate_id: int) -> dict[str, Any]:
    _ensure_candidate_access(candidate_id)
    return service.discard_candidate(candidate_id)


@router.post("/presets/{preset_type}/{preset_id}/candidates/clear")
def clear_candidates(preset_type: str, preset_id: str) -> dict[str, Any]:
    service.ensure_restricted_access(preset_type, preset_id, _restricted())
    return service.clear_candidates(preset_type, preset_id)


@router.post("/presets/{preset_type}/{preset_id}/rollback/{version}")
def rollback_version(
    preset_type: str,
    preset_id: str,
    version: int,
    payload: dict[str, Any] | None = Body(None),
) -> dict[str, Any]:
    service.ensure_restricted_access(preset_type, preset_id, _restricted())
    expected = (payload or {}).get("expected_revision")
    return service.rollback_version(
        preset_type,
        preset_id,
        version,
        int(expected) if expected not in (None, "") else None,
    )


@router.get("/sources/{source_id}/file")
def get_source_file(source_id: int) -> Response:
    _ensure_source_access(source_id)
    return _file_response(service.source_file(source_id))


@router.get("/candidates/{candidate_id}/file")
def get_candidate_file(
    candidate_id: int,
    original: bool = Query(False),
) -> Response:
    _ensure_candidate_access(candidate_id)
    return _file_response(service.candidate_file(candidate_id, original=original))


@router.get("/versions/{version_id}/file")
def get_version_file(version_id: int) -> Response:
    _ensure_version_access(version_id)
    return _file_response(service.version_file(version_id))
