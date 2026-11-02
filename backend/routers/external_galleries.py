"""HTTP routes for independently bound external reference galleries."""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse

import external_galleries


router = APIRouter(prefix="/api/external-galleries", tags=["external-galleries"])


def _same_origin(request: Request) -> bool:
    origin = str(request.headers.get("origin") or "").strip()
    if not origin:
        return True
    hostname = urlsplit(origin).hostname
    return hostname in {"127.0.0.1", "localhost", "::1"}


def _require_local_origin(request: Request) -> None:
    if not _same_origin(request):
        raise HTTPException(status_code=403, detail="图库绑定只接受本机页面请求。")


@router.get("/settings")
def get_external_gallery_settings() -> dict:
    return {"settings": external_galleries.settings_payload()}


@router.put("/settings/{kind}")
def update_external_gallery_settings(
    kind: str,
    request: Request,
    payload: dict = Body(...),
) -> dict:
    _require_local_origin(request)
    try:
        settings = external_galleries.save_binding(
            kind,
            str(payload.get("directory") or ""),
            payload.get("confirmed_local_access") is True,
        )
    except external_galleries.ExternalGalleryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except OSError:
        raise HTTPException(
            status_code=500,
            detail="图库设置无法保存，请检查配置目录写入权限。",
        ) from None
    return {"settings": settings}


@router.delete("/settings/{kind}")
def delete_external_gallery_settings(kind: str, request: Request) -> dict:
    _require_local_origin(request)
    try:
        settings = external_galleries.clear_binding(kind)
    except external_galleries.ExternalGalleryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except OSError:
        raise HTTPException(
            status_code=500,
            detail="图库设置无法保存，请检查配置目录写入权限。",
        ) from None
    return {"settings": settings}


@router.get("/{kind}/catalogue")
def get_external_gallery_catalogue(kind: str) -> dict:
    try:
        return external_galleries.catalogue_for(kind)
    except external_galleries.ExternalGalleryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.post("/{kind}/refresh")
def refresh_external_gallery_catalogue(kind: str) -> dict:
    try:
        return external_galleries.synchronize_managed(kind)
    except external_galleries.ExternalGalleryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/{kind}/sync")
def sync_external_gallery(kind: str) -> dict:
    try:
        return external_galleries.synchronize_managed(kind)
    except external_galleries.ExternalGalleryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.post("/{kind}/assets/{asset_id}/favorite")
def toggle_external_gallery_favorite(kind: str, asset_id: int) -> dict:
    try:
        return external_galleries.toggle_managed_favorite(kind, asset_id)
    except external_galleries.ExternalGalleryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.post("/{kind}/assets/{asset_id}/use")
def record_external_gallery_use(kind: str, asset_id: int) -> dict:
    try:
        return external_galleries.record_managed_use(kind, asset_id)
    except external_galleries.ExternalGalleryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.put("/{kind}/assets/{asset_id}/pose-link")
def link_external_gallery_pose(
    kind: str,
    asset_id: int,
    payload: dict = Body(...),
) -> dict:
    try:
        return external_galleries.link_managed_pose(
            kind,
            asset_id,
            str(payload.get("pose_preset_id") or ""),
        )
    except external_galleries.ExternalGalleryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/{kind}/assets/{asset_id}")
def get_external_gallery_asset(
    kind: str,
    asset_id: int,
    variant: str = Query(default="original"),
) -> FileResponse:
    try:
        path = external_galleries.managed_image_path(kind, asset_id, variant)
    except external_galleries.ExternalGalleryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return FileResponse(
        path,
        media_type=external_galleries.MIME_BY_SUFFIX.get(
            path.suffix.lower(),
            "application/octet-stream",
        ),
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{kind}/image")
def get_external_gallery_image(
    kind: str,
    relative_path: str = Query(alias="path"),
    variant: str = Query(default="original"),
    manifest_thumbnail: str = Query(default="", alias="thumb_path"),
) -> FileResponse:
    try:
        path = external_galleries.image_path_for(
            kind,
            relative_path,
            variant,
            manifest_thumbnail,
        )
    except external_galleries.ExternalGalleryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    media_type = external_galleries.MIME_BY_SUFFIX.get(
        path.suffix.lower(),
        "application/octet-stream",
    )
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )
