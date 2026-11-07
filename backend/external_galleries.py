"""Read-only bindings for external pose and costume image galleries."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PIL import Image, ImageOps

import config
import database
import gallery_repository


KINDS = {"pose": "姿势图库", "costume": "服装图库"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
THUMBNAIL_MAX_SIDE = 384
FOLDER_CACHE_SECONDS = 8.0
MAX_SEARCH_LENGTH = 4000

_LOCK = threading.RLock()
_CATALOGUE_CACHE: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
_POSE_PRESET_CACHE: dict[str, dict[str, Any]] | None = None


class ExternalGalleryError(ValueError):
    """A user-facing gallery validation error."""


def _pose_presets() -> dict[str, dict[str, Any]]:
    global _POSE_PRESET_CACHE
    if _POSE_PRESET_CACHE is None:
        import prompt_agent

        _POSE_PRESET_CACHE = {
            str(preset["id"]): preset
            for preset in prompt_agent.POSE_PRESETS
        }
    return _POSE_PRESET_CACHE


def _pose_link_metadata(pose_preset_id: str) -> dict[str, str]:
    if not pose_preset_id:
        return {"pose_preset_label": "", "pose_preset_category": ""}
    preset = _pose_presets().get(pose_preset_id)
    if not preset:
        return {"pose_preset_label": "", "pose_preset_category": ""}
    if (
        str(preset.get("rating") or "") == "R18"
        and database.get_setting("content_restriction", "false") == "true"
    ):
        return {"pose_preset_label": "", "pose_preset_category": ""}
    return {
        "pose_preset_label": str(preset.get("label") or pose_preset_id),
        "pose_preset_category": str(preset.get("category") or ""),
    }


def _empty_binding() -> dict[str, Any]:
    return {"directory": "", "accepted": False, "accepted_at": ""}


def _empty_settings() -> dict[str, dict[str, Any]]:
    return {kind: _empty_binding() for kind in KINDS}


def _read_settings_unlocked() -> dict[str, dict[str, Any]]:
    path = config.EXTERNAL_GALLERY_CONFIG_PATH
    raw: Any = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
    settings = _empty_settings()
    if not isinstance(raw, dict):
        return settings
    for kind in KINDS:
        entry = raw.get(kind)
        if not isinstance(entry, dict):
            continue
        settings[kind] = {
            "directory": str(entry.get("directory") or "").strip(),
            "accepted": bool(entry.get("accepted")),
            "accepted_at": str(entry.get("accepted_at") or ""),
        }
    return settings


def _write_settings_unlocked(settings: dict[str, dict[str, Any]]) -> None:
    path = config.EXTERNAL_GALLERY_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _binding_id(root: Path) -> str:
    normalized = os.path.normcase(str(root.resolve()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def settings_payload() -> dict[str, dict[str, Any]]:
    managed_sources = {
        kind: gallery_repository.get_enabled_source(kind)
        for kind in KINDS
    }
    with _LOCK:
        settings = _read_settings_unlocked()
    result: dict[str, dict[str, Any]] = {}
    for kind, entry in settings.items():
        managed = managed_sources.get(kind)
        if managed:
            directory = str(managed.get("source_directory") or "")
            root = Path(directory) if directory else None
            result[kind] = {
                **entry,
                "directory": directory,
                "accepted": True,
                "accepted_at": str(managed.get("accepted_at") or ""),
                "label": KINDS[kind],
                "configured": True,
                "available": bool(
                    (root and root.is_dir())
                    or int(managed.get("item_count") or 0) > 0
                ),
                "source_available": bool(root and root.is_dir()),
                "binding_id": (
                    _binding_id(root)
                    if root
                    else f"managed-{int(managed['id'])}"
                ),
                "source_id": int(managed["id"]),
                "import_mode": "managed",
                "status": str(managed.get("status") or "empty"),
                "item_count": int(managed.get("item_count") or 0),
                "last_synced_at": managed.get("last_synced_at"),
                "warning": str(managed.get("warning") or ""),
                "error": str(managed.get("error") or ""),
            }
            continue
        directory = str(entry.get("directory") or "")
        configured = bool(directory and entry.get("accepted"))
        root = Path(directory) if directory else None
        available = bool(root and root.is_absolute() and root.is_dir())
        result[kind] = {
            **entry,
            "label": KINDS[kind],
            "configured": configured,
            "available": available,
            "source_available": available,
            "binding_id": _binding_id(root) if available and root else "",
            "source_id": None,
            "import_mode": "reference",
            "status": "ready" if configured and available else "empty",
            "item_count": 0,
            "last_synced_at": None,
            "warning": "",
            "error": "",
        }
    return result


def save_binding(
    kind: str,
    directory: str,
    confirmed_local_access: bool,
) -> dict[str, dict[str, Any]]:
    if kind not in KINDS:
        raise ExternalGalleryError("未知图库类型。")
    if not confirmed_local_access:
        raise ExternalGalleryError("绑定图库前请确认你拥有该目录及素材的使用权。")
    text = str(directory or "").strip()
    if not text:
        raise ExternalGalleryError("请填写图库目录的绝对路径。")
    root = Path(text).expanduser()
    if not root.is_absolute():
        raise ExternalGalleryError("图库目录必须使用本机绝对路径。")
    try:
        root = root.resolve(strict=True)
    except OSError:
        raise ExternalGalleryError(f"图库目录不存在或无法访问：{text}") from None
    if not root.is_dir():
        raise ExternalGalleryError(f"图库目录不存在或不是文件夹：{root}")

    catalogue = build_catalogue(kind, root, allow_empty=True)
    catalogue = _validate_pose_links(catalogue, kind)
    resolved_paths = {
        str(item["id"]): resolve_image(root, str(item["path"]))
        for item in catalogue.get("items") or []
    }
    try:
        gallery_repository.sync_catalogue(
            kind,
            root,
            catalogue,
            resolved_paths,
        )
    except RuntimeError as exc:
        raise ExternalGalleryError(str(exc)) from exc
    with _LOCK:
        settings = _read_settings_unlocked()
        previous = settings.get(kind, {})
        settings[kind] = {
            "directory": str(root),
            "accepted": True,
            "accepted_at": (
                previous.get("accepted_at")
                if previous.get("directory") == str(root)
                else time.strftime("%Y-%m-%dT%H:%M:%S%z")
            ),
        }
        _write_settings_unlocked(settings)
    invalidate()
    return settings_payload()


def clear_binding(kind: str) -> dict[str, dict[str, Any]]:
    if kind not in KINDS:
        raise ExternalGalleryError("未知图库类型。")
    gallery_repository.disable_source(kind)
    with _LOCK:
        settings = _read_settings_unlocked()
        settings[kind] = _empty_binding()
        _write_settings_unlocked(settings)
    invalidate()
    return settings_payload()


def bound_root(kind: str) -> Path:
    if kind not in KINDS:
        raise ExternalGalleryError("未知图库类型。")
    settings = settings_payload()[kind]
    label = KINDS[kind]
    if not settings["configured"]:
        raise ExternalGalleryError(f"尚未绑定{label}。")
    if not settings["available"]:
        raise ExternalGalleryError(
            f"{label}目录已移动或不可访问：{settings['directory']}"
        )
    return Path(settings["directory"]).resolve()


def safe_relative_path(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        raise ExternalGalleryError("素材路径不能为空。")
    if (
        text.startswith("/")
        or text.startswith("//")
        or re.match(r"^[a-zA-Z]:", text)
        or "\x00" in text
    ):
        raise ExternalGalleryError("素材路径必须是图库目录内的相对路径。")
    parts = text.split("/")
    if any(part in {"", ".", ".."} or part.startswith(".") for part in parts):
        raise ExternalGalleryError(f"素材路径不合法：{value}")
    if Path(text).suffix.lower() not in IMAGE_SUFFIXES:
        raise ExternalGalleryError(f"不支持的图片格式：{value}")
    return "/".join(parts)


def resolve_image(root: Path, relative_path: str) -> Path:
    relative = safe_relative_path(relative_path)
    root = root.resolve()
    target = (root / Path(relative)).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ExternalGalleryError(f"素材路径越界：{relative_path}") from None
    if not target.is_file():
        raise ExternalGalleryError(f"图片文件缺失：{relative_path}")
    return target


def _natural_key(value: str) -> list[Any]:
    return [
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", value)
    ]


def _manifest_candidates(root: Path, kind: str) -> list[Path]:
    data = root / "data"
    if not data.is_dir():
        return []
    preferred = [data / f"{kind}-zh.json", data / f"{kind}.json"]
    candidates = [path for path in preferred if path.is_file()]
    for path in sorted(data.glob("*.json"), key=lambda item: _natural_key(item.name)):
        if path in candidates:
            continue
        stem = path.stem.casefold()
        if stem.startswith("pose") and kind != "pose":
            continue
        if stem.startswith("costume") and kind != "costume":
            continue
        candidates.append(path)
    return candidates


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _as_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [
            item.strip()
            for item in re.split(r"[,，;；|]", value)
            if item.strip()
        ]
    return []


def _manifest_item(row: dict[str, Any]) -> dict[str, Any] | None:
    item_id = _as_text(row.get("id"))
    original = _as_text(
        row.get("original")
        or row.get("image")
        or row.get("path")
        or row.get("原图")
        or row.get("大图")
    )
    if not item_id or not original:
        return None
    try:
        relative = safe_relative_path(original)
    except ExternalGalleryError:
        return None
    thumbnail = _as_text(
        row.get("thumbnail")
        or row.get("thumb")
        or row.get("缩略图")
    )
    if thumbnail:
        try:
            thumbnail = safe_relative_path(thumbnail)
        except ExternalGalleryError:
            thumbnail = ""
    tags = _as_tags(row.get("tags") or row.get("标签"))
    keywords = " ".join(
        value
        for value in (
            _as_text(row.get("keywords")),
            _as_text(row.get("关键词")),
            _as_text(row.get("关键词中文")),
        )
        if value
    )
    name = (
        _as_text(row.get("name"))
        or _as_text(row.get("名称"))
        or _as_text(row.get("姿势名称"))
        or _as_text(row.get("关键词中文"))
        or item_id
    )
    category = _as_text(row.get("category") or row.get("分类"))
    system = _as_text(row.get("system") or row.get("体系"))
    angle = _as_text(row.get("angle") or row.get("角度"))
    group = _as_text(row.get("group") or row.get("姿势编号"))
    pose_preset_id = _as_text(
        row.get("pose_preset_id")
        or row.get("pose_id")
        or row.get("position_preset_id")
        or row.get("体位预设ID")
        or row.get("体位ID")
    )
    search = " ".join(
        (item_id, name, relative, category, system, angle, group, keywords, *tags)
    ).casefold()[:MAX_SEARCH_LENGTH]
    return {
        "id": item_id,
        "name": name,
        "category": category,
        "system": system,
        "angle": angle,
        "group": group,
        "pose_preset_id": pose_preset_id,
        "tags": tags,
        "path": relative,
        "thumb": thumbnail,
        "search": search,
    }


def _manifest_catalogue(
    root: Path,
    kind: str,
) -> tuple[dict[str, Any] | None, str]:
    had_manifest = False
    invalid_messages: list[str] = []
    for manifest in _manifest_candidates(root, kind):
        had_manifest = True
        try:
            rows = json.loads(manifest.read_text(encoding="utf-8-sig"))
            if not isinstance(rows, list):
                raise ValueError("根节点必须是数组")
        except (OSError, ValueError) as exc:
            invalid_messages.append(f"{manifest.name}: {exc}")
            continue
        items = [
            item
            for item in (
                _manifest_item(row)
                for row in rows
                if isinstance(row, dict)
            )
            if item
        ]
        if not items:
            invalid_messages.append(f"{manifest.name}: 没有含 id 和原图路径的有效条目")
            continue
        if len(items) > config.EXTERNAL_GALLERY_MAX_ITEMS:
            raise ExternalGalleryError(
                f"清单包含 {len(items)} 张图片，超过上限 "
                f"{config.EXTERNAL_GALLERY_MAX_ITEMS}。"
            )
        angles = sorted(
            {item["angle"] for item in items if item["angle"]},
            key=_natural_key,
        )
        tag_counts: dict[str, int] = {}
        for item in items:
            for tag in item["tags"]:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        catalogue = {
            "kind": kind,
            "mode": "manifest",
            "manifest": manifest.relative_to(root).as_posix(),
            "warning": "",
            "count": len(items),
            "items": items,
            "facets": {
                "system": sorted(
                    {item["system"] for item in items if item["system"]},
                    key=_natural_key,
                ),
                "category": sorted(
                    {item["category"] for item in items if item["category"]},
                    key=_natural_key,
                ),
                "angle": angles,
                "tag": [
                    tag
                    for tag, _count in sorted(
                        tag_counts.items(),
                        key=lambda entry: (-entry[1], _natural_key(entry[0])),
                    )[:48]
                ],
            },
        }
        return catalogue, ""
    warning = ""
    if had_manifest and invalid_messages:
        warning = "清单不可用，已回退到递归图片扫描：" + "；".join(invalid_messages[:2])
    return None, warning


def _folder_catalogue(
    root: Path,
    kind: str,
    warning: str = "",
    *,
    allow_empty: bool = False,
) -> dict[str, Any]:
    files: list[Path] = []
    for current_root, directory_names, file_names in os.walk(root):
        directory_names[:] = [
            name for name in directory_names if not name.startswith(".")
        ]
        current = Path(current_root)
        for name in file_names:
            if name.startswith(".") or Path(name).suffix.lower() not in IMAGE_SUFFIXES:
                continue
            path = (current / name).resolve()
            try:
                path.relative_to(root)
            except ValueError:
                continue
            files.append(path)
            if len(files) > config.EXTERNAL_GALLERY_MAX_ITEMS:
                raise ExternalGalleryError(
                    "图库图片数量超过上限 "
                    f"{config.EXTERNAL_GALLERY_MAX_ITEMS}，请拆分目录后重新绑定。"
                )
    if not files and not allow_empty:
        raise ExternalGalleryError(
            "目录中没有支持的图片（PNG/JPEG/WebP）。"
        )
    files.sort(key=lambda path: _natural_key(path.relative_to(root).as_posix()))
    items: list[dict[str, Any]] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        parent = path.parent.relative_to(root).as_posix()
        items.append(
            {
                "id": relative,
                "name": path.stem,
                "category": "" if parent == "." else parent,
                "system": "",
                "angle": "",
                "group": "",
                "tags": [],
                "path": relative,
                "thumb": "",
                "search": relative.casefold()[:MAX_SEARCH_LENGTH],
            }
        )
    return {
        "kind": kind,
        "mode": "folder",
        "manifest": "",
        "warning": warning,
        "count": len(items),
        "items": items,
        "facets": {
            "system": [],
            "category": sorted(
                {item["category"] for item in items if item["category"]},
                key=_natural_key,
            ),
            "angle": [],
            "tag": [],
        },
    }


def build_catalogue(
    kind: str,
    root: Path,
    *,
    allow_empty: bool = False,
) -> dict[str, Any]:
    if kind not in KINDS:
        raise ExternalGalleryError("未知图库类型。")
    root = root.resolve()
    if not root.is_dir():
        raise ExternalGalleryError(f"图库目录不可访问：{root}")
    catalogue, warning = _manifest_catalogue(root, kind)
    if catalogue is None:
        catalogue = _folder_catalogue(
            root,
            kind,
            warning,
            allow_empty=allow_empty,
        )
    for item in catalogue["items"]:
        encoded_path = quote(item["path"], safe="")
        item["image_url"] = (
            f"/api/external-galleries/{kind}/image?path={encoded_path}"
        )
        thumbnail_query = f"path={encoded_path}&variant=thumbnail"
        if item["thumb"]:
            thumbnail_query += (
                "&thumb_path=" + quote(item["thumb"], safe="")
            )
        item["thumbnail_url"] = (
            f"/api/external-galleries/{kind}/image?{thumbnail_query}"
        )
    return catalogue


def _validate_pose_links(catalogue: dict[str, Any], kind: str) -> dict[str, Any]:
    if kind != "pose":
        return catalogue
    valid = _pose_presets()
    rejected: list[str] = []
    for item in catalogue.get("items") or []:
        pose_preset_id = str(item.get("pose_preset_id") or "").strip()
        if pose_preset_id and pose_preset_id not in valid:
            item["pose_preset_id"] = ""
            rejected.append(str(item.get("id") or pose_preset_id))
    if rejected:
        warning = (
            "以下素材引用了不存在的体位预设，已保留素材但清除关联："
            + "、".join(rejected[:8])
        )
        catalogue["warning"] = "；".join(
            part for part in [str(catalogue.get("warning") or ""), warning] if part
        )
    return catalogue


def _managed_catalogue(kind: str) -> dict[str, Any]:
    source = gallery_repository.get_enabled_source(kind)
    if not source:
        raise ExternalGalleryError(f"尚未托管{KINDS[kind]}。")
    assets = gallery_repository.list_assets(kind)
    items: list[dict[str, Any]] = []
    tag_counts: dict[str, int] = {}
    for asset in assets:
        tags = list(asset.get("tags") or [])
        pose_preset_id = (
            str(asset.get("pose_preset_id") or "")
            if kind == "pose"
            else ""
        )
        pose_link = _pose_link_metadata(pose_preset_id)
        for tag in tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        asset_id = int(asset["id"])
        items.append(
            {
                "id": str(asset["external_id"]),
                "asset_id": asset_id,
                "name": str(asset.get("name") or asset["external_id"]),
                "category": str(asset.get("category") or ""),
                "system": str(asset.get("system") or ""),
                "angle": str(asset.get("angle") or ""),
                "group": str(asset.get("group_name") or ""),
                "pose_preset_id": pose_preset_id,
                **pose_link,
                "tags": tags,
                "path": str(asset.get("source_relative_path") or ""),
                "thumb": "",
                "search": " ".join(
                    value
                    for value in (
                        str(asset.get("search_text") or ""),
                        pose_preset_id,
                        pose_link["pose_preset_label"],
                    )
                    if value
                ).casefold(),
                "favorite": bool(asset.get("favorite")),
                "last_used_at": asset.get("last_used_at"),
                "use_count": int(asset.get("use_count") or 0),
                "managed": True,
                "image_url": (
                    f"/api/external-galleries/{kind}/assets/{asset_id}"
                ),
                "thumbnail_url": (
                    f"/api/external-galleries/{kind}/assets/{asset_id}"
                    "?variant=thumbnail"
                ),
            }
        )
    return {
        "kind": kind,
        "mode": "database",
        "manifest": str(source.get("manifest_relative_path") or ""),
        "warning": str(source.get("warning") or ""),
        "count": len(items),
        "items": items,
        "facets": {
            "system": sorted(
                {item["system"] for item in items if item["system"]},
                key=_natural_key,
            ),
            "category": sorted(
                {item["category"] for item in items if item["category"]},
                key=_natural_key,
            ),
            "angle": sorted(
                {item["angle"] for item in items if item["angle"]},
                key=_natural_key,
            ),
            "tag": [
                tag
                for tag, _count in sorted(
                    tag_counts.items(),
                    key=lambda entry: (-entry[1], _natural_key(entry[0])),
                )[:48]
            ],
        },
    }


def synchronize_managed(kind: str) -> dict[str, Any]:
    if kind not in KINDS:
        raise ExternalGalleryError("未知图库类型。")
    source = gallery_repository.get_enabled_source(kind)
    if not source:
        invalidate()
        return catalogue_for(kind)
    root = Path(str(source.get("source_directory") or ""))
    if not root.is_absolute() or not root.is_dir():
        gallery_repository.set_source_status(
            kind,
            "source_unavailable",
            warning=f"{KINDS[kind]}来源目录当前不可访问，托管副本仍可继续使用。",
        )
        return _managed_catalogue(kind)
    root = root.resolve()
    catalogue = build_catalogue(kind, root, allow_empty=True)
    catalogue = _validate_pose_links(catalogue, kind)
    resolved_paths = {
        str(item["id"]): resolve_image(root, str(item["path"]))
        for item in catalogue.get("items") or []
    }
    try:
        gallery_repository.sync_catalogue(
            kind,
            root,
            catalogue,
            resolved_paths,
        )
    except RuntimeError as exc:
        raise ExternalGalleryError(str(exc)) from exc
    invalidate()
    return _managed_catalogue(kind)


def catalogue_for(kind: str) -> dict[str, Any]:
    if gallery_repository.get_enabled_source(kind):
        return _managed_catalogue(kind)
    root = bound_root(kind)
    candidates = _manifest_candidates(root, kind)
    manifest_signatures: list[str] = []
    for candidate in candidates:
        try:
            stat = candidate.stat()
            manifest_signatures.append(
                f"{candidate}:{stat.st_mtime_ns}:{stat.st_size}"
            )
        except OSError:
            manifest_signatures.append(f"{candidate}:missing")
    manifest_signature = "|".join(manifest_signatures)
    key = (kind, str(root), manifest_signature)
    with _LOCK:
        cached = _CATALOGUE_CACHE.get(key)
    if cached:
        cached_at, catalogue = cached
        if manifest_signature or time.time() - cached_at < FOLDER_CACHE_SECONDS:
            return catalogue
    catalogue = build_catalogue(kind, root)
    with _LOCK:
        _CATALOGUE_CACHE[key] = (time.time(), catalogue)
    return catalogue


def invalidate() -> None:
    with _LOCK:
        _CATALOGUE_CACHE.clear()


def _thumbnail_cache_path(image_path: Path) -> Path:
    stat = image_path.stat()
    digest = hashlib.sha256(
        (
            f"{image_path}|{stat.st_mtime_ns}|{stat.st_size}|"
            f"{THUMBNAIL_MAX_SIDE}"
        ).encode("utf-8")
    ).hexdigest()
    return config.EXTERNAL_GALLERY_CACHE_DIR / "thumbnails" / f"{digest}.jpg"


def image_path_for(
    kind: str,
    relative_path: str,
    variant: str,
    manifest_thumbnail: str = "",
) -> Path:
    root = bound_root(kind)
    if variant != "thumbnail":
        return resolve_image(root, relative_path)
    if manifest_thumbnail:
        try:
            return resolve_image(root, manifest_thumbnail)
        except ExternalGalleryError:
            pass
    source = resolve_image(root, relative_path)
    cache_path = _thumbnail_cache_path(source)
    if cache_path.is_file():
        return cache_path
    temporary = cache_path.with_name(
        f".{cache_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail(
                (THUMBNAIL_MAX_SIDE, THUMBNAIL_MAX_SIDE),
                Image.Resampling.LANCZOS,
            )
            image.save(temporary, "JPEG", quality=86, optimize=True)
            os.replace(temporary, cache_path)
        return cache_path
    except (OSError, ValueError):
        # A readable original is still a valid preview if thumbnail generation fails.
        return source
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def managed_image_path(
    kind: str,
    asset_id: int,
    variant: str,
) -> Path:
    asset = gallery_repository.get_asset(kind, asset_id)
    if not asset or asset.get("status") != "active":
        raise ExternalGalleryError("托管素材不存在或已缺失。")
    relative = (
        str(asset.get("thumbnail_relative_path") or "")
        if variant == "thumbnail"
        else str(asset.get("managed_relative_path") or "")
    )
    try:
        return (
            gallery_repository.thumbnail_path(relative)
            if variant == "thumbnail"
            else gallery_repository.managed_path(relative)
        )
    except (OSError, ValueError) as exc:
        raise ExternalGalleryError(str(exc)) from exc


def toggle_managed_favorite(kind: str, asset_id: int) -> dict[str, Any]:
    asset = gallery_repository.toggle_favorite(kind, asset_id)
    if not asset:
        raise ExternalGalleryError("托管素材不存在。")
    return {
        "asset_id": int(asset["id"]),
        "favorite": bool(asset.get("favorite")),
    }


def record_managed_use(kind: str, asset_id: int) -> dict[str, Any]:
    asset = gallery_repository.record_use(kind, asset_id)
    if not asset:
        raise ExternalGalleryError("托管素材不存在。")
    return {
        "asset_id": int(asset["id"]),
        "last_used_at": asset.get("last_used_at"),
        "use_count": int(asset.get("use_count") or 0),
    }


def link_managed_pose(
    kind: str,
    asset_id: int,
    pose_preset_id: str,
) -> dict[str, Any]:
    if kind != "pose":
        raise ExternalGalleryError("只有姿势图库可以关联体位预设。")
    selected = str(pose_preset_id or "").strip()
    if selected and selected not in _pose_presets():
        raise ExternalGalleryError("体位预设不存在，未保存关联。")
    asset = gallery_repository.set_pose_link(asset_id, selected)
    if not asset:
        raise ExternalGalleryError("托管姿势素材不存在。")
    metadata = _pose_link_metadata(selected)
    return {
        "asset_id": int(asset["id"]),
        "pose_preset_id": selected,
        **metadata,
    }
