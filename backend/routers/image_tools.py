"""Local image utility endpoints that never call external services."""
from __future__ import annotations

import base64
import json
import threading

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

import config
import image_deobfuscation

router = APIRouter(prefix="/api/image-tools", tags=["image-tools"])

_PROCESSING_SLOTS = threading.BoundedSemaphore(
    max(1, config.IMAGE_DEOBFUSCATION_MAX_CONCURRENCY)
)


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
