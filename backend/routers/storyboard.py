"""HTTP routes for storyboard grids and compatible segment merging."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

import storyboard_tools


router = APIRouter(prefix="/api/storyboard", tags=["storyboard"])


def _report_header(report: dict) -> str:
    encoded = json.dumps(
        report,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


@router.post(
    "/slice",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
)
def slice_storyboard_image(
    file: UploadFile = File(...),
    grid: int = Query(...),
    crop_margin: int = Query(0),
) -> Response:
    data = file.file.read(storyboard_tools.config.STORYBOARD_MAX_BYTES + 1)
    try:
        archive, report = storyboard_tools.slice_storyboard(
            data,
            file.filename or "storyboard.png",
            grid,
            crop_margin,
        )
    except storyboard_tools.StoryboardToolError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="storyboard-cells.zip"',
            "X-Image-Tool-Report": _report_header(report),
        },
    )


@router.post("/merge/preflight")
def preflight_video_merge(files: list[UploadFile] = File(...)) -> dict:
    temporary, paths = storyboard_tools.prepare_uploaded_videos(files)
    try:
        return storyboard_tools.preflight_videos(paths)
    except storyboard_tools.StoryboardToolError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    finally:
        temporary.cleanup()


@router.post("/merge")
def merge_video_segments(files: list[UploadFile] = File(...)) -> dict:
    temporary, paths = storyboard_tools.prepare_uploaded_videos(files)
    try:
        return storyboard_tools.merge_videos(paths)
    except storyboard_tools.StoryboardToolError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    finally:
        temporary.cleanup()


@router.get("/merges/{filename}")
def get_merged_video(filename: str) -> FileResponse:
    safe_name = Path(filename).name
    path = storyboard_tools.config.VIDEO_MERGE_OUTPUT_DIR / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="合并视频不存在")
    return FileResponse(
        path,
        media_type=storyboard_tools.VIDEO_MIME_TYPES.get(
            path.suffix.lower(),
            "application/octet-stream",
        ),
    )
