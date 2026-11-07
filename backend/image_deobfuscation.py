"""Lossless Xiaofanqie (generalized Gilbert-curve) image transforms."""
from __future__ import annotations

import hashlib
import io
import math
import sys
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

import config

ALGORITHM_ID = "xiaofanqie-gilbert-v1"


class ImageDeobfuscationError(ValueError):
    """Raised when an uploaded image cannot be decoded or processed."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ImageTransformResult:
    image_bytes: bytes
    report: dict
    width: int
    height: int
    roughness_before: float
    roughness_after: float
    roughness_ratio: float
    accepted: bool


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


def _generate_curve(
    x: int,
    y: int,
    ax: int,
    ay: int,
    bx: int,
    by: int,
    width: int,
    output: list[int],
) -> None:
    w = abs(ax + ay)
    h = abs(bx + by)
    dax, day = _sign(ax), _sign(ay)
    dbx, dby = _sign(bx), _sign(by)
    if h == 1:
        for _ in range(w):
            output.append(x + y * width)
            x += dax
            y += day
        return
    if w == 1:
        for _ in range(h):
            output.append(x + y * width)
            x += dbx
            y += dby
        return

    ax2, ay2 = ax // 2, ay // 2
    bx2, by2 = bx // 2, by // 2
    w2 = abs(ax2 + ay2)
    h2 = abs(bx2 + by2)
    if 2 * w > 3 * h:
        if (w2 % 2) and w > 2:
            ax2 += dax
            ay2 += day
        _generate_curve(x, y, ax2, ay2, bx, by, width, output)
        _generate_curve(
            x + ax2,
            y + ay2,
            ax - ax2,
            ay - ay2,
            bx,
            by,
            width,
            output,
        )
        return

    if (h2 % 2) and h > 2:
        bx2 += dbx
        by2 += dby
    _generate_curve(x, y, bx2, by2, ax2, ay2, width, output)
    _generate_curve(
        x + bx2,
        y + by2,
        ax,
        ay,
        bx - bx2,
        by - by2,
        width,
        output,
    )
    _generate_curve(
        x + (ax - dax) + (bx2 - dbx),
        y + (ay - day) + (by2 - dby),
        -bx2,
        -by2,
        -(ax - ax2),
        -(ay - ay2),
        width,
        output,
    )


def _curve_indices(width: int, height: int) -> np.ndarray:
    if width <= 0 or height <= 0:
        raise ImageDeobfuscationError("图片尺寸无效")
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 20_000))
    output: list[int] = []
    if width >= height:
        _generate_curve(0, 0, width, 0, 0, height, width, output)
    else:
        _generate_curve(0, 0, 0, height, width, 0, width, output)
    return np.asarray(output, dtype=np.int64)


@lru_cache(maxsize=8)
def _cached_curve_indices(width: int, height: int) -> np.ndarray:
    return _curve_indices(width, height)


def curve_indices(width: int, height: int) -> np.ndarray:
    """Return row-major pixel indices in generalized Gilbert-curve order."""
    if width * height <= config.IMAGE_DEOBFUSCATION_CURVE_CACHE_MAX_PIXELS:
        return _cached_curve_indices(width, height)
    return _curve_indices(width, height)


def curve_offset(pixel_count: int) -> int:
    return math.floor((math.sqrt(5) - 1) / 2 * pixel_count + 0.5)


def roughness(image: np.ndarray) -> float:
    values = image.astype(np.int16)
    if values.ndim == 3:
        values = values[:, :, :3]
    dx = float(np.abs(np.diff(values, axis=1)).mean()) if values.shape[1] > 1 else 0.0
    dy = float(np.abs(np.diff(values, axis=0)).mean()) if values.shape[0] > 1 else 0.0
    return (dx + dy) / 2


def transform_array(image: np.ndarray, operation: str) -> np.ndarray:
    if operation not in {"decode", "encode"}:
        raise ValueError(operation)
    height, width = image.shape[:2]
    indices = curve_indices(width, height)
    if indices.size != width * height:
        raise ImageDeobfuscationError("Gilbert 曲线像素数不匹配")
    offset = curve_offset(indices.size)
    flat = image.reshape(width * height, -1)
    output = np.empty_like(flat)
    if operation == "decode":
        output[indices[:-offset]] = flat[indices[offset:]]
        output[indices[-offset:]] = flat[indices[:offset]]
    else:
        output[indices[offset:]] = flat[indices[:-offset]]
        output[indices[:offset]] = flat[indices[-offset:]]
    return output.reshape(image.shape)


def _open_image(data: bytes) -> tuple[Image.Image, str]:
    if not data:
        raise ImageDeobfuscationError("图片内容为空", status_code=400)
    try:
        with Image.open(io.BytesIO(data)) as probe:
            width, height = probe.size
            source_format = str(probe.format or "").upper()
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageDeobfuscationError("图片无法解码或格式不受支持", status_code=400) from exc
    if width <= 0 or height <= 0:
        raise ImageDeobfuscationError("图片尺寸无效")
    if width * height > config.IMAGE_DEOBFUSCATION_MAX_PIXELS:
        raise ImageDeobfuscationError(
            f"图片像素超过限制：{config.IMAGE_DEOBFUSCATION_MAX_PIXELS}",
            status_code=413,
        )
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageDeobfuscationError("图片无法读取", status_code=400) from exc
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    return image, source_format


def _process(
    data: bytes,
    *,
    operation: str,
    force: bool,
) -> ImageTransformResult:
    if len(data) > config.IMAGE_DEOBFUSCATION_MAX_BYTES:
        raise ImageDeobfuscationError("图片文件超过大小限制", status_code=413)
    image, source_format = _open_image(data)
    original = np.asarray(image)
    before = roughness(original)
    transformed = transform_array(original, operation)
    after = roughness(transformed)
    ratio = after / before if before > 0 else 1.0
    accepted = ratio <= config.IMAGE_DEOBFUSCATION_ROUGHNESS_RATIO_MAX
    if operation == "decode":
        accepted = accepted and (before - after) >= config.IMAGE_DEOBFUSCATION_MIN_ROUGHNESS_DROP
    output_image = Image.fromarray(transformed, mode=image.mode)
    output = io.BytesIO()
    save_options: dict[str, object] = {"format": "PNG", "compress_level": 6}
    if image.info.get("icc_profile"):
        save_options["icc_profile"] = image.info["icc_profile"]
    output_image.save(output, **save_options)
    result_bytes = output.getvalue()
    report = {
        "algorithm": ALGORITHM_ID,
        "operation": operation,
        "source_format": source_format,
        "width": image.width,
        "height": image.height,
        "mode": image.mode,
        "pixel_count": image.width * image.height,
        "roughness_before": round(before, 6),
        "roughness_after": round(after, 6),
        "roughness_ratio": round(ratio, 6),
        "accepted": accepted,
        "forced": bool(force),
        "input_sha256": hashlib.sha256(data).hexdigest().upper(),
        "output_sha256": hashlib.sha256(result_bytes).hexdigest().upper(),
    }
    if operation == "decode" and not accepted and not force:
        raise ImageDeobfuscationError(
            "解混淆后粗糙度未明显下降，可能不是小番茄混淆图",
            status_code=422,
        )
    return ImageTransformResult(
        image_bytes=result_bytes,
        report=report,
        width=image.width,
        height=image.height,
        roughness_before=before,
        roughness_after=after,
        roughness_ratio=ratio,
        accepted=accepted,
    )


def decode_image(data: bytes, *, force: bool = False) -> ImageTransformResult:
    return _process(data, operation="decode", force=force)


def encode_image(data: bytes) -> ImageTransformResult:
    """Encode a normal image for compatibility and round-trip testing."""
    return _process(data, operation="encode", force=True)
