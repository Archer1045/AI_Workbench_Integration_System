"""Database repository and managed-file synchronization for reference galleries."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

import config
import database


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
THUMBNAIL_MAX_SIDE = 384
_SYNC_LOCKS: dict[str, threading.Lock] = {}
_LOCK = threading.Lock()


def _sync_lock(kind: str) -> threading.Lock:
    with _LOCK:
        return _SYNC_LOCKS.setdefault(kind, threading.Lock())


def _source_row(kind: str) -> dict[str, Any] | None:
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM gallery_sources WHERE kind = ?",
            (kind,),
        ).fetchone()
    return dict(row) if row else None


def get_enabled_source(kind: str) -> dict[str, Any] | None:
    source = _source_row(kind)
    if not source or not bool(source.get("enabled")):
        return None
    return source


def upsert_source(
    kind: str,
    source_directory: Path,
    *,
    status: str,
    warning: str = "",
    error: str = "",
) -> dict[str, Any]:
    now = database.now_iso()
    with database.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO gallery_sources (
                kind, source_directory, import_mode, accepted_at,
                last_synced_at, status, item_count, warning, error,
                enabled, created_at, updated_at
            ) VALUES (?, ?, 'managed', ?, ?, ?, 0, ?, ?, 1, ?, ?)
            ON CONFLICT(kind) DO UPDATE SET
                source_directory = excluded.source_directory,
                import_mode = 'managed',
                accepted_at = CASE
                    WHEN gallery_sources.source_directory = excluded.source_directory
                    THEN gallery_sources.accepted_at
                    ELSE excluded.accepted_at
                END,
                manifest_relative_path = '',
                last_synced_at = excluded.last_synced_at,
                status = excluded.status,
                warning = excluded.warning,
                error = excluded.error,
                enabled = 1,
                updated_at = excluded.updated_at
            """,
            (
                kind,
                str(source_directory),
                now,
                now,
                status,
                warning,
                error,
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM gallery_sources WHERE kind = ?",
            (kind,),
        ).fetchone()
    return dict(row)


def disable_source(kind: str) -> None:
    with database.get_connection() as conn:
        conn.execute(
            """
            UPDATE gallery_sources
            SET enabled = 0, status = 'disabled', updated_at = ?
            WHERE kind = ?
            """,
            (database.now_iso(), kind),
        )


def set_source_status(
    kind: str,
    status: str,
    *,
    item_count: int | None = None,
    warning: str = "",
    error: str = "",
) -> None:
    with database.get_connection() as conn:
        if item_count is None:
            conn.execute(
                """
                UPDATE gallery_sources
                SET status = ?, warning = ?, error = ?, last_synced_at = ?,
                    updated_at = ?
                WHERE kind = ?
                """,
                (
                    status,
                    warning,
                    error,
                    database.now_iso(),
                    database.now_iso(),
                    kind,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE gallery_sources
                SET status = ?, item_count = ?, warning = ?, error = ?,
                    last_synced_at = ?, updated_at = ?
                WHERE kind = ?
                """,
                (
                    status,
                    item_count,
                    warning,
                    error,
                    database.now_iso(),
                    database.now_iso(),
                    kind,
                ),
            )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _managed_relative_path(kind: str, digest: str, suffix: str) -> str:
    return f"{kind}/{digest[:2]}/{digest}{suffix.lower()}"


def _copy_managed(source: Path, relative: str) -> Path:
    root = config.EXTERNAL_GALLERY_ASSET_ROOT.resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError("托管路径越界") from None
    if target.is_file() and target.stat().st_size == source.stat().st_size:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _thumbnail_for(managed: Path, digest: str) -> str:
    relative = f"thumbnails/{digest}.jpg"
    target = config.EXTERNAL_GALLERY_CACHE_DIR / relative
    if target.is_file():
        return relative
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with Image.open(managed) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail(
                (THUMBNAIL_MAX_SIDE, THUMBNAIL_MAX_SIDE),
                Image.Resampling.LANCZOS,
            )
            image.save(temporary, "JPEG", quality=86, optimize=True)
            os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return relative


def sync_catalogue(
    kind: str,
    source_directory: Path,
    catalogue: dict[str, Any],
    resolved_paths: dict[str, Path],
) -> dict[str, Any]:
    """Copy/update catalogue items into managed storage and upsert DB rows."""
    lock = _sync_lock(kind)
    if not lock.acquire(blocking=False):
        raise RuntimeError("该图库正在同步，请稍后重试")
    warnings: list[str] = []
    imported = 0
    failed = 0
    seen: set[str] = set()
    conn = None
    try:
        upsert_source(kind, source_directory, status="syncing")
        source = get_enabled_source(kind)
        if not source:
            raise RuntimeError("图库来源未能建立")
        source_id = int(source["id"])
        now = database.now_iso()
        conn = database.get_connection()
        for item in catalogue.get("items") or []:
            external_id = str(item.get("id") or "").strip()
            source_path = resolved_paths.get(external_id)
            if not external_id or not source_path:
                failed += 1
                warnings.append(f"{external_id or '未知素材'}：缺少可读取路径")
                continue
            try:
                digest = _hash_file(source_path)
                managed_relative = _managed_relative_path(
                    kind,
                    digest,
                    source_path.suffix,
                )
                managed = _copy_managed(source_path, managed_relative)
                with Image.open(managed) as opened:
                    opened.load()
                    width, height = opened.size
                    image_format = str(opened.format or source_path.suffix[1:]).upper()
                thumbnail_relative = _thumbnail_for(managed, digest)
                tags = [str(tag) for tag in (item.get("tags") or [])]
                search_text = str(
                    item.get("search")
                    or " ".join(
                        [
                            external_id,
                            str(item.get("name") or ""),
                            str(item.get("category") or ""),
                            str(item.get("system") or ""),
                            str(item.get("angle") or ""),
                            *tags,
                        ]
                    )
                ).casefold()
                conn.execute(
                    """
                        INSERT INTO gallery_assets (
                            source_id, kind, external_id, source_relative_path,
                            managed_relative_path, sha256, width, height, format,
                            size_bytes, name, category, system, angle, group_name,
                            tags_json, search_text, thumbnail_relative_path,
                            pose_preset_id, favorite, last_used_at, use_count, status,
                            imported_at, updated_at
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, 0, NULL, 0, 'active', ?, ?
                        )
                        ON CONFLICT(source_id, external_id) DO UPDATE SET
                            kind = excluded.kind,
                            source_relative_path = excluded.source_relative_path,
                            managed_relative_path = excluded.managed_relative_path,
                            sha256 = excluded.sha256,
                            width = excluded.width,
                            height = excluded.height,
                            format = excluded.format,
                            size_bytes = excluded.size_bytes,
                            name = excluded.name,
                            category = excluded.category,
                            system = excluded.system,
                            angle = excluded.angle,
                            group_name = excluded.group_name,
                            tags_json = excluded.tags_json,
                            search_text = excluded.search_text,
                            thumbnail_relative_path = excluded.thumbnail_relative_path,
                            pose_preset_id = excluded.pose_preset_id,
                            status = 'active',
                            updated_at = excluded.updated_at
                        """,
                    (
                        source_id,
                        kind,
                        external_id,
                        str(item.get("path") or ""),
                        managed_relative,
                        digest,
                        width,
                        height,
                        image_format,
                        source_path.stat().st_size,
                        str(item.get("name") or external_id),
                        str(item.get("category") or ""),
                        str(item.get("system") or ""),
                        str(item.get("angle") or ""),
                        str(item.get("group") or ""),
                        json.dumps(tags, ensure_ascii=False),
                        search_text,
                        thumbnail_relative,
                        (
                            str(item.get("pose_preset_id") or "")
                            if kind == "pose"
                            else ""
                        ),
                        now,
                        now,
                    ),
                )
                imported += 1
                seen.add(external_id)
            except Exception as exc:  # noqa: BLE001 - continue with other assets
                failed += 1
                warnings.append(f"{external_id}：{str(exc)[-300:]}")
        rows = conn.execute(
            """
            SELECT external_id FROM gallery_assets
            WHERE source_id = ? AND status = 'active'
            """,
            (source_id,),
        ).fetchall()
        missing = [str(row["external_id"]) for row in rows if row["external_id"] not in seen]
        for external_id in missing:
            conn.execute(
                """
                UPDATE gallery_assets
                SET status = 'missing', updated_at = ?
                WHERE source_id = ? AND external_id = ?
                """,
                (database.now_iso(), source_id, external_id),
            )
        status = "empty" if imported == 0 and failed == 0 else "ready"
        if imported == 0 and failed:
            status = "error"
        warning = catalogue.get("warning") or ""
        if warnings:
            warning = "；".join(
                part for part in [warning, *warnings[:8]] if part
            )
        conn.execute(
            """
            UPDATE gallery_sources
            SET status = ?, item_count = ?, warning = ?, error = ?,
                manifest_relative_path = ?, last_synced_at = ?, updated_at = ?
            WHERE kind = ?
            """,
            (
                status,
                imported,
                warning,
                warnings[0] if status == "error" else "",
                str(catalogue.get("manifest") or ""),
                database.now_iso(),
                database.now_iso(),
                kind,
            ),
        )
        conn.commit()
        conn.close()
        conn = None
        return {
            "imported": imported,
            "failed": failed,
            "missing": len(missing),
            "warning": warning,
            "status": status,
        }
    finally:
        if conn is not None:
            conn.close()
        lock.release()


def list_assets(kind: str, *, include_missing: bool = False) -> list[dict[str, Any]]:
    source = get_enabled_source(kind)
    if not source:
        return []
    with database.get_connection() as conn:
        if include_missing:
            rows = conn.execute(
                """
                SELECT * FROM gallery_assets
                WHERE source_id = ?
                ORDER BY status = 'missing', name COLLATE NOCASE, id
                """,
                (int(source["id"]),),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM gallery_assets
                WHERE source_id = ? AND status = 'active'
                ORDER BY name COLLATE NOCASE, id
                """,
                (int(source["id"]),),
            ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["tags"] = json.loads(item.pop("tags_json") or "[]")
        except ValueError:
            item["tags"] = []
        item["favorite"] = bool(item.get("favorite"))
        items.append(item)
    return items


def get_asset(kind: str, asset_id: int) -> dict[str, Any] | None:
    with database.get_connection() as conn:
        row = conn.execute(
            """
            SELECT gallery_assets.*, gallery_sources.enabled
            FROM gallery_assets
            JOIN gallery_sources ON gallery_sources.id = gallery_assets.source_id
            WHERE gallery_assets.id = ? AND gallery_assets.kind = ?
              AND gallery_sources.enabled = 1
            """,
            (asset_id, kind),
        ).fetchone()
    return dict(row) if row else None


def toggle_favorite(kind: str, asset_id: int) -> dict[str, Any] | None:
    with database.get_connection() as conn:
        conn.execute(
            """
            UPDATE gallery_assets
            SET favorite = CASE favorite WHEN 0 THEN 1 ELSE 0 END,
                updated_at = ?
            WHERE id = ? AND kind = ?
            """,
            (database.now_iso(), asset_id, kind),
        )
    return get_asset(kind, asset_id)


def record_use(kind: str, asset_id: int) -> dict[str, Any] | None:
    with database.get_connection() as conn:
        conn.execute(
            """
            UPDATE gallery_assets
            SET use_count = use_count + 1, last_used_at = ?, updated_at = ?
            WHERE id = ? AND kind = ?
            """,
            (database.now_iso(), database.now_iso(), asset_id, kind),
        )
    return get_asset(kind, asset_id)


def set_pose_link(asset_id: int, pose_preset_id: str) -> dict[str, Any] | None:
    with database.get_connection() as conn:
        conn.execute(
            """
            UPDATE gallery_assets
            SET pose_preset_id = ?, updated_at = ?
            WHERE id = ? AND kind = 'pose'
            """,
            (pose_preset_id, database.now_iso(), asset_id),
        )
    return get_asset("pose", asset_id)


def managed_path(relative_path: str) -> Path:
    root = config.EXTERNAL_GALLERY_ASSET_ROOT.resolve()
    target = (root / str(relative_path or "")).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError("托管素材路径越界") from None
    if not target.is_file():
        raise FileNotFoundError(f"托管素材不存在：{relative_path}")
    return target


def thumbnail_path(relative_path: str) -> Path:
    root = config.EXTERNAL_GALLERY_CACHE_DIR.resolve()
    target = (root / str(relative_path or "")).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError("缩略图路径越界") from None
    if not target.is_file():
        raise FileNotFoundError(f"缩略图不存在：{relative_path}")
    return target
