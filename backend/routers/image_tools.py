"""Local image utility endpoints that never call external services."""
from __future__ import annotations

import base64
import json
import threading

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

import config
import comic_text
import image_deobfuscation

router = APIRouter(prefix="/api/image-tools", tags=["image-tools"])

_PROCESSING_SLOTS = threading.BoundedSemaphore(
    max(1, config.IMAGE_DEOBFUSCATION_MAX_CONCURRENCY)
)
_COMIC_SLOT = threading.BoundedSemaphore(1)


def _report_header(report: dict) -> str:
    encoded = json.dumps(
        report,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


@router.post(
    "/deobfuscate",
    response_class=Response,
    responses={
        200: {"content": {"image/png": {}}},
        400: {"description": "Image cannot be decoded"},
        413: {"description": "Image exceeds size or pixel limits"},
        422: {"description": "Image does not look obfuscated"},
        429: {"description": "Another image is being processed"},
    },
)
def deobfuscate_image(
    file: UploadFile = File(...),
    force: bool = Query(False),
) -> Response:
    """Decode a Xiaofanqie image in local memory and return a PNG."""
    if not _PROCESSING_SLOTS.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="已有图片正在解混淆，请稍后重试",
        )
    try:
        data = file.file.read(config.IMAGE_DEOBFUSCATION_MAX_BYTES + 1)
        try:
            result = image_deobfuscation.decode_image(data, force=force)
        except image_deobfuscation.ImageDeobfuscationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    finally:
        _PROCESSING_SLOTS.release()

    headers = {
        "Cache-Control": "no-store",
        "Content-Disposition": 'attachment; filename="deobfuscated.png"',
        "X-Content-Type-Options": "nosniff",
        "X-Image-Tool-Report": _report_header(result.report),
    }
    return Response(
        content=result.image_bytes,
        media_type="image/png",
        headers=headers,
    )


@router.get("/comic/capabilities")
def comic_capabilities() -> dict:
    return comic_text.capabilities()


@router.post("/comic/parse")
def parse_comic_script(payload: dict) -> dict:
    return comic_text.parse_script(
        str(payload.get("raw_prompt") or ""),
        str(payload.get("base_bubble_description") or ""),
    )


@router.post(
    "/comic/render",
    response_class=Response,
    responses={
        200: {"content": {"image/png": {}}},
        400: {"description": "Invalid image, font or text box"},
        413: {"description": "Image exceeds size or pixel limits"},
        429: {"description": "Another comic image is being rendered"},
    },
)
def render_comic_text(
    file: UploadFile = File(...),
    boxes_json: str = Query(...),
    font_id: str = Query(...),
) -> Response:
    if not _COMIC_SLOT.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="已有漫画文字正在生成，请稍后重试")
    try:
        data = file.file.read(config.COMIC_TEXT_MAX_BYTES + 1)
        try:
            boxes = json.loads(boxes_json)
            if not isinstance(boxes, list):
                raise ValueError("boxes_json 必须是数组")
            image_bytes, report = comic_text.render_text(data, boxes, font_id)
        except (json.JSONDecodeError, ValueError) as exc:
            if isinstance(exc, comic_text.ComicTextError):
                raise HTTPException(
                    status_code=exc.status_code,
                    detail=str(exc),
                ) from exc
            raise HTTPException(status_code=400, detail="文字框 JSON 格式不正确") from exc
    finally:
        _COMIC_SLOT.release()
    return Response(
        content=image_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="comic-text.png"',
            "X-Content-Type-Options": "nosniff",
            "X-Image-Tool-Report": _report_header(report),
        },
    )


@router.post("/comic/detect-bubbles")
def detect_comic_bubbles(
    file: UploadFile = File(...),
    white_threshold: int = Query(220, ge=1, le=255),
    min_area: int = Query(5000, ge=100, le=1_000_000),
    invert: bool = Query(False),
) -> dict:
    data = file.file.read(config.COMIC_TEXT_MAX_BYTES + 1)
    try:
        return comic_text.detect_bubbles(
            data,
            white_threshold=white_threshold,
            min_area=min_area,
            invert=invert,
        )
    except comic_text.ComicTextError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
