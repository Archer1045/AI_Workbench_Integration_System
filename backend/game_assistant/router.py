"""FastAPI routes for the FGO Game Assistant."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .domain import GuideGenerationRequest, GuideGenerationResult
from .material_sourcing import material_sourcing
from .provider_settings import (
    ProviderSettingsError,
    ProviderSettingsUpdate,
    get_provider_settings_service,
)
from .service import get_service
from .source_domain import (
    SourceDiscoverIngestRequest,
    SourceDiscoverRequest,
    SourceDiscoverResult,
    SourceExtractionRequest,
    SourceExtractionResult,
    SourceIngestRequest,
    SourcePublishRequest,
    SourceRecord,
)
from .source_service import SourceError, get_source_manager
from .source_images import analyze_images, prepare_images
from .source_discovery import discover as discover_sources
from .source_discovery import normalize_fetched_page, url_allowed
from . import announcement_feed, mooncell_events, schedule
from web_tools import WebToolsError, get_web_tools_service

router = APIRouter(prefix="/api/game-assistant/fgo", tags=["game-assistant"])


@router.get("/schedule")
def schedule_list() -> dict[str, Any]:
    """后续活动日程。`confirmed` = 用户核对过来源的；`candidate` = 候选（未核对）。

    回答「下一个活动」时只认 confirmed；没有已确认日程时会明确说明——**不用日服进度、
    版本号或模型记忆推断国服排期**。
    """
    items = schedule.load_schedule()
    confirmed = [item for item in items if item.status == schedule.STATUS_CONFIRMED]
    now = datetime.now(schedule.SHANGHAI)
    return {
        "items": [item.model_dump(mode="json") for item in items],
        "confirmed_count": len(confirmed),
        "confirmed_upcoming": [
            item.model_dump(mode="json") for item in schedule.upcoming_confirmed_events(now)
        ],
        "japanese_reference": mooncell_events.japanese_reference(now),
        # 维护窗口单独存、单独回：它是日历上的一类条目，但**不能**混进活动日程
        "maintenance": announcement_feed.load_maintenance(),
        "path": str(schedule.schedule_path()),
        "note": "没有已确认日程时会明确回答「暂无」；候选日程需要人工核对来源后再标为已确认。",
    }


@router.post("/schedule")
def schedule_upsert(payload: schedule.ScheduleUpsertRequest) -> dict[str, Any]:
    event = schedule.upsert_event(
        payload.model_dump(exclude={"confirm"}), confirm=payload.confirm
    )
    return {"item": event.model_dump(mode="json")}


@router.post("/schedule/refresh-from-official")
def schedule_refresh_from_official(limit: int = 12) -> dict[str, Any]:
    """拉国服官方公告 → 落成**候选**日程（幂等；已确认的条目不动；永不自动确认）。

    这是「下个活动」的自动数据源。公告接口见 `announcement_feed` 模块头部的说明；
    官网抖动 / 断网时只回 `errors`，不抛异常（页面不该因为对方抖一下就打不开）。
    """
    summary = announcement_feed.refresh_schedule(limit=limit)
    # 顺带刷 Mooncell 活动表缓存（「日服·参考」那一行用；抓不到就保留旧缓存）
    summary["mooncell"] = mooncell_events.refresh_cache()
    return summary


@router.delete("/schedule/{event_id}")
def schedule_delete(event_id: str) -> dict[str, Any]:
    return {"deleted": schedule.delete_event(event_id)}


@router.get("/bootstrap")
def bootstrap() -> dict:
    try:
        return get_service().bootstrap()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/material-sourcing")
def material_sourcing_query(material: str, limit: int = 3, event_limit: int = 5) -> dict:
    """缺素材 X → 优先刷哪个自由关卡 / 哪个活动能换。

    掉落来自 Mooncell「道具一览」top3 关卡库（Atlas 无掉落数据），活动来自已导入的国服/日服活动库。
    """
    if not material.strip():
        raise HTTPException(status_code=400, detail="material 不能为空")
    try:
        return material_sourcing(material, limit=limit, event_limit=event_limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/events")
def list_events() -> list[dict]:
    return get_service().list_events()


@router.post("/guides/generate", response_model=GuideGenerationResult)
def generate_guide(request: GuideGenerationRequest) -> GuideGenerationResult:
    try:
        return get_service().generate_and_save(request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/guides/{generation_id}", response_model=GuideGenerationResult)
def get_guide(generation_id: str) -> GuideGenerationResult:
    result = get_service().get_generation(generation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="guide generation not found")
    return result


@router.get("/settings/providers")
def list_provider_settings():
    return get_provider_settings_service().list_settings()


@router.put("/settings/providers/{provider_id}")
def update_provider_settings(provider_id: str, payload: ProviderSettingsUpdate):
    try:
        return get_provider_settings_service().update(provider_id, payload)
    except ProviderSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/settings/providers/{provider_id}")
def delete_provider_settings(provider_id: str):
    try:
        return get_provider_settings_service().delete(provider_id)
    except ProviderSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/settings/providers/{provider_id}/test")
def test_provider_settings(provider_id: str):
    try:
        return get_provider_settings_service().test(provider_id)
    except ProviderSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sources", response_model=list[SourceRecord])
def list_sources(limit: int = 50):
    return get_source_manager().list_sources(limit=limit)


@router.post("/sources/discover", response_model=SourceDiscoverResult)
def discover_source_candidates(request: SourceDiscoverRequest) -> SourceDiscoverResult:
    try:
        return SourceDiscoverResult.model_validate(
            discover_sources(request.query, count=request.count, days=request.days)
        )
    except WebToolsError as exc:
        status = 502 if exc.retryable or (exc.status_code or 0) >= 500 else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.post("/sources/discover/ingest", response_model=SourceRecord)
def ingest_discovered_source(request: SourceDiscoverIngestRequest) -> SourceRecord:
    if not url_allowed(request.url):
        raise HTTPException(status_code=400, detail="只允许官方与 Mooncell 白名单域名")
    try:
        page = get_web_tools_service().fetch(request.url, app="game-assistant-source-ingest")
    except WebToolsError as exc:
        status = 502 if exc.retryable or (exc.status_code or 0) >= 500 else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    title, text, images = normalize_fetched_page(page.title, page.content)
    ingest_request = SourceIngestRequest(
        url=request.url,
        source_type=request.source_type,
        title=request.title or title,
        event_id=request.event_id,
        revision=request.revision,
    )
    try:
        return get_source_manager().ingest(
            ingest_request,
            prefetched_text=text,
            prefetched_title=title,
            prefetched_images=images,
            content_type="text/markdown",
            http_status=200,
        )
    except SourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sources/ingest", response_model=SourceRecord)
def ingest_source(request: SourceIngestRequest) -> SourceRecord:
    try:
        return get_source_manager().ingest(request)
    except SourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sources/{source_id}", response_model=SourceRecord)
def get_source(source_id: str) -> SourceRecord:
    try:
        return get_source_manager().get_source(source_id)
    except SourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sources/{source_id}/extract", response_model=SourceExtractionResult)
def extract_source(source_id: str, request: SourceExtractionRequest) -> SourceExtractionResult:
    try:
        return get_source_manager().extract(source_id, request.provider)
    except (SourceError, ProviderSettingsError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"{type(exc).__name__}: {exc}") from exc


@router.post("/sources/{source_id}/publish")
def publish_source(source_id: str, request: SourcePublishRequest):
    try:
        bundle = get_source_manager().publish(source_id, confirm=request.confirm)
    except SourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"published": True, "event_id": bundle.event_id, "revision": bundle.revision}


@router.post("/sources/{source_id}/images/prepare")
def prepare_source_images(source_id: str):
    try:
        return prepare_images(source_id, get_source_manager().sources)
    except SourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sources/{source_id}/images/analyze")
def analyze_source_images(source_id: str, payload: dict | None = None):
    try:
        model = str((payload or {}).get("model") or "")
        return analyze_images(source_id, get_source_manager().sources, model=model)
    except SourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"{type(exc).__name__}: {exc}") from exc


@router.get("/sources/{source_id}/images/{image_id}")
def get_source_image(source_id: str, image_id: str):
    record = get_source_manager().get_source(source_id)
    asset = next((item for item in record.image_assets if item.image_id == image_id), None)
    if asset is None or asset.status != "downloaded" or not asset.local_path:
        raise HTTPException(status_code=404, detail="source image not found")
    path = Path(asset.local_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="source image file missing")
    return FileResponse(path, media_type=asset.mime_type or "application/octet-stream")
