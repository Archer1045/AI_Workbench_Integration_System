"""Storyboard slicing and lossless-compatible video merge helpers."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError

import config


GRID_SIZES = {
    4: (2, 2),
    6: (2, 3),
    9: (3, 3),
}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
VIDEO_MIME_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}


class StoryboardToolError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _load_image(data: bytes) -> Image.Image:
    if len(data) > config.STORYBOARD_MAX_BYTES:
        raise StoryboardToolError(
            f"分镜图不能超过 {config.STORYBOARD_MAX_BYTES / 1024 / 1024:g} MB。",
            413,
        )
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if (opened.format or "").upper() not in {"PNG", "JPEG", "WEBP"}:
                raise StoryboardToolError("分镜图只支持 PNG/JPEG/WebP。")
            opened.load()
            image = ImageOps.exif_transpose(opened).copy()
    except StoryboardToolError:
        raise
    except (UnidentifiedImageError, OSError):
        raise StoryboardToolError("分镜图格式无法识别。") from None
    if image.width * image.height > config.STORYBOARD_MAX_PIXELS:
        raise StoryboardToolError(
            f"分镜图像素数不能超过 {config.STORYBOARD_MAX_PIXELS:,}。",
            413,
        )
    return image.convert("RGBA")


def _boundaries(length: int, count: int) -> list[int]:
    return [round(index * length / count) for index in range(count + 1)]


def slice_storyboard(
    image_bytes: bytes,
    source_name: str,
    grid: int,
    crop_margin: int = 0,
) -> tuple[bytes, dict[str, Any]]:
    if grid not in GRID_SIZES:
        raise StoryboardToolError("网格只支持 4、6 或 9 格。")
    margin = int(crop_margin)
    if margin < 0 or margin > config.STORYBOARD_CROP_MARGIN_MAX:
        raise StoryboardToolError(
            f"裁剪边距必须在 0-{config.STORYBOARD_CROP_MARGIN_MAX} px。"
        )
    image = _load_image(image_bytes)
    rows, columns = GRID_SIZES[grid]
    row_edges = _boundaries(image.height, rows)
    column_edges = _boundaries(image.width, columns)
    cells: list[dict[str, Any]] = []
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        order = 0
        for row in range(rows):
            for column in range(columns):
                order += 1
                left = column_edges[column]
                top = row_edges[row]
                right = column_edges[column + 1]
                bottom = row_edges[row + 1]
                crop_left = left + margin
                crop_top = top + margin
                crop_right = right - margin
                crop_bottom = bottom - margin
                if crop_right <= crop_left or crop_bottom <= crop_top:
                    raise StoryboardToolError(
                        "裁剪边距过大，切出的单元没有有效像素。"
                    )
                cell = image.crop((crop_left, crop_top, crop_right, crop_bottom))
                filename = f"cells/r{row + 1}c{column + 1}.png"
                cell_buffer = io.BytesIO()
                cell.save(cell_buffer, format="PNG")
                archive.writestr(filename, cell_buffer.getvalue())
                cells.append(
                    {
                        "order": order,
                        "row": row + 1,
                        "column": column + 1,
                        "x": crop_left,
                        "y": crop_top,
                        "width": cell.width,
                        "height": cell.height,
                        "file": filename,
                    }
                )
        manifest = {
            "version": 1,
            "source_name": Path(source_name or "storyboard").name,
            "source_sha256": hashlib.sha256(image_bytes).hexdigest(),
            "source_width": image.width,
            "source_height": image.height,
            "grid": grid,
            "rows": rows,
            "columns": columns,
            "crop_margin": margin,
            "cell_count": len(cells),
            "cells": cells,
        }
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
    return output.getvalue(), manifest


def ffmpeg_path() -> Path:
    configured = str(os.environ.get("FFMPEG_EXE") or "").strip()
    candidates = [Path(configured)] if configured else []
    discovered = shutil.which("ffmpeg")
    if discovered:
        candidates.append(Path(discovered))
    binary_dir = config.COMFY_DIR / "venv" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries"
    if binary_dir.is_dir():
        candidates.extend(sorted(binary_dir.glob("ffmpeg*.exe")))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise StoryboardToolError(
        "未找到 FFmpeg。请先确认 ComfyUI 的 imageio-ffmpeg 或系统 FFmpeg 可用。",
        503,
    )


def _decode_output(data: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def probe_video(path: Path, display_name: str = "") -> dict[str, Any]:
    try:
        process = subprocess.run(
            [str(ffmpeg_path()), "-hide_banner", "-i", str(path)],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StoryboardToolError(f"读取视频信息失败：{exc}", 422) from exc
    text = _decode_output(process.stderr)
    duration_match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
        text,
    )
    video_match = None
    audio_match = None
    for line in text.splitlines():
        if "Stream #" not in line:
            continue
        if " Video: " in line and video_match is None:
            codec = re.search(r"Video:\s*([^\s,]+)", line)
            dimensions = re.search(r"(\d{2,5})x(\d{2,5})(?:[\s,\[]|$)", line)
            fps = re.search(r"(\d+(?:\.\d+)?)\s+fps", line)
            if codec and dimensions:
                video_match = {
                    "codec": codec.group(1),
                    "width": int(dimensions.group(1)),
                    "height": int(dimensions.group(2)),
                    "fps": float(fps.group(1)) if fps else 0.0,
                }
        elif " Audio: " in line and audio_match is None:
            codec = re.search(r"Audio:\s*([^\s,]+)", line)
            sample_rate = re.search(r"(\d+)\s+Hz", line)
            layout = re.search(
                r"Hz,\s*([^,\n]+?)(?:,\s*\d+\s+kb/s|$)",
                line,
            )
            audio_match = {
                "codec": codec.group(1) if codec else "",
                "sample_rate": int(sample_rate.group(1)) if sample_rate else 0,
                "layout": layout.group(1).strip() if layout else "",
            }
    if video_match is None:
        raise StoryboardToolError(f"无法读取视频流：{path.name}", 422)
    return {
        "name": display_name or path.name,
        "duration": (
            int(duration_match.group(1)) * 3600
            + int(duration_match.group(2)) * 60
            + float(duration_match.group(3))
            if duration_match
            else 0.0
        ),
        "video": video_match,
        "audio": audio_match,
        "bytes": path.stat().st_size,
    }


def _compatibility_report(items: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[str] = []
    reference = items[0]
    for item in items[1:]:
        for key in ("width", "height", "codec"):
            if item["video"][key] != reference["video"][key]:
                issues.append(
                    f"{item['name']} 的视频 {key} 与首段不一致。"
                )
        if abs(item["video"]["fps"] - reference["video"]["fps"]) > 0.05:
            issues.append(f"{item['name']} 的帧率与首段不一致。")
        if bool(item["audio"]) != bool(reference["audio"]):
            issues.append(f"{item['name']} 的音轨存在性与首段不一致。")
        elif item["audio"]:
            for key in ("codec", "sample_rate", "layout"):
                if item["audio"][key] != reference["audio"][key]:
                    issues.append(
                        f"{item['name']} 的音频 {key} 与首段不一致。"
                    )
    video_codec = str(reference["video"]["codec"]).casefold()
    audio_codec = str((reference["audio"] or {}).get("codec") or "").casefold()
    if video_codec in {"h264", "hevc"} and audio_codec in {"", "aac", "mp3"}:
        output_format = "mp4"
    elif video_codec in {"vp9", "av1"} and audio_codec in {"", "opus", "vorbis"}:
        output_format = "webm"
    else:
        output_format = "mkv"
        issues.append(
            "当前编码组合不能可靠无损封装为浏览器可预览的 MP4/WebM；"
            "需转码后再合并。",
        )
    return {
        "compatible": not issues,
        "issues": issues,
        "output_format": output_format,
        "files": items,
        "total_duration": sum(float(item["duration"]) for item in items),
    }


def _write_upload(upload: Any, path: Path) -> int:
    size = 0
    with path.open("wb") as target:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > config.VIDEO_MERGE_MAX_BYTES:
                raise StoryboardToolError(
                    f"{upload.filename or path.name} 超过单文件大小上限。",
                    413,
                )
            target.write(chunk)
    return size


def prepare_uploaded_videos(
    uploads: list[Any],
) -> tuple[tempfile.TemporaryDirectory[str], list[tuple[Path, str]]]:
    if len(uploads) < 2:
        raise StoryboardToolError("至少需要两个视频片段。")
    if len(uploads) > config.VIDEO_MERGE_MAX_FILES:
        raise StoryboardToolError(
            f"一次最多合并 {config.VIDEO_MERGE_MAX_FILES} 个片段。"
        )
    temporary = tempfile.TemporaryDirectory(prefix="rider-video-merge-")
    root = Path(temporary.name)
    paths: list[tuple[Path, str]] = []
    try:
        for index, upload in enumerate(uploads, start=1):
            suffix = Path(upload.filename or "").suffix.lower()
            if suffix not in VIDEO_SUFFIXES:
                raise StoryboardToolError(
                    f"{upload.filename or '视频'} 格式不受支持。"
                )
            path = root / f"segment_{index:02d}{suffix}"
            _write_upload(upload, path)
            if path.stat().st_size == 0:
                raise StoryboardToolError(
                    f"{upload.filename or '视频'} 是空文件。"
                )
            paths.append((path, upload.filename or path.name))
        return temporary, paths
    except Exception:
        temporary.cleanup()
        raise


def preflight_videos(
    paths: list[tuple[Path, str]],
) -> dict[str, Any]:
    return _compatibility_report(
        [probe_video(path, display_name) for path, display_name in paths]
    )


def merge_videos(
    paths: list[tuple[Path, str]],
    output_dir: Path | None = None,
) -> dict[str, Any]:
    report = preflight_videos(paths)
    if not report["compatible"]:
        raise StoryboardToolError(
            "视频不兼容，未执行合并：" + "；".join(report["issues"]),
            422,
        )
    suffix = f".{report['output_format']}"
    destination = output_dir or config.VIDEO_MERGE_OUTPUT_DIR
    destination.mkdir(parents=True, exist_ok=True)
    output_id = os.urandom(8).hex()
    output_path = destination / f"video_merge_{output_id}{suffix}"
    concat_file = paths[0][0].parent / "concat.txt"
    concat_file.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path, _name in paths),
        encoding="utf-8",
    )
    command = [
        str(ffmpeg_path()),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
    ]
    if suffix == ".mp4":
        command.extend(["-movflags", "+faststart"])
    command.append(str(output_path))
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        output_path.unlink(missing_ok=True)
        raise StoryboardToolError(f"视频合并失败：{exc}", 422) from exc
    if process.returncode != 0 or not output_path.is_file():
        output_path.unlink(missing_ok=True)
        detail = _decode_output(process.stderr).strip()
        raise StoryboardToolError(
            "FFmpeg 合并失败：" + (detail[-800:] or "未知错误"),
            422,
        )
    return {
        "filename": output_path.name,
        "url": (
            f"/api/video/file/{output_path.name}"
            if output_dir is not None
            else f"/api/storyboard/merges/{output_path.name}"
        ),
        "format": report["output_format"],
        "bytes": output_path.stat().st_size,
        "total_duration": report["total_duration"],
        "files": report["files"],
    }
