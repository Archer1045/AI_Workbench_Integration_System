"""Preset thumbnail workshop storage, image processing, and public sync."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

import config
import database
import preset_registry


IMAGE_EXTENSIONS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}
MIME_TYPES = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}
ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
ACTIVE_CANDIDATE_STATUSES = {
    "queued",
    "preparing",
    "running",
    "cancel_requested",
    "ready",
    "cancelled",
    "interrupted",
    "failed",
}
CATALOG_TASK_STATUSES = (
    "queued",
    "preparing",
    "running",
    "cancel_requested",
    "done",
    "failed",
    "cancelled",
    "interrupted",
)
CATALOG_TASK_STATUS_LABELS = {
    "queued": "排队中",
    "preparing": "准备中",
    "running": "生成中",
    "cancel_requested": "取消中",
    "done": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
    "interrupted": "已中断",
}
SAFE_STATUSES = {"ready", "adopted", "discarded", "failed", "interrupted"}
CATALOG_RESOURCE_FILTERS = {
    "all",
    "with-image",
    "without-image",
    "with-source",
    "without-source",
    "with-candidate",
    "ready",
    "running",
    "failed",
}
CATALOG_SORTS = {"default", "name", "updated_at"}
CANDIDATE_JOB_ITEM_INDEX_PARAM = "_preset_asset_job_item_index"


class PresetAssetError(RuntimeError):
    """Domain error mapped to an HTTP response by the router."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class _PresetAssetWriteLeaseLost(PresetAssetError):
    """Raised internally when a formal-asset write lease is no longer owned."""

    def __init__(self) -> None:
        super().__init__(
            "正式素材写入租约已失效，已停止继续写入",
            status_code=409,
        )


class _PresetAssetWriteLeaseGuard:
    """Keep a database lease alive and verify ownership around file writes."""

    TTL_SECONDS = 900
    RENEW_INTERVAL_SECONDS = 60

    def __init__(self, preset_type: str, preset_id: str, owner_token: str) -> None:
        self.preset_type = preset_type
        self.preset_id = preset_id
        self.owner_token = owner_token
        self._lost = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._renew_loop,
            name=f"preset-asset-lease-{self.preset_type}-{self.preset_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def assert_owned(self) -> None:
        if self._lost.is_set():
            raise _PresetAssetWriteLeaseLost()
        renewed = database.renew_preset_asset_write_lease(
            self.preset_type,
            self.preset_id,
            self.owner_token,
            ttl_seconds=self.TTL_SECONDS,
        )
        if not renewed:
            self._lost.set()
            raise _PresetAssetWriteLeaseLost()

    def _renew_loop(self) -> None:
        interval = max(1, min(self.RENEW_INTERVAL_SECONDS, self.TTL_SECONDS // 3))
        while not self._stop.wait(interval):
            if not database.renew_preset_asset_write_lease(
                self.preset_type,
                self.preset_id,
                self.owner_token,
                ttl_seconds=self.TTL_SECONDS,
            ):
                self._lost.set()
                return


def _now() -> str:
    return database.now_iso()


def _safe_name(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise PresetAssetError("非法预设 ID", status_code=400)
    return value


def resolve_preset(preset_type: str, preset_id: str) -> dict[str, Any]:
    """Resolve a preset only through the central registry."""
    definition = preset_registry.PRESET_KIND_BY_KEY.get(str(preset_type or ""))
    if not definition:
        raise PresetAssetError("未知的预设类型", status_code=400)
    safe_id = _safe_name(str(preset_id or ""))
    for preset in definition.list_loader():
        if str(preset.get("id") or "") == safe_id:
            return dict(preset)
    raise PresetAssetError("预设不存在", status_code=404)


def preset_is_restricted(preset: dict[str, Any]) -> bool:
    rating = str(preset.get("rating") or "").upper()
    return rating == "R18" or bool(preset.get("nsfw"))


def preset_label(preset_type: str, preset_id: str) -> str:
    """Return a stable label for task payloads without a catalog dependency."""
    definition = preset_registry.PRESET_KIND_BY_KEY.get(str(preset_type or ""))
    safe_id = str(preset_id or "")
    if definition and safe_id:
        for preset in definition.list_loader():
            if str(preset.get("id") or "") == safe_id:
                return str(preset.get("label") or safe_id)
    return safe_id


def ensure_restricted_access(
    preset_type: str,
    preset_id: str,
    restriction: bool,
) -> dict[str, Any]:
    """Resolve a preset and enforce the current R18 content restriction."""
    preset = resolve_preset(preset_type, preset_id)
    if restriction and preset_is_restricted(preset):
        raise PresetAssetError("当前内容限制下不可访问该预设", status_code=403)
    return preset


def target_for(preset_type: str) -> dict[str, Any]:
    target = config.PRESET_ASSET_TARGETS.get(preset_type)
    if not target:
        raise PresetAssetError("未知的预设类型", status_code=400)
    return target


def _candidate_preset_version(candidate: dict[str, Any]) -> int | None:
    params = candidate.get("params")
    if not isinstance(params, dict):
        return None
    raw_version = params.get("preset_version")
    if candidate.get("generation_mode") == "crop":
        nested = params.get("params")
        if isinstance(nested, dict) and nested.get("preset_version") is not None:
            raw_version = nested.get("preset_version")
    try:
        version = int(raw_version)
    except (TypeError, ValueError):
        return None
    return version if version > 0 else None


def _assert_current_character_version(candidate: dict[str, Any]) -> None:
    if str(candidate.get("preset_type") or "") != "character":
        return
    preset = resolve_preset("character", str(candidate.get("preset_id") or ""))
    current_version = int(preset.get("version") or 1)
    if _candidate_preset_version(candidate) != current_version:
        raise PresetAssetError(
            "角色预设已更新或候选缺少版本信息，请基于当前版本重新生成缩略图",
            status_code=409,
        )


def _asset_paths(preset_type: str, preset_id: str) -> tuple[Path, Path]:
    definition = preset_registry.PRESET_KIND_BY_KEY[preset_type]
    extension = definition.image_extension
    public_root = config.PROJECT_ROOT / "studio" / "frontend" / "public"
    dist_root = config.PROJECT_ROOT / "studio" / "frontend" / "dist"
    return (
        public_root / definition.image_directory / f"{preset_id}.{extension}",
        dist_root / definition.image_directory / f"{preset_id}.{extension}",
    )


def _managed_root(*parts: str) -> Path:
    root = Path(config.PRESET_ASSET_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    path = root.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ensure_under(path: Path, parent: Path) -> Path:
    resolved = path.resolve()
    if parent.resolve() not in resolved.parents and resolved != parent.resolve():
        raise PresetAssetError("文件路径超出受控目录", status_code=400)
    return resolved


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _detect_format(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    raise PresetAssetError("仅支持 PNG、JPEG、WebP 图片", status_code=415)


def validate_image_bytes(data: bytes, *, mime_type: str | None = None) -> dict[str, Any]:
    """Validate magic bytes, dimensions, EXIF, and decode safety."""
    if not data:
        raise PresetAssetError("图片内容为空", status_code=400)
    if len(data) > config.PRESET_ASSET_UPLOAD_MAX_BYTES:
        raise PresetAssetError("图片超过 20 MB 限制", status_code=413)
    detected = _detect_format(data)
    if mime_type and str(mime_type).lower().split(";", 1)[0] not in ALLOWED_MIME_TYPES:
        raise PresetAssetError("不允许的图片 MIME 类型", status_code=415)
    if mime_type and MIME_TYPES[detected] != str(mime_type).lower().split(";", 1)[0]:
        raise PresetAssetError("图片扩展名或 MIME 与内容不一致", status_code=415)
    try:
        with Image.open(io.BytesIO(data)) as probe:
            width, height = probe.size
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise PresetAssetError("图片无法解码或已损坏", status_code=400) from exc
    if width <= 0 or height <= 0:
        raise PresetAssetError("图片尺寸无效", status_code=400)
    if width * height > config.PRESET_ASSET_UPLOAD_MAX_PIXELS:
        raise PresetAssetError("图片像素超过 20 MP 限制", status_code=413)
    return {
        "format": detected,
        "mime_type": MIME_TYPES[detected],
        "width": int(width),
        "height": int(height),
        "sha256": _sha256_bytes(data),
    }


def _open_image_bytes(data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image.load()
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        return image
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise PresetAssetError("图片无法解码或已损坏", status_code=400) from exc


def _open_image_path(path: Path) -> Image.Image:
    try:
        return _open_image_bytes(path.read_bytes())
    except OSError as exc:
        raise PresetAssetError("源图不存在或不可读", status_code=404) from exc


def _resize_cover(
    image: Image.Image,
    output_size: tuple[int, int],
    *,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    zoom: float = 1.0,
) -> Image.Image:
    target_w, target_h = output_size
    if target_w <= 0 or target_h <= 0:
        raise PresetAssetError("输出尺寸无效", status_code=400)
    zoom = max(0.05, min(10.0, float(zoom or 1.0)))
    focus_x = max(0.0, min(1.0, float(focus_x)))
    focus_y = max(0.0, min(1.0, float(focus_y)))
    scale = max(target_w / image.width, target_h / image.height) * zoom
    resized = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = round((resized.width - target_w) * focus_x)
    top = round((resized.height - target_h) * focus_y)
    left = max(0, min(left, max(0, resized.width - target_w)))
    top = max(0, min(top, max(0, resized.height - target_h)))
    return resized.crop((left, top, left + target_w, top + target_h))


def _resize_contain(
    image: Image.Image,
    output_size: tuple[int, int],
    *,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    zoom: float = 1.0,
) -> Image.Image:
    target_w, target_h = output_size
    if target_w <= 0 or target_h <= 0:
        raise PresetAssetError("输出尺寸无效", status_code=400)
    zoom = max(0.05, min(10.0, float(zoom or 1.0)))
    scale = min(target_w / image.width, target_h / image.height) * zoom
    resized = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    if "A" in resized.getbands():
        canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    else:
        canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
    x = round((target_w - resized.width) * max(0.0, min(1.0, float(focus_x))))
    y = round((target_h - resized.height) * max(0.0, min(1.0, float(focus_y))))
    canvas.paste(resized, (x, y))
    return canvas


def _encode_image(
    image: Image.Image,
    output_format: str,
    quality: int,
) -> tuple[bytes, str, str]:
    output_format = output_format.upper()
    if output_format not in IMAGE_EXTENSIONS:
        raise PresetAssetError("不支持的输出格式", status_code=400)
    if output_format == "PNG":
        image = image.convert("RGBA") if "A" in image.getbands() else image.convert("RGB")
        options = {"optimize": True}
    elif output_format == "WEBP":
        image = image.convert("RGBA") if "A" in image.getbands() else image.convert("RGB")
        options = {"quality": max(1, min(100, int(quality or 90))), "method": 6}
    else:
        image = image.convert("RGB")
        options = {"quality": max(1, min(100, int(quality or 90))), "optimize": True}
    buffer = io.BytesIO()
    image.save(buffer, format=output_format, **options)
    return buffer.getvalue(), MIME_TYPES[output_format], IMAGE_EXTENSIONS[output_format]


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    data = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_write(path, data)


def settings_payload() -> dict[str, Any]:
    stored = database.get_preset_asset_setting("defaults") or {}
    if stored.get("style_positive") == config.DRAW_DEFAULT_PROMPT:
        stored = {
            **stored,
            "style_positive": config.PRESET_ASSET_DEFAULT_STYLE_POSITIVE,
        }
        database.set_preset_asset_setting("defaults", stored)
        database.add_preset_asset_audit(
            "settings_migrated",
            detail={"keys": ["style_positive"]},
        )
    merged = {**config.PRESET_ASSET_DEFAULT_SETTINGS, **stored}
    targets = {
        kind: {
            **target,
            "generation_size": list(target["generation_size"]),
            "output_size": list(target["output_size"]),
        }
        for kind, target in config.PRESET_ASSET_TARGETS.items()
    }
    return {
        "defaults": _sanitize_settings(merged),
        "targets": targets,
        "limits": {
            "candidate_min": config.PRESET_ASSET_CANDIDATE_MIN,
            "candidate_max": config.PRESET_ASSET_CANDIDATE_MAX,
            "batch_max_items": config.PRESET_ASSET_BATCH_MAX_ITEMS,
            "upload_max_bytes": config.PRESET_ASSET_UPLOAD_MAX_BYTES,
            "upload_max_pixels": config.PRESET_ASSET_UPLOAD_MAX_PIXELS,
            "width_min": config.DRAW_WIDTH_MIN,
            "width_max": config.DRAW_WIDTH_MAX,
            "height_min": config.DRAW_HEIGHT_MIN,
            "height_max": config.DRAW_HEIGHT_MAX,
            "steps_min": config.DRAW_STEPS_MIN,
            "steps_max": config.DRAW_STEPS_MAX,
            "cfg_min": config.DRAW_CFG_MIN,
            "cfg_max": config.DRAW_CFG_MAX,
            "cfg_step": config.DRAW_CFG_STEP,
            "seed_min": config.DRAW_SEED_MIN,
            "seed_max": config.DRAW_SEED_MAX,
            "focus_min": config.PRESET_ASSET_FOCUS_MIN,
            "focus_max": config.PRESET_ASSET_FOCUS_MAX,
            "focus_step": config.PRESET_ASSET_FOCUS_STEP,
            "zoom_min": config.PRESET_ASSET_ZOOM_MIN,
            "zoom_max": config.PRESET_ASSET_ZOOM_MAX,
            "zoom_step": config.PRESET_ASSET_ZOOM_STEP,
            "lora_strength_min": config.DRAW_LORA_STRENGTH_MIN,
            "lora_strength_max": config.DRAW_LORA_STRENGTH_MAX,
            "lora_strength_step": config.DRAW_LORA_STRENGTH_STEP,
        },
        "template_version": config.PRESET_ASSET_TEMPLATE_VERSION,
    }


def _sanitize_settings(value: dict[str, Any]) -> dict[str, Any]:
    defaults = dict(config.PRESET_ASSET_DEFAULT_SETTINGS)
    raw = value if isinstance(value, dict) else {}
    result = {**defaults, **raw}
    try:
        result["steps"] = max(
            config.DRAW_STEPS_MIN, min(config.DRAW_STEPS_MAX, int(result["steps"]))
        )
    except (TypeError, ValueError):
        result["steps"] = defaults["steps"]
    try:
        result["cfg"] = max(
            config.DRAW_CFG_MIN, min(config.DRAW_CFG_MAX, float(result["cfg"]))
        )
    except (TypeError, ValueError):
        result["cfg"] = defaults["cfg"]
    try:
        result["candidate_count"] = max(
            config.PRESET_ASSET_CANDIDATE_MIN,
            min(config.PRESET_ASSET_CANDIDATE_MAX, int(result["candidate_count"])),
        )
    except (TypeError, ValueError):
        result["candidate_count"] = defaults["candidate_count"]
    result["model"] = str(result.get("model") or defaults["model"])
    result["loras"] = list(
        dict.fromkeys(
            str(item).strip()
            for item in (result.get("loras") or [])
            if str(item).strip()
        )
    )
    raw_strengths = result.get("lora_strengths")
    strengths: dict[str, dict[str, float]] = {}
    if isinstance(raw_strengths, dict):
        for raw_name, raw_values in raw_strengths.items():
            name = str(raw_name).strip()
            if not name or not isinstance(raw_values, dict):
                continue
            values: dict[str, float] = {}
            for key in ("model", "clip"):
                try:
                    value = float(raw_values[key])
                except (KeyError, TypeError, ValueError):
                    continue
                if value != value or value in (float("inf"), float("-inf")):
                    continue
                values[key] = max(
                    config.DRAW_LORA_STRENGTH_MIN,
                    min(config.DRAW_LORA_STRENGTH_MAX, value),
                )
            if values:
                strengths[name] = values
    result["lora_strengths"] = strengths
    result["seed_strategy"] = (
        str(result.get("seed_strategy") or "random")
        if str(result.get("seed_strategy") or "random") in {"fixed", "random", "derive"}
        else "random"
    )
    try:
        result["seed"] = None if result.get("seed") in (None, "") else int(result["seed"])
    except (TypeError, ValueError):
        result["seed"] = None
    if result["seed"] is not None:
        result["seed"] = max(
            config.DRAW_SEED_MIN,
            min(config.DRAW_SEED_MAX, result["seed"]),
        )
    result["crop_mode"] = (
        str(result.get("crop_mode") or "cover")
        if str(result.get("crop_mode") or "cover") in {"cover", "contain"}
        else "cover"
    )
    for key, default in (("focus_x", 0.5), ("focus_y", 0.5), ("zoom", 1.0)):
        try:
            result[key] = float(result.get(key, default))
        except (TypeError, ValueError):
            result[key] = default
    result["focus_x"] = max(0.0, min(1.0, result["focus_x"]))
    result["focus_y"] = max(0.0, min(1.0, result["focus_y"]))
    result["zoom"] = max(
        config.PRESET_ASSET_ZOOM_MIN,
        min(config.PRESET_ASSET_ZOOM_MAX, result["zoom"]),
    )
    result["focus_x"] = max(
        config.PRESET_ASSET_FOCUS_MIN,
        min(config.PRESET_ASSET_FOCUS_MAX, result["focus_x"]),
    )
    result["focus_y"] = max(
        config.PRESET_ASSET_FOCUS_MIN,
        min(config.PRESET_ASSET_FOCUS_MAX, result["focus_y"]),
    )
    for key in (
        "style_positive",
        "style_negative",
        "user_positive",
        "user_negative",
    ):
        result[key] = str(result.get(key) or "")
    return result


def normalize_settings(value: dict[str, Any]) -> dict[str, Any]:
    """Public settings sanitizer used by the generation pipeline."""
    return _sanitize_settings(value)


def save_settings(value: dict[str, Any]) -> dict[str, Any]:
    cleaned = normalize_settings(value)
    database.set_preset_asset_setting("defaults", cleaned)
    database.add_preset_asset_audit("settings_updated", detail={"keys": sorted(cleaned)})
    return settings_payload()


def _source_payload(source: dict[str, Any]) -> dict[str, Any]:
    return {
        **source,
        "url": f"/api/preset-assets/sources/{source['id']}/file",
    }


def _candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    payload = dict(candidate)
    payload.pop("original_path", None)
    payload.pop("preview_path", None)
    payload.pop("thumbnail_path", None)
    params = payload.get("params")
    if isinstance(params, dict):
        payload["params"] = {
            key: value
            for key, value in params.items()
            if key != CANDIDATE_JOB_ITEM_INDEX_PARAM
        }
    payload["original_url"] = (
        f"/api/preset-assets/candidates/{candidate['id']}/file"
        if candidate.get("original_path")
        else None
    )
    payload["preview_url"] = (
        f"/api/preset-assets/candidates/{candidate['id']}/file"
        if candidate.get("preview_path")
        else None
    )
    payload["thumbnail_url"] = (
        f"/api/preset-assets/candidates/{candidate['id']}/file"
        if candidate.get("thumbnail_path")
        else None
    )
    return payload


def candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    """Public candidate serializer used by the router and task pipeline."""
    return _candidate_payload(candidate)


def _version_payload(version: dict[str, Any]) -> dict[str, Any]:
    payload = dict(version)
    payload.pop("public_path", None)
    payload.pop("dist_path", None)
    payload["url"] = f"/api/preset-assets/versions/{version['id']}/file"
    return payload


def version_payload(version: dict[str, Any]) -> dict[str, Any]:
    """Public version serializer used by task and catalog responses."""
    return _version_payload(version)


def _ensure_existing_version(preset_type: str, preset_id: str) -> dict[str, Any] | None:
    active = database.get_active_preset_asset_version(preset_type, preset_id)
    if active:
        return active
    public_path, dist_path = _asset_paths(preset_type, preset_id)
    if not public_path.is_file():
        return None
    data = public_path.read_bytes()
    metadata = validate_image_bytes(data)
    archive = _managed_root("versions", preset_type, preset_id) / (
        f"1.{IMAGE_EXTENSIONS[metadata['format']]}"
    )
    _atomic_write(archive, data)
    version_id = database.insert_preset_asset_version(
        preset_type,
        preset_id,
        1,
        None,
        str(public_path),
        str(dist_path),
        metadata["mime_type"],
        metadata["width"],
        metadata["height"],
        metadata["sha256"],
        True,
    )
    database.add_preset_asset_audit(
        "existing_version_indexed",
        preset_type,
        preset_id,
        detail={"version_id": version_id, "sha256": metadata["sha256"]},
    )
    return database.get_preset_asset_version(version_id)


def preset_summary(
    preset_type: str,
    preset_id: str,
    *,
    index_existing: bool = True,
) -> dict[str, Any]:
    preset = resolve_preset(preset_type, preset_id)
    active_version = (
        _ensure_existing_version(preset_type, preset_id)
        if index_existing
        else database.get_active_preset_asset_version(preset_type, preset_id)
    )
    source = database.get_active_preset_asset_source(preset_type, preset_id)
    candidates = database.list_preset_asset_candidates(
        preset_type, preset_id, statuses=list(ACTIVE_CANDIDATE_STATUSES), limit=200
    )
    ready_count = sum(1 for item in candidates if item.get("status") == "ready")
    running_count = sum(
        1
        for item in candidates
        if item.get("status") in {"queued", "preparing", "running", "cancel_requested"}
    )
    candidate_status_counts = {
        status: sum(
            1 for item in candidates if item.get("status") == status
        )
        for status in ACTIVE_CANDIDATE_STATUSES
    }
    image_url = None
    if active_version:
        image_url = (
            f"/{preset_registry.PRESET_KIND_BY_KEY[preset_type].image_directory}/"
            f"{preset_id}.{preset_registry.PRESET_KIND_BY_KEY[preset_type].image_extension}"
            f"?v={active_version.get('sha256', '')[:12]}"
        )
    elif (config.PROJECT_ROOT / "studio" / "frontend" / "public").joinpath(
        preset_registry.PRESET_KIND_BY_KEY[preset_type].image_directory,
        f"{preset_id}.{preset_registry.PRESET_KIND_BY_KEY[preset_type].image_extension}",
    ).is_file():
        image_url = (
            f"/{preset_registry.PRESET_KIND_BY_KEY[preset_type].image_directory}/"
            f"{preset_id}.{preset_registry.PRESET_KIND_BY_KEY[preset_type].image_extension}"
        )
    return {
        "preset_type": preset_type,
        "preset_id": preset_id,
        "label": preset.get("label") or preset_id,
        "category": preset.get("category") or "",
        "category_group": preset.get("category_group") or "",
        "subcategory": preset.get("subcategory") or "",
        "rating": preset.get("rating") or ("R18" if preset.get("nsfw") else "普通"),
        "restricted": preset_is_restricted(preset),
        "image": image_url,
        "has_image": bool(image_url),
        "active_version": _version_payload(active_version) if active_version else None,
        "source": _source_payload(source) if source else None,
        "ready_count": ready_count,
        "running_count": running_count,
        "failed_count": sum(
            1 for item in candidates if item.get("status") in {"failed", "interrupted"}
        ),
        "candidate_count": len(candidates),
        "candidate_status_counts": candidate_status_counts,
    }


def _character_thumbnail_status(
    preset: dict[str, Any],
    preset_id: str,
    active_version: dict[str, Any] | None,
    active_candidate: dict[str, Any] | None,
    *,
    static_file_exists: bool,
) -> dict[str, Any]:
    definition = preset_registry.PRESET_KIND_BY_KEY["character"]
    image_url = None
    if active_version:
        image_url = (
            f"/{definition.image_directory}/{preset_id}.{definition.image_extension}"
            f"?v={str(active_version.get('sha256') or '')[:12]}"
        )
    elif static_file_exists:
        image_url = (
            f"/{definition.image_directory}/{preset_id}.{definition.image_extension}"
        )

    thumbnail_version = (
        _candidate_preset_version(active_candidate)
        if active_candidate
        else None
    )
    current_version = int(preset.get("version") or 1)
    has_thumbnail = bool(image_url)
    return {
        "has_thumbnail": has_thumbnail,
        "thumbnail_url": image_url,
        "thumbnail_stale": has_thumbnail
        and (
            active_version is None
            or thumbnail_version != current_version
        ),
        "thumbnail_version": thumbnail_version,
        "current_preset_version": current_version,
    }


def character_thumbnail_statuses(
    preset_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Return thumbnail lifecycle state for many character presets in bulk."""
    requested_ids = list(
        dict.fromkeys(_safe_name(str(preset_id or "")) for preset_id in preset_ids)
    )
    if not requested_ids:
        return {}

    presets = {
        str(preset.get("id") or ""): dict(preset)
        for preset in preset_registry.PRESET_KIND_BY_KEY[
            "character"
        ].list_loader()
    }
    missing = [preset_id for preset_id in requested_ids if preset_id not in presets]
    if missing:
        raise PresetAssetError(
            f"角色预设不存在: {missing[0]}",
            status_code=404,
        )

    requested_set = set(requested_ids)
    active_versions = {
        str(version["preset_id"]): version
        for version in database.list_active_preset_asset_versions(["character"])
        if str(version["preset_id"]) in requested_set
    }
    candidate_ids = [
        int(version["candidate_id"])
        for version in active_versions.values()
        if version.get("candidate_id") is not None
    ]
    candidates = {
        int(candidate["id"]): candidate
        for candidate in database.list_preset_asset_candidates_by_ids(candidate_ids)
    }
    public_root = (
        Path(config.PROJECT_ROOT)
        / "studio"
        / "frontend"
        / "public"
        / preset_registry.PRESET_KIND_BY_KEY["character"].image_directory
    )

    result: dict[str, dict[str, Any]] = {}
    for preset_id in requested_ids:
        active_version = active_versions.get(preset_id)
        active_candidate = None
        if active_version and active_version.get("candidate_id") is not None:
            active_candidate = candidates.get(int(active_version["candidate_id"]))
        result[preset_id] = _character_thumbnail_status(
            presets[preset_id],
            preset_id,
            active_version,
            active_candidate,
            static_file_exists=(
                public_root / f"{preset_id}.webp"
            ).is_file(),
        )
    return result


def character_thumbnail_status(preset_id: str) -> dict[str, Any]:
    """Return read-only thumbnail lifecycle state for one character preset."""
    safe_id = _safe_name(str(preset_id or ""))
    return character_thumbnail_statuses([safe_id])[safe_id]


def _catalog_category_group(item: dict[str, Any]) -> str:
    return str(item.get("category_group") or item.get("category") or "其他")


def _catalog_subcategory(item: dict[str, Any]) -> str:
    return str(item.get("subcategory") or "其他")


def _catalog_static_image_url(
    definition: preset_registry.PresetKind,
    preset_id: str,
) -> str | None:
    public_path = (
        Path(config.PROJECT_ROOT)
        / "studio"
        / "frontend"
        / "public"
        / definition.image_directory
        / f"{preset_id}.{definition.image_extension}"
    )
    if not public_path.is_file():
        return None
    return f"/{definition.image_directory}/{preset_id}.{definition.image_extension}"


def _build_catalog_items_by_kind(restriction: bool) -> dict[str, list[dict[str, Any]]]:
    definitions: list[tuple[preset_registry.PresetKind, list[dict[str, Any]]]] = []
    preset_types: list[str] = []
    for definition in preset_registry.PRESET_KINDS:
        presets = [
            dict(preset)
            for preset in definition.list_loader()
            if not restriction or not preset_is_restricted(dict(preset))
        ]
        definitions.append((definition, presets))
        preset_types.append(definition.kind)

    versions: dict[tuple[str, str], dict[str, Any]] = {}
    for version in database.list_active_preset_asset_versions(preset_types):
        key = (str(version["preset_type"]), str(version["preset_id"]))
        versions.setdefault(key, version)

    sources: dict[tuple[str, str], dict[str, Any]] = {}
    for source in database.list_active_preset_asset_sources(preset_types):
        key = (str(source["preset_type"]), str(source["preset_id"]))
        sources.setdefault(key, source)

    aggregates: dict[tuple[str, str], dict[str, Any]] = {}
    for item in database.summarize_preset_asset_candidates(
        preset_types,
        statuses=list(ACTIVE_CANDIDATE_STATUSES),
    ):
        aggregates[
            (str(item["preset_type"]), str(item["preset_id"]))
        ] = item

    task_aggregates: dict[tuple[str, str], dict[str, Any]] = {}
    for item in database.summarize_preset_asset_job_item_statuses(
        preset_types,
        statuses=list(CATALOG_TASK_STATUSES),
    ):
        task_aggregates[
            (str(item["preset_type"]), str(item["preset_id"]))
        ] = item

    result: dict[str, list[dict[str, Any]]] = {}
    for definition, presets in definitions:
        items: list[dict[str, Any]] = []
        for index, preset in enumerate(presets):
            preset_id = str(preset["id"])
            key = (definition.kind, preset_id)
            active_version = versions.get(key)
            source = sources.get(key)
            aggregate = aggregates.get(key, {})
            task_aggregate = task_aggregates.get(key, {})
            candidate_status_counts = {
                status: 0 for status in ACTIVE_CANDIDATE_STATUSES
            }
            candidate_status_counts.update(
                {
                    str(status): int(count or 0)
                    for status, count in (
                        aggregate.get("candidate_status_counts") or {}
                    ).items()
                }
            )
            task_status_counts = {
                status: 0 for status in CATALOG_TASK_STATUSES
            }
            task_status_counts.update(
                {
                    str(status): int(count or 0)
                    for status, count in (
                        task_aggregate.get("task_status_counts") or {}
                    ).items()
                    if status in CATALOG_TASK_STATUSES
                }
            )
            task_status_updated_at = str(
                task_aggregate.get("task_status_updated_at") or ""
            )
            image_url = None
            if active_version:
                image_url = (
                    f"/{definition.image_directory}/{preset_id}."
                    f"{definition.image_extension}"
                    f"?v={str(active_version.get('sha256') or '')[:12]}"
                )
            else:
                image_url = _catalog_static_image_url(definition, preset_id)
            updated_at = max(
                (
                    str((active_version or {}).get("created_at") or ""),
                    str((source or {}).get("created_at") or ""),
                    str(aggregate.get("updated_at") or ""),
                    task_status_updated_at,
                ),
                default="",
            )
            items.append(
                {
                    "preset_type": definition.kind,
                    "preset_id": preset_id,
                    "label": str(preset.get("label") or preset_id),
                    "category": str(preset.get("category") or ""),
                    "category_group": _catalog_category_group(preset),
                    "subcategory": _catalog_subcategory(preset),
                    "rating": str(
                        preset.get("rating")
                        or ("R18" if preset.get("nsfw") else "普通")
                    ),
                    "restricted": preset_is_restricted(preset),
                    "image": image_url,
                    "has_image": bool(image_url),
                    "active_version": (
                        _version_payload(active_version)
                        if active_version
                        else None
                    ),
                    "source": _source_payload(source) if source else None,
                    "ready_count": int(aggregate.get("ready_count") or 0),
                    "running_count": int(aggregate.get("running_count") or 0),
                    "failed_count": int(aggregate.get("failed_count") or 0),
                    "candidate_count": int(
                        aggregate.get("candidate_count") or 0
                    ),
                    "candidate_status_counts": candidate_status_counts,
                    "task_status_counts": task_status_counts,
                    "task_status_updated_at": (
                        task_status_updated_at or None
                    ),
                    "updated_at": updated_at,
                    "order": index,
                    "kind_label": definition.label,
                }
            )
        result[definition.kind] = items
    return result


def dashboard_summary() -> dict[str, Any]:
    """Return read-only preset asset dashboard metrics without writing data."""
    items_by_kind = _build_catalog_items_by_kind(False)
    all_items = [
        item
        for definition in preset_registry.PRESET_KINDS
        for item in items_by_kind.get(definition.kind, [])
    ]

    def coverage(items: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(items)
        formal_count = sum(1 for item in items if item.get("has_image"))
        versioned_count = sum(1 for item in items if item.get("active_version"))
        candidate_only_count = sum(
            1
            for item in items
            if not item.get("has_image") and int(item.get("ready_count") or 0) > 0
        )
        missing_count = max(0, total - formal_count - candidate_only_count)
        return {
            "total": total,
            "formal_count": formal_count,
            "versioned_count": versioned_count,
            "candidate_only_count": candidate_only_count,
            "missing_count": missing_count,
            "formal_percent": round(formal_count / total * 100, 2) if total else 0,
            "with_candidates_percent": (
                round((formal_count + candidate_only_count) / total * 100, 2)
                if total
                else 0
            ),
        }

    candidate_status_counts: dict[str, int] = {}
    for item in all_items:
        for status, count in (item.get("candidate_status_counts") or {}).items():
            candidate_status_counts[str(status)] = (
                int(candidate_status_counts.get(str(status)) or 0)
                + int(count or 0)
            )

    template_versions: dict[str, int] = {}
    template_missing_count = 0
    preset_version_counts = {"known": 0, "missing": 0, "malformed": 0}
    for candidate in database.list_preset_asset_candidate_version_rows():
        template_version = str(candidate.get("template_version") or "").strip()
        if template_version:
            template_versions[template_version] = (
                template_versions.get(template_version, 0) + 1
            )
        else:
            template_missing_count += 1

        try:
            params = json.loads(candidate.get("params_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            preset_version_counts["malformed"] += 1
            continue
        if not isinstance(params, dict):
            preset_version_counts["malformed"] += 1
            continue
        raw_version = params.get("preset_version")
        if raw_version is None and isinstance(params.get("params"), dict):
            raw_version = params["params"].get("preset_version")
        if raw_version is None:
            preset_version_counts["missing"] += 1
            continue
        try:
            int(raw_version)
        except (TypeError, ValueError):
            preset_version_counts["malformed"] += 1
        else:
            preset_version_counts["known"] += 1

    audit_events = database.summarize_preset_asset_audit_events()
    by_kind = []
    for definition in preset_registry.PRESET_KINDS:
        kind_items = items_by_kind.get(definition.kind, [])
        by_kind.append(
            {
                "kind": definition.kind,
                "label": definition.label,
                **coverage(kind_items),
            }
        )

    return {
        **coverage(all_items),
        "candidate_count": sum(candidate_status_counts.values()),
        "candidate_status_counts": candidate_status_counts,
        "ready_count": int(candidate_status_counts.get("ready") or 0),
        "running_count": sum(
            int(candidate_status_counts.get(status) or 0)
            for status in ("queued", "preparing", "running", "cancel_requested")
        ),
        "failed_count": sum(
            int(candidate_status_counts.get(status) or 0)
            for status in ("failed", "interrupted")
        ),
        "adopted_count": int(audit_events.get("candidate_adopted") or 0),
        "rolled_back_count": int(audit_events.get("version_rolled_back") or 0),
        "discarded_count": int(audit_events.get("candidate_discarded") or 0),
        "audit_event_counts": audit_events,
        "template_versions": template_versions,
        "template_missing_count": template_missing_count,
        "preset_version_counts": preset_version_counts,
        "version_missing_count": (
            preset_version_counts["missing"] + preset_version_counts["malformed"]
        ),
        "by_kind": by_kind,
    }


def _catalog_item_matches(
    item: dict[str, Any],
    *,
    kind: str = "",
    keyword: str = "",
    resource: str = "all",
    rating: str = "",
    category_group: str = "",
    subcategory: str = "",
    candidate_status: str = "",
    task_status: str = "",
) -> bool:
    if kind and item.get("preset_type") != kind:
        return False
    if resource == "with-image" and not item.get("has_image"):
        return False
    if resource == "without-image" and item.get("has_image"):
        return False
    if resource == "with-source" and not item.get("source"):
        return False
    if resource == "without-source" and item.get("source"):
        return False
    if resource == "with-candidate" and int(item.get("candidate_count") or 0) <= 0:
        return False
    if resource == "ready" and int(item.get("ready_count") or 0) <= 0:
        return False
    if resource == "running" and int(item.get("running_count") or 0) <= 0:
        return False
    if resource == "failed" and int(item.get("failed_count") or 0) <= 0:
        return False
    if (
        candidate_status
        and int(
            (item.get("candidate_status_counts") or {}).get(
                candidate_status
            )
            or 0
        )
        <= 0
    ):
        return False
    if (
        task_status
        and int(
            (item.get("task_status_counts") or {}).get(task_status)
            or 0
        )
        <= 0
    ):
        return False
    if rating and item.get("rating") != rating:
        return False
    if category_group and _catalog_category_group(item) != category_group:
        return False
    if subcategory and _catalog_subcategory(item) != subcategory:
        return False
    normalized_keyword = keyword.strip().casefold()
    if not normalized_keyword:
        return True
    return normalized_keyword in " ".join(
        str(item.get(field) or "")
        for field in (
            "label",
            "preset_id",
            "category",
            "category_group",
            "subcategory",
            "kind_label",
        )
    ).casefold()


def _catalog_facet_items(
    items: list[dict[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(field) or "")
        if value:
            counts[value] = counts.get(value, 0) + 1
    return [
        {"value": value, "label": value, "count": count}
        for value, count in sorted(
            counts.items(),
            key=lambda entry: (-entry[1], entry[0].casefold()),
        )
    ]


def _catalog_task_status_facet_items(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        for status, count in (item.get("task_status_counts") or {}).items():
            if status not in CATALOG_TASK_STATUSES or int(count or 0) <= 0:
                continue
            counts[status] = counts.get(status, 0) + 1
    return [
        {
            "value": status,
            "label": CATALOG_TASK_STATUS_LABELS[status],
            "count": counts[status],
        }
        for status in CATALOG_TASK_STATUSES
        if counts.get(status, 0) > 0
    ]


def catalog_query(
    *,
    kind: str = "pose",
    keyword: str = "",
    resource: str = "all",
    rating: str = "",
    category_group: str = "",
    subcategory: str = "",
    candidate_status: str = "",
    task_status: str = "",
    page: int = 1,
    page_size: int = 40,
    sort: str = "default",
    restriction: bool,
) -> dict[str, Any]:
    """Return a server-filtered, paginated preset asset catalog."""
    definition = preset_registry.PRESET_KIND_BY_KEY.get(str(kind or ""))
    if not definition:
        raise PresetAssetError("未知的预设类型", status_code=400)
    normalized_resource = str(resource or "all")
    if normalized_resource not in CATALOG_RESOURCE_FILTERS:
        raise PresetAssetError("未知的资源筛选", status_code=400)
    normalized_candidate_status = str(candidate_status or "")
    if (
        normalized_candidate_status
        and normalized_candidate_status not in ACTIVE_CANDIDATE_STATUSES
    ):
        raise PresetAssetError("未知的候选状态筛选", status_code=400)
    normalized_task_status = str(task_status or "")
    if (
        normalized_task_status
        and normalized_task_status not in CATALOG_TASK_STATUSES
    ):
        raise PresetAssetError("未知的任务状态筛选", status_code=400)
    normalized_sort = str(sort or "default")
    if normalized_sort not in CATALOG_SORTS:
        raise PresetAssetError("未知的排序方式", status_code=400)
    current_page = max(1, int(page or 1))
    current_page_size = max(1, int(page_size or 40))

    items_by_kind = _build_catalog_items_by_kind(restriction)
    all_items = [
        item
        for preset_definition in preset_registry.PRESET_KINDS
        for item in items_by_kind.get(preset_definition.kind, [])
    ]
    common_filters = {
        "keyword": str(keyword or ""),
        "resource": normalized_resource,
        "rating": str(rating or ""),
        "candidate_status": normalized_candidate_status,
        "task_status": normalized_task_status,
    }
    exact_items = [
        item
        for item in all_items
        if _catalog_item_matches(
            item,
            kind=definition.kind,
            category_group=str(category_group or ""),
            subcategory=str(subcategory or ""),
            **common_filters,
        )
    ]
    if normalized_sort == "name":
        exact_items.sort(
            key=lambda item: (
                str(item.get("label") or "").casefold(),
                str(item.get("preset_id") or ""),
            )
        )
    elif normalized_sort == "updated_at":
        exact_items.sort(
            key=lambda item: (
                str(item.get("updated_at") or ""),
                str(item.get("label") or "").casefold(),
            ),
            reverse=True,
        )

    total = len(exact_items)
    total_pages = max(1, (total + current_page_size - 1) // current_page_size)
    current_page = min(current_page, total_pages)
    start = (current_page - 1) * current_page_size
    page_items = exact_items[start : start + current_page_size]

    kind_scope = [
        item
        for item in all_items
        if _catalog_item_matches(item, **common_filters)
    ]
    category_scope = [
        item
        for item in all_items
        if _catalog_item_matches(
            item,
            kind=definition.kind,
            **common_filters,
        )
    ]
    subcategory_scope = [
        item
        for item in category_scope
        if not category_group
        or _catalog_category_group(item) == str(category_group)
    ]
    task_status_scope = [
        item
        for item in all_items
        if _catalog_item_matches(
            item,
            kind=definition.kind,
            category_group=str(category_group or ""),
            subcategory=str(subcategory or ""),
            **{**common_filters, "task_status": ""},
        )
    ]
    facets = {
        "kinds": [
            {
                "value": preset_definition.kind,
                "label": preset_definition.label,
                "count": sum(
                    1
                    for item in kind_scope
                    if item.get("preset_type") == preset_definition.kind
                ),
                "order": preset_definition.order,
            }
            for preset_definition in preset_registry.PRESET_KINDS
        ],
        "category_groups": _catalog_facet_items(category_scope, "category_group"),
        "subcategories": _catalog_facet_items(subcategory_scope, "subcategory"),
        "task_statuses": _catalog_task_status_facet_items(task_status_scope),
    }
    return {
        "items": [
            {
                "kind": definition.kind,
                "label": definition.label,
                "order": definition.order,
                "items": page_items,
            }
        ],
        "total": total,
        "page": current_page,
        "page_size": current_page_size,
        "sort": normalized_sort,
        "facets": facets,
    }


def catalog(restriction: bool) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for definition in preset_registry.PRESET_KINDS:
        kind_items = []
        for preset in definition.list_loader():
            if restriction and preset_is_restricted(preset):
                continue
            kind_items.append(
                preset_summary(
                    definition.kind,
                    str(preset["id"]),
                    index_existing=False,
                )
            )
        items.append(
            {
                "kind": definition.kind,
                "label": definition.label,
                "order": definition.order,
                "items": kind_items,
            }
        )
    return {"items": items}


def preset_detail(preset_type: str, preset_id: str, restriction: bool) -> dict[str, Any]:
    preset = ensure_restricted_access(preset_type, preset_id, restriction)
    return {
        "preset": preset,
        "summary": preset_summary(preset_type, preset_id),
        "sources": [
            _source_payload(item)
            for item in database.list_preset_asset_sources(preset_type, preset_id)
        ],
        "candidates": [
            _candidate_payload(item)
            for item in database.list_preset_asset_candidates(
                preset_type, preset_id, limit=200
            )
        ],
        "versions": [
            _version_payload(item)
            for item in database.list_preset_asset_versions(
                preset_type, preset_id, limit=100
            )
        ],
    }


def import_source(
    preset_type: str,
    preset_id: str,
    data: bytes,
    *,
    mime_type: str | None = None,
    source_kind: str = "upload",
) -> dict[str, Any]:
    resolve_preset(preset_type, preset_id)
    metadata = validate_image_bytes(data, mime_type=mime_type)
    sources = database.list_preset_asset_sources(preset_type, preset_id, limit=1)
    revision = (int(sources[0]["revision"]) + 1) if sources else 1
    directory = _managed_root("sources", preset_type, preset_id, str(revision))
    extension = IMAGE_EXTENSIONS[metadata["format"]]
    target = _ensure_under(directory / f"source.{extension}", directory)
    _atomic_write(target, data)
    database.deactivate_preset_asset_sources(preset_type, preset_id)
    source_id = database.insert_preset_asset_source(
        preset_type,
        preset_id,
        revision,
        source_kind,
        str(target),
        metadata["mime_type"],
        metadata["width"],
        metadata["height"],
        metadata["sha256"],
        True,
    )
    database.add_preset_asset_audit(
        "source_imported",
        preset_type,
        preset_id,
        detail={"source_id": source_id, "sha256": metadata["sha256"]},
    )
    return _source_payload(database.get_preset_asset_source(source_id) or {})


def create_crop_candidate(
    preset_type: str,
    preset_id: str,
    *,
    source_id: int | None = None,
    crop: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    job_item_index: int | None = None,
) -> dict[str, Any]:
    preset = resolve_preset(preset_type, preset_id)
    target = target_for(preset_type)
    source = (
        database.get_preset_asset_source(source_id)
        if source_id
        else database.get_active_preset_asset_source(preset_type, preset_id)
    )
    if not source:
        raise PresetAssetError("没有可用的源图", status_code=409)
    if source.get("preset_type") != preset_type or source.get("preset_id") != preset_id:
        raise PresetAssetError("源图不属于当前预设", status_code=400)
    source_path = Path(str(source["managed_path"]))
    _ensure_under(source_path, Path(config.PRESET_ASSET_ROOT))
    image = _open_image_path(source_path)
    crop_data = {
        "mode": str((crop or {}).get("mode") or "cover"),
        "focus_x": (crop or {}).get("focus_x", 0.5),
        "focus_y": (crop or {}).get("focus_y", 0.5),
        "zoom": (crop or {}).get("zoom", 1.0),
    }
    output_size = tuple(int(item) for item in target["output_size"])
    crop_params = {
        "focus_x": crop_data["focus_x"],
        "focus_y": crop_data["focus_y"],
        "zoom": crop_data["zoom"],
    }
    if crop_data["mode"] == "contain":
        output_image = _resize_contain(image, output_size, **crop_params)
    else:
        output_image = _resize_cover(image, output_size, **crop_params)
    output_data, mime_type, extension = _encode_image(
        output_image, target["format"], target["quality"]
    )
    candidate_params = dict(params or {})
    if job_item_index is not None:
        candidate_params[CANDIDATE_JOB_ITEM_INDEX_PARAM] = int(job_item_index)
    candidate_id = database.insert_preset_asset_candidate(
        preset_type,
        preset_id,
        "crop",
        "preparing",
        candidate_params,
        source_revision_id=source.get("id"),
        generation_width=image.width,
        generation_height=image.height,
        output_width=output_size[0],
        output_height=output_size[1],
        crop=crop_data,
    )
    candidate_dir = _managed_root("candidates", preset_type, preset_id, str(candidate_id))
    target_path = _ensure_under(candidate_dir / f"thumbnail.{extension}", candidate_dir)
    _atomic_write(target_path, output_data)
    database.update_preset_asset_candidate(
        candidate_id,
        status="ready",
        original_path=str(source_path),
        preview_path=str(target_path),
        thumbnail_path=str(target_path),
        params_json=json.dumps(candidate_params, ensure_ascii=False),
        crop_json=json.dumps(crop_data, ensure_ascii=False),
    )
    database.add_preset_asset_audit(
        "crop_candidate_created",
        preset_type,
        preset_id,
        candidate_id=candidate_id,
        detail={"source_id": source.get("id")},
    )
    candidate = database.get_preset_asset_candidate(candidate_id)
    if not candidate:
        raise PresetAssetError("候选保存失败", status_code=500)
    return _candidate_payload(candidate)


def finalize_ai_candidate(
    candidate_id: int,
    source_path: Path,
    *,
    crop: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = database.get_preset_asset_candidate(candidate_id)
    if not candidate:
        raise PresetAssetError("候选不存在", status_code=404)
    preset_type = str(candidate["preset_type"])
    preset_id = str(candidate["preset_id"])
    target = target_for(preset_type)
    source_path = _ensure_under(source_path, Path(config.PRESET_ASSET_ROOT))
    image = _open_image_path(source_path)
    crop_data = {
        "mode": str((crop or {}).get("mode") or "cover"),
        "focus_x": (crop or {}).get("focus_x", 0.5),
        "focus_y": (crop or {}).get("focus_y", 0.5),
        "zoom": (crop or {}).get("zoom", 1.0),
    }
    output_size = tuple(int(item) for item in target["output_size"])
    crop_params = {
        "focus_x": crop_data["focus_x"],
        "focus_y": crop_data["focus_y"],
        "zoom": crop_data["zoom"],
    }
    if crop_data["mode"] == "contain":
        output_image = _resize_contain(image, output_size, **crop_params)
    else:
        output_image = _resize_cover(image, output_size, **crop_params)
    output_data, _mime_type, extension = _encode_image(
        output_image, target["format"], target["quality"]
    )
    candidate_dir = _managed_root("candidates", preset_type, preset_id, str(candidate_id))
    thumbnail_path = _ensure_under(
        candidate_dir / f"thumbnail.{extension}", candidate_dir
    )
    _atomic_write(thumbnail_path, output_data)
    database.update_preset_asset_candidate(
        candidate_id,
        status="ready",
        original_path=str(source_path),
        preview_path=str(thumbnail_path),
        thumbnail_path=str(thumbnail_path),
        crop_json=json.dumps(crop_data, ensure_ascii=False),
        error=None,
    )
    database.add_preset_asset_audit(
        "ai_candidate_ready",
        preset_type,
        preset_id,
        candidate_id=candidate_id,
        detail={"source_path": str(source_path)},
    )
    return _candidate_payload(database.get_preset_asset_candidate(candidate_id) or {})


def candidate_file(candidate_id: int, *, original: bool = False) -> Path:
    candidate = database.get_preset_asset_candidate(candidate_id)
    if not candidate:
        raise PresetAssetError("候选不存在", status_code=404)
    path_value = (
        candidate.get("original_path")
        if original
        else candidate.get("thumbnail_path") or candidate.get("preview_path")
    )
    if not path_value:
        raise PresetAssetError("候选文件不存在", status_code=404)
    path = _ensure_under(Path(str(path_value)), Path(config.PRESET_ASSET_ROOT))
    if not path.is_file():
        raise PresetAssetError("候选文件不存在", status_code=404)
    return path


def source_file(source_id: int) -> Path:
    source = database.get_preset_asset_source(source_id)
    if not source:
        raise PresetAssetError("源图不存在", status_code=404)
    path = _ensure_under(Path(str(source["managed_path"])), Path(config.PRESET_ASSET_ROOT))
    if not path.is_file():
        raise PresetAssetError("源图不存在", status_code=404)
    return path


def version_file(version_id: int) -> Path:
    version = database.get_preset_asset_version(version_id)
    if not version:
        raise PresetAssetError("版本不存在", status_code=404)
    archive = _version_archive_path(
        str(version["preset_type"]),
        str(version["preset_id"]),
        int(version["version"]),
    )
    if archive.is_file():
        return archive
    path = _ensure_under(
        Path(str(version["public_path"])),
        config.PROJECT_ROOT / "studio" / "frontend",
    )
    if not path.is_file():
        raise PresetAssetError("版本文件不存在", status_code=404)
    return path


def _version_archive_path(preset_type: str, preset_id: str, version: int) -> Path:
    definition = preset_registry.PRESET_KIND_BY_KEY[preset_type]
    return (
        Path(config.PRESET_ASSET_ROOT)
        / "versions"
        / preset_type
        / preset_id
        / f"{version}.{definition.image_extension}"
    )


def _manifest(root: Path) -> dict[str, str]:
    directory = root / "clothing-presets"
    return {
        path.stem: f"/clothing-presets/{path.name}"
        for path in sorted(directory.glob("*.webp"))
    }


def _restore_active_files(preset_type: str, preset_id: str) -> None:
    """Restore public/dist files from the current active archived version."""
    active = database.get_active_preset_asset_version(preset_type, preset_id)
    if not active:
        return
    archive_path = _version_archive_path(
        preset_type,
        preset_id,
        int(active["version"]),
    )
    if not archive_path.is_file():
        raise PresetAssetError(
            "当前活动版本归档不存在，无法恢复正式素材",
            status_code=500,
        )
    data = archive_path.read_bytes()
    public_path, dist_path = _asset_paths(preset_type, preset_id)
    _atomic_write(public_path, data)
    _atomic_write(dist_path, data)
    if preset_type == "clothing":
        for manifest_path in (
            public_path.parent / "_manifest.json",
            dist_path.parent / "_manifest.json",
        ):
            _write_json_atomic(manifest_path, _manifest(manifest_path.parent.parent))


def _sync_files(
    preset_type: str,
    preset_id: str,
    data: bytes,
    *,
    journal_event: str,
    owner_token: str,
    lease_guard: _PresetAssetWriteLeaseGuard,
    expected_revision: int,
    version_number: int,
    candidate_id: int | None = None,
    target_version_id: int | None = None,
) -> tuple[Path, Path, Path]:
    public_path, dist_path = _asset_paths(preset_type, preset_id)
    archive_path = _version_archive_path(preset_type, preset_id, version_number)
    journal_dir = _managed_root("journals")
    journal_path = journal_dir / f"{preset_type}-{preset_id}-{uuid.uuid4().hex}.json"
    manifest_paths: list[Path] = []
    if preset_type == "clothing":
        manifest_paths = [
            public_path.parent / "_manifest.json",
            dist_path.parent / "_manifest.json",
        ]
    journal_files = [
        _journal_file_state(path)
        for path in [archive_path, public_path, dist_path, *manifest_paths]
    ]
    journal = {
        "version": 1,
        "event": journal_event,
        "preset_type": preset_type,
        "preset_id": preset_id,
        "owner_token": owner_token,
        "expected_revision": int(expected_revision),
        "candidate_id": candidate_id,
        "target_version_id": target_version_id,
        "version_number": int(version_number),
        "created_at": _now(),
        "files": journal_files,
    }
    lease_guard.assert_owned()
    _write_json_atomic(
        journal_path,
        journal,
    )
    try:
        for path in (archive_path, public_path, dist_path):
            lease_guard.assert_owned()
            _atomic_write(path, data)
            lease_guard.assert_owned()
        for manifest_path in manifest_paths:
            lease_guard.assert_owned()
            _write_json_atomic(manifest_path, _manifest(manifest_path.parent.parent))
            lease_guard.assert_owned()
    except _PresetAssetWriteLeaseLost:
        raise
    except Exception:
        try:
            _restore_journal_files(journal)
        except Exception:
            pass
        else:
            journal_path.unlink(missing_ok=True)
        raise
    return public_path, dist_path, journal_path


def _journal_file_state(path: Path) -> dict[str, Any]:
    data = path.read_bytes() if path.is_file() else None
    return {
        "path": str(path),
        "data": (
            base64.b64encode(data).decode("ascii")
            if data is not None
            else None
        ),
    }


def _journal_path(path: Path) -> Path:
    resolved = path.resolve()
    frontend_root = config.PROJECT_ROOT / "studio" / "frontend"
    allowed_roots = (
        (frontend_root / "public").resolve(),
        (frontend_root / "dist").resolve(),
        (Path(config.PRESET_ASSET_ROOT) / "versions").resolve(),
    )
    if any(
        resolved == root or root in resolved.parents
        for root in allowed_roots
    ):
        return resolved
    raise PresetAssetError("素材 journal 包含越界路径", status_code=500)


def _restore_journal_files(journal: dict[str, Any]) -> None:
    files = journal.get("files")
    if not isinstance(files, list):
        raise PresetAssetError("素材 journal 文件状态缺失", status_code=500)
    for item in files:
        if not isinstance(item, dict) or not item.get("path"):
            raise PresetAssetError("素材 journal 文件状态无效", status_code=500)
        path = _journal_path(Path(str(item["path"])))
        encoded = item.get("data")
        if encoded is None:
            path.unlink(missing_ok=True)
            continue
        try:
            data = base64.b64decode(str(encoded), validate=True)
        except (ValueError, TypeError) as exc:
            raise PresetAssetError(
                "素材 journal 文件内容无效",
                status_code=500,
            ) from exc
        _atomic_write(path, data)


def _journal_committed(journal: dict[str, Any]) -> bool:
    preset_type = str(journal.get("preset_type") or "")
    preset_id = str(journal.get("preset_id") or "")
    event = str(journal.get("event") or "")
    active = database.get_active_preset_asset_version(preset_type, preset_id)
    if event == "adopt_candidate":
        candidate_id = int(journal.get("candidate_id") or 0)
        version_number = int(journal.get("version_number") or 0)
        candidate = database.get_preset_asset_candidate(candidate_id)
        return bool(
            active
            and int(active.get("version") or 0) == version_number
            and int(active.get("candidate_id") or 0) == candidate_id
            and candidate
            and candidate.get("status") == "adopted"
        )
    if event == "rollback_version":
        target_version_id = int(journal.get("target_version_id") or 0)
        return bool(active and int(active.get("id") or 0) == target_version_id)
    return False


def _discard_journal(journal_path: Path) -> None:
    try:
        journal_path.unlink(missing_ok=True)
    except OSError:
        pass


def _restore_journal_or_active(
    journal: dict[str, Any],
    *,
    current_revision: int,
) -> None:
    expected_revision = int(journal.get("expected_revision") or 0)
    if current_revision != expected_revision:
        if current_revision:
            _restore_active_files(
                str(journal.get("preset_type") or ""),
                str(journal.get("preset_id") or ""),
            )
            return
        raise PresetAssetError(
            "素材版本状态异常，无法安全恢复 journal",
            status_code=500,
        )
    _restore_journal_files(journal)


def _recover_write_journal(
    journal_path: Path,
    *,
    takeover_owner_token: str | None = None,
    expected_owner_token: str | None = None,
) -> str:
    try:
        journal = json.loads(journal_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PresetAssetError("素材 journal 无法读取", status_code=500) from exc
    if not isinstance(journal, dict) or int(journal.get("version") or 0) != 1:
        raise PresetAssetError("素材 journal 版本不支持", status_code=500)

    preset_type = str(journal.get("preset_type") or "")
    preset_id = str(journal.get("preset_id") or "")
    owner_token = str(journal.get("owner_token") or "")
    expected_revision = int(journal.get("expected_revision") or 0)
    if expected_owner_token is not None and owner_token != expected_owner_token:
        return "deferred"
    committed = _journal_committed(journal)
    lease = database.get_preset_asset_write_lease(preset_type, preset_id)
    lease_owner = str((lease or {}).get("owner_token") or "")
    lease_active = bool(
        lease and float(lease.get("expires_at") or 0) > time.time()
    )

    if takeover_owner_token is not None:
        if lease_owner != takeover_owner_token:
            return "deferred"
        if not committed:
            active = database.get_active_preset_asset_version(preset_type, preset_id)
            current_revision = int(active["id"]) if active else 0
            _restore_journal_or_active(
                journal,
                current_revision=current_revision,
            )
        _discard_journal(journal_path)
        return "cleaned" if committed else "recovered"

    if committed:
        if lease_owner and (lease_owner == owner_token or not lease_active):
            database.release_preset_asset_write_lease(
                preset_type,
                preset_id,
                lease_owner,
            )
        _discard_journal(journal_path)
        return "cleaned"

    if lease_owner and lease_owner != owner_token and lease_active:
        return "deferred"

    active = database.get_active_preset_asset_version(preset_type, preset_id)
    current_revision = int(active["id"]) if active else 0
    if not committed:
        if current_revision == expected_revision:
            _restore_journal_files(journal)
        elif current_revision:
            _restore_active_files(preset_type, preset_id)
        else:
            raise PresetAssetError(
                "素材版本状态异常，无法安全恢复 journal",
                status_code=500,
            )

    if lease_owner and (lease_owner == owner_token or not lease_active):
        database.release_preset_asset_write_lease(
            preset_type,
            preset_id,
            lease_owner,
        )
    _discard_journal(journal_path)
    return "restored"


def _recover_stale_write_journals(
    preset_type: str,
    preset_id: str,
    owner_token: str,
) -> list[dict[str, str]]:
    recovered: list[dict[str, str]] = []
    journal_dir = _managed_root("journals")
    for journal_path in sorted(journal_dir.glob("*.json")):
        try:
            journal = json.loads(journal_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            str(journal.get("preset_type") or "") != preset_type
            or str(journal.get("preset_id") or "") != preset_id
        ):
            continue
        status = _recover_write_journal(
            journal_path,
            takeover_owner_token=owner_token,
        )
        if status != "deferred":
            recovered.append(
                {
                    "journal": journal_path.name,
                    "status": status,
                }
            )
    return recovered


def _recover_write_after_error(
    journal_path: Path | None,
    *,
    preset_type: str,
    preset_id: str,
    owner_token: str,
) -> None:
    """Recover a failed write, including when a newer owner removed its journal."""
    lease = database.get_preset_asset_write_lease(preset_type, preset_id)
    lease_owner = str((lease or {}).get("owner_token") or "")
    if lease_owner and lease_owner != owner_token:
        return

    if journal_path is not None and journal_path.is_file():
        _recover_write_journal(
            journal_path,
            expected_owner_token=owner_token,
        )
        return

    if journal_path is None:
        journal_dir = _managed_root("journals")
        for candidate in sorted(journal_dir.glob("*.json")):
            try:
                journal = json.loads(candidate.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (
                str(journal.get("preset_type") or "") == preset_type
                and str(journal.get("preset_id") or "") == preset_id
                and str(journal.get("owner_token") or "") == owner_token
            ):
                _recover_write_journal(
                    candidate,
                    expected_owner_token=owner_token,
                )
                return

    active = database.get_active_preset_asset_version(preset_type, preset_id)
    if active:
        _restore_active_files(preset_type, preset_id)


def recover_pending_write_journals() -> list[dict[str, str]]:
    """Recover durable formal-asset writes left by an interrupted process."""
    journal_dir = _managed_root("journals")
    recovered: list[dict[str, str]] = []
    for journal_path in sorted(journal_dir.glob("*.json")):
        recovered.append(
            {
                "journal": journal_path.name,
                "status": _recover_write_journal(journal_path),
            }
        )
    return recovered


def adopt_candidate(candidate_id: int, expected_revision: int | None = None) -> dict[str, Any]:
    candidate = database.get_preset_asset_candidate(candidate_id)
    if not candidate:
        raise PresetAssetError("候选不存在", status_code=404)
    if candidate.get("status") != "ready":
        raise PresetAssetError("只有 ready 候选可以采纳", status_code=409)
    preset_type = str(candidate["preset_type"])
    preset_id = str(candidate["preset_id"])
    resolve_preset(preset_type, preset_id)
    _assert_current_character_version(candidate)
    active = database.get_active_preset_asset_version(preset_type, preset_id)
    current_revision = int(active["id"]) if active else 0
    if expected_revision is not None and int(expected_revision) != current_revision:
        raise PresetAssetError("正式图已被其他操作更新，请刷新后重试", status_code=409)
    thumbnail = candidate.get("thumbnail_path") or candidate.get("preview_path")
    if not thumbnail:
        raise PresetAssetError("候选缺少可采纳缩略图", status_code=409)
    source_path = _ensure_under(Path(str(thumbnail)), Path(config.PRESET_ASSET_ROOT))
    if not source_path.is_file():
        raise PresetAssetError("候选文件不存在", status_code=409)
    data = source_path.read_bytes()
    metadata = validate_image_bytes(data)
    target = target_for(preset_type)
    expected_size = tuple(int(item) for item in target["output_size"])
    if (metadata["width"], metadata["height"]) != expected_size:
        raise PresetAssetError("候选尺寸不符合目标尺寸", status_code=409)
    versions = database.list_preset_asset_versions(preset_type, preset_id, limit=1)
    version_number = (int(versions[0]["version"]) + 1) if versions else 1

    owner_token = uuid.uuid4().hex
    lease_status = database.acquire_preset_asset_write_lease(
        preset_type,
        preset_id,
        "adopt",
        current_revision,
        owner_token,
        candidate_id=int(candidate_id),
    )
    if lease_status == "busy":
        raise PresetAssetError("该预设正在执行其他正式素材操作，请稍后重试", status_code=409)
    if lease_status == "revision_conflict":
        raise PresetAssetError("正式图已被其他操作更新，请刷新后重试", status_code=409)
    if lease_status == "candidate_unavailable":
        raise PresetAssetError("候选状态已变化，请刷新后重试", status_code=409)
    if lease_status != "acquired":
        raise PresetAssetError("无法获取正式素材写入锁", status_code=409)

    lease_guard = _PresetAssetWriteLeaseGuard(
        preset_type,
        preset_id,
        owner_token,
    )
    lease_guard.start()
    journal_path: Path | None = None
    write_started = False
    try:
        _recover_stale_write_journals(
            preset_type,
            preset_id,
            owner_token,
        )
        write_started = True
        public_path, dist_path, journal_path = _sync_files(
            preset_type,
            preset_id,
            data,
            journal_event="adopt_candidate",
            owner_token=owner_token,
            lease_guard=lease_guard,
            expected_revision=current_revision,
            version_number=version_number,
            candidate_id=int(candidate_id),
        )
        lease_guard.assert_owned()
        committed = database.commit_preset_asset_adoption(
            preset_type,
            preset_id,
            int(candidate_id),
            owner_token,
            str(public_path),
            str(dist_path),
            metadata["mime_type"],
            metadata["width"],
            metadata["height"],
            metadata["sha256"],
            expected_version_number=version_number,
        )
        if not committed:
            _recover_write_after_error(
                journal_path,
                preset_type=preset_type,
                preset_id=preset_id,
                owner_token=owner_token,
            )
            journal_path = None
            raise PresetAssetError(
                "正式图已被其他操作更新，请刷新后重试",
                status_code=409,
            )
        _discard_journal(journal_path)
        journal_path = None
        version_id = int(committed["version_id"])
    except Exception:
        try:
            if write_started:
                _recover_write_after_error(
                    journal_path,
                    preset_type=preset_type,
                    preset_id=preset_id,
                    owner_token=owner_token,
                )
        finally:
            database.release_preset_asset_write_lease(
                preset_type,
                preset_id,
                owner_token,
            )
        raise
    finally:
        lease_guard.stop()
    return {
        "ok": True,
        "version": _version_payload(database.get_preset_asset_version(version_id) or {}),
        "image": preset_summary(preset_type, preset_id)["image"],
    }


def discard_candidate(candidate_id: int) -> dict[str, Any]:
    candidate = database.get_preset_asset_candidate(candidate_id)
    if not candidate:
        raise PresetAssetError("候选不存在", status_code=404)
    if candidate.get("status") == "adopted":
        raise PresetAssetError("已采纳候选不能丢弃", status_code=409)
    updated = database.discard_preset_asset_candidate(candidate_id)
    if not updated:
        current = database.get_preset_asset_candidate(candidate_id)
        if current and current.get("status") == "discarded":
            return {"ok": True, "status": "discarded"}
        raise PresetAssetError(
            "该预设正在执行正式素材写入，请稍后重试",
            status_code=409,
        )
    database.add_preset_asset_audit(
        "candidate_discarded",
        str(candidate["preset_type"]),
        str(candidate["preset_id"]),
        candidate_id=candidate_id,
    )
    return {"ok": True, "status": "discarded"}


def clear_candidates(preset_type: str, preset_id: str) -> dict[str, Any]:
    resolve_preset(preset_type, preset_id)
    cleared_count, active_count, lease_busy = database.discard_preset_asset_candidates(
        preset_type,
        preset_id,
    )
    if lease_busy:
        raise PresetAssetError(
            "该预设正在执行正式素材写入，请稍后重试",
            status_code=409,
        )
    if active_count:
        raise PresetAssetError(
            f"仍有 {active_count} 个生成中的候选，请先停止或等待任务完成",
            status_code=409,
        )
    if cleared_count:
        database.add_preset_asset_audit(
            "candidates_cleared",
            preset_type,
            preset_id,
            detail={"cleared_count": cleared_count},
        )
    return {"ok": True, "cleared_count": cleared_count}


def rollback_version(
    preset_type: str,
    preset_id: str,
    version: int,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    resolve_preset(preset_type, preset_id)
    active = database.get_active_preset_asset_version(preset_type, preset_id)
    current_revision = int(active["id"]) if active else 0
    if expected_revision is not None and int(expected_revision) != current_revision:
        raise PresetAssetError("正式图已被其他操作更新，请刷新后重试", status_code=409)
    target = database.get_preset_asset_version_by_number(
        preset_type,
        preset_id,
        int(version),
    )
    if not target:
        raise PresetAssetError("目标历史版本不存在", status_code=404)
    archive = _version_archive_path(preset_type, preset_id, int(version))
    if not archive.is_file():
        raise PresetAssetError("历史版本归档不存在", status_code=409)
    data = archive.read_bytes()
    metadata = validate_image_bytes(data)

    owner_token = uuid.uuid4().hex
    lease_status = database.acquire_preset_asset_write_lease(
        preset_type,
        preset_id,
        "rollback",
        current_revision,
        owner_token,
        target_version_id=int(target["id"]),
    )
    if lease_status == "busy":
        raise PresetAssetError("该预设正在执行其他正式素材操作，请稍后重试", status_code=409)
    if lease_status == "revision_conflict":
        raise PresetAssetError("正式图已被其他操作更新，请刷新后重试", status_code=409)
    if lease_status == "target_unavailable":
        raise PresetAssetError("目标历史版本状态已变化，请刷新后重试", status_code=409)
    if lease_status != "acquired":
        raise PresetAssetError("无法获取正式素材写入锁", status_code=409)

    lease_guard = _PresetAssetWriteLeaseGuard(
        preset_type,
        preset_id,
        owner_token,
    )
    lease_guard.start()
    journal_path: Path | None = None
    write_started = False
    try:
        _recover_stale_write_journals(
            preset_type,
            preset_id,
            owner_token,
        )
        write_started = True
        _public_path, _dist_path, journal_path = _sync_files(
            preset_type,
            preset_id,
            data,
            journal_event="rollback_version",
            owner_token=owner_token,
            lease_guard=lease_guard,
            expected_revision=current_revision,
            version_number=int(version),
            candidate_id=(
                int(target["candidate_id"])
                if target.get("candidate_id") is not None
                else None
            ),
            target_version_id=int(target["id"]),
        )
        lease_guard.assert_owned()
        committed = database.commit_preset_asset_rollback(
            preset_type,
            preset_id,
            int(target["id"]),
            owner_token,
        )
        if not committed:
            _recover_write_after_error(
                journal_path,
                preset_type=preset_type,
                preset_id=preset_id,
                owner_token=owner_token,
            )
            journal_path = None
            raise PresetAssetError(
                "正式图已被其他操作更新，请刷新后重试",
                status_code=409,
            )
        _discard_journal(journal_path)
        journal_path = None
    except Exception:
        try:
            if write_started:
                _recover_write_after_error(
                    journal_path,
                    preset_type=preset_type,
                    preset_id=preset_id,
                    owner_token=owner_token,
                )
        finally:
            database.release_preset_asset_write_lease(
                preset_type,
                preset_id,
                owner_token,
            )
        raise
    finally:
        lease_guard.stop()
    return {
        "ok": True,
        "version": _version_payload(target),
        "sha256": metadata["sha256"],
        "image": preset_summary(preset_type, preset_id)["image"],
    }


def version_key(preset_type: str, preset_id: str) -> str:
    try:
        active = database.get_active_preset_asset_version(preset_type, preset_id)
    except Exception:
        active = None
    if active and active.get("sha256"):
        return str(active["sha256"])[:12]
    try:
        public_path, _dist_path = _asset_paths(preset_type, preset_id)
        if public_path.is_file():
            stat = public_path.stat()
            return f"{stat.st_mtime_ns:x}"[-12:]
    except Exception:
        pass
    return ""


def cleanup_candidate_files(candidate_id: int) -> None:
    """Best-effort candidate cleanup used by tests and future retention jobs."""
    candidate = database.get_preset_asset_candidate(candidate_id)
    if not candidate:
        return
    for key in ("original_path", "preview_path", "thumbnail_path"):
        value = candidate.get(key)
        if not value:
            continue
        try:
            path = _ensure_under(Path(str(value)), Path(config.PRESET_ASSET_ROOT))
            path.unlink(missing_ok=True)
        except (OSError, PresetAssetError):
            continue
