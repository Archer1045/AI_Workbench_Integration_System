"""提示词集管理：新增、查询、编辑、删除、使用计数。"""
from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import Response

import config
import database
import prompt_document
from routers.chat import translate_text

router = APIRouter()


def _composition_json(payload: dict) -> str:
    raw = payload.get("composition_json")
    if raw in (None, ""):
        raw = payload.get("composition") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"组合元数据不是有效 JSON：{exc}") from exc
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="组合元数据必须是 JSON 对象")
    encoded = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > 20000:
        raise HTTPException(status_code=400, detail="组合元数据过长")
    return encoded


def _prompt_document_json(payload: dict, existing: dict | None = None) -> str:
    if "prompt_document_json" not in payload and "prompt_document" not in payload:
        return str((existing or {}).get("prompt_document_json") or "{}")
    raw = payload.get("prompt_document_json")
    if raw in (None, ""):
        raw = payload.get("prompt_document") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"结构化提示词不是有效 JSON：{exc}") from exc
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="结构化提示词必须是 JSON 对象")
    normalized = prompt_document.normalize_document(raw)
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > 200000:
        raise HTTPException(status_code=400, detail="结构化提示词过长")
    return encoded


def _validate_payload(
    payload: dict,
    prompt_id: int | None = None,
) -> tuple[str, str, str, str, str, str, str, str]:
    name = str(payload.get("name") or "").strip()
    prompt_type = str(payload.get("type") or "其他").strip() or "其他"
    content = str(payload.get("content") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="提示词集名称不能为空")
    if not content:
        raise HTTPException(status_code=400, detail="提示词集内容不能为空")
    if database.prompt_set_name_exists(name, exclude_id=prompt_id):
        raise HTTPException(status_code=400, detail="同名提示词集已存在")
    translation = str(payload.get("translation") or "").strip()
    if not translation:
        translation = translate_text(content)
    description = str(payload.get("description") or "").strip()
    tags = str(payload.get("tags") or "").strip()
    existing = database.get_prompt_set(prompt_id) if prompt_id is not None else None
    if "composition_json" not in payload and "composition" not in payload and existing is not None:
        composition_json = str(existing.get("composition_json") or "{}")
    else:
        composition_json = _composition_json(payload)
    prompt_document_json = _prompt_document_json(payload, existing)
    return (
        name,
        prompt_type,
        content,
        translation,
        description,
        tags,
        composition_json,
        prompt_document_json,
    )


@router.get("/api/prompt-sets")
def list_prompt_sets(
    keyword: str | None = Query(None),
    type: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    page: int = Query(
        config.QUERY_PROMPT_SET_PAGE_DEFAULT,
        ge=config.QUERY_PAGE_MIN,
    ),
    page_size: int = Query(
        config.QUERY_PROMPT_SET_PAGE_SIZE_DEFAULT,
        ge=config.QUERY_PAGE_MIN,
        le=config.QUERY_PROMPT_SET_PAGE_SIZE_MAX,
    ),
) -> dict:
    """按关键词/类型/时间范围分页查询提示词集。"""
    return database.query_prompt_sets(
        keyword=keyword,
        prompt_type=type,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


def _export_rows(
    keyword: str | None,
    prompt_type: str | None,
    date_from: str | None,
    date_to: str | None,
) -> list[dict]:
    rows = database.list_all_prompt_sets()
    filtered: list[dict] = []
    for row in rows:
        if keyword:
            haystack = f"{row.get('name') or ''} {row.get('content') or ''} {row.get('tags') or ''}".lower()
            if keyword.lower() not in haystack:
                continue
        if prompt_type and row.get("type") != prompt_type:
            continue
        day = str(row.get("created_at") or "")[:10]
        if date_from and day < date_from:
            continue
        if date_to and day > date_to:
            continue
        filtered.append(row)
    return filtered


@router.get("/api/prompt-sets/export")
def export_prompt_sets(
    format: str = Query("json"),
    keyword: str | None = Query(None),
    type: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
) -> Response:
    """导出提示词集为 JSON 或 CSV。"""
    rows = _export_rows(keyword, type, date_from, date_to)
    if format == "json":
        content = json.dumps(rows, ensure_ascii=False, indent=2)
        media_type = "application/json"
        filename = "prompt-sets.json"
    elif format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer,
            fieldnames=["name", "type", "content", "translation", "description", "tags", "composition_json", "prompt_document_json", "use_count", "created_at", "updated_at"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
        content = buffer.getvalue()
        media_type = "text/csv; charset=utf-8"
        filename = "prompt-sets.csv"
    else:
        raise HTTPException(status_code=400, detail="format 只支持 json 或 csv")
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/prompt-sets/import")
def import_prompt_sets(payload: dict = Body(...)) -> dict:
    """导入提示词集（JSON 数组或 CSV）。"""
    format = str(payload.get("format") or "").strip().lower()
    content = str(payload.get("content") or "")
    items: list[dict] = []
    if format == "json":
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"JSON 解析失败：{exc}") from exc
        if not isinstance(data, list):
            raise HTTPException(status_code=400, detail="JSON 顶层必须是数组")
        items = data
    elif format == "csv":
        reader = csv.DictReader(io.StringIO(content))
        items = [{k.strip(): (v or "").strip() for k, v in row.items()} for row in reader]
    else:
        raise HTTPException(status_code=400, detail="format 只支持 json 或 csv")

    inserted = 0
    skipped = 0
    errors: list[str] = []
    for index, item in enumerate(items):
        name = str(item.get("name") or "").strip()
        prompt_content = str(item.get("content") or "").strip()
        if not name or not prompt_content:
            skipped += 1
            errors.append(f"第 {index + 1} 条缺少名称或内容")
            continue
        if database.prompt_set_name_exists(name):
            skipped += 1
            errors.append(f"第 {index + 1} 条同名已存在：{name}")
            continue
        database.insert_prompt_set(
            name,
            str(item.get("type") or "其他").strip() or "其他",
            prompt_content,
            str(item.get("translation") or "").strip(),
            str(item.get("description") or "").strip(),
            str(item.get("tags") or "").strip(),
            _composition_json(item),
            _prompt_document_json(item),
        )
        inserted += 1
    return {"ok": True, "inserted": inserted, "skipped": skipped, "errors": errors[:10]}


@router.post("/api/prompt-sets/batch-delete")
def batch_delete_prompt_sets(payload: dict = Body(...)) -> dict:
    """批量删除提示词集。"""
    ids: list[int] = []
    for value in payload.get("ids") or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="ids 不合法")
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要删除的记录")
    for prompt_id in ids:
        if database.get_prompt_set(prompt_id):
            database.delete_prompt_set(prompt_id)
    return {"ok": True, "deleted": len(ids)}


@router.post("/api/prompt-sets")
def create_prompt_set(payload: dict = Body(...)) -> dict:
    """新增提示词集。"""
    (
        name,
        prompt_type,
        content,
        translation,
        description,
        tags,
        composition_json,
        prompt_document_json,
    ) = _validate_payload(payload)
    prompt_id = database.insert_prompt_set(
        name,
        prompt_type,
        content,
        translation,
        description,
        tags,
        composition_json,
        prompt_document_json,
    )
    item = database.get_prompt_set(prompt_id)
    return {"ok": True, "item": item}


@router.put("/api/prompt-sets/batch-type")
def batch_update_type(payload: dict = Body(...)) -> dict:
    """批量修改提示词集类型。"""
    ids_raw = payload.get("ids") or []
    prompt_type = str(payload.get("type") or "").strip()
    ids: list[int] = []
    for value in ids_raw:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="ids 不合法")
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要修改的记录")
    if not prompt_type:
        raise HTTPException(status_code=400, detail="类型不能为空")
    updated = database.update_prompt_sets_type(ids, prompt_type)
    return {"ok": True, "updated": updated}


@router.put("/api/prompt-sets/{prompt_id}")
def edit_prompt_set(prompt_id: int, payload: dict = Body(...)) -> dict:
    """编辑提示词集。"""
    if not database.get_prompt_set(prompt_id):
        raise HTTPException(status_code=404, detail="提示词集不存在")
    (
        name,
        prompt_type,
        content,
        translation,
        description,
        tags,
        composition_json,
        prompt_document_json,
    ) = _validate_payload(payload, prompt_id=prompt_id)
    database.update_prompt_set(
        prompt_id,
        name,
        prompt_type,
        content,
        translation,
        description,
        tags,
        composition_json,
        prompt_document_json,
    )
    return {"ok": True, "item": database.get_prompt_set(prompt_id)}


@router.delete("/api/prompt-sets/{prompt_id}")
def remove_prompt_set(prompt_id: int) -> dict:
    """删除提示词集。"""
    if not database.get_prompt_set(prompt_id):
        raise HTTPException(status_code=404, detail="提示词集不存在")
    database.delete_prompt_set(prompt_id)
    return {"ok": True}


@router.post("/api/prompt-sets/{prompt_id}/use")
def use_prompt_set(prompt_id: int) -> dict:
    """插入使用时累计使用次数。"""
    if not database.get_prompt_set(prompt_id):
        raise HTTPException(status_code=404, detail="提示词集不存在")
    database.touch_prompt_set(prompt_id)
    return {"ok": True}
