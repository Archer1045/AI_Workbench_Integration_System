"""Central registry for built-in preset catalogs and their metadata."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import body_modification_presets
import clothing_presets
import database
import expansion_presets
import prompt_agent
import scene_presets
import toy_presets


@dataclass(frozen=True)
class PresetKind:
    """Describe how one preset family is exposed and composed."""

    kind: str
    label: str
    order: int
    catalog_key: str
    api_path: str
    image_directory: str
    image_extension: str
    taxonomy_key: str
    composition_field: str
    list_loader: Callable[[], list[dict[str, Any]]]
    scope_capable: bool = True
    max_per_scope: int | None = None
    selection_type: str = "multiple"
    supports_colors: bool = False
    supports_thumbnail: bool = True
    composition_enabled: bool = True


def _pose_presets() -> list[dict[str, Any]]:
    return list(prompt_agent.POSE_PRESETS)


def _clothing_presets() -> list[dict[str, Any]]:
    return list(clothing_presets.CLOTHING_PRESETS)


def _scene_presets() -> list[dict[str, Any]]:
    return list(scene_presets.SCENE_PRESETS)


def _body_modification_presets() -> list[dict[str, Any]]:
    return list(body_modification_presets.BODY_MODIFICATION_PRESETS)


def _toy_presets() -> list[dict[str, Any]]:
    return list(toy_presets.TOY_PRESETS)


def _expansion_presets() -> list[dict[str, Any]]:
    return list(expansion_presets.EXPANSION_PRESETS)


def _character_presets() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for preset in database.list_character_appearance_presets():
        tags: list[str] = []
        seen: set[str] = set()
        for field in ("appearance_tags", "clothing_tags", "expression_tags"):
            for tag in preset.get(field) or []:
                normalized = str(tag).strip()
                key = normalized.casefold()
                if normalized and key not in seen:
                    seen.add(key)
                    tags.append(normalized)
        items.append(
            {
                "id": str(preset["preset_id"]),
                "label": str(preset["name"]),
                "draw_prompt": ", ".join(tags),
                "tags": tags,
                "category": str(preset.get("category") or ""),
                "work": str(preset.get("work") or ""),
                "source": str(preset.get("source") or "user"),
                "version": int(preset.get("version") or 1),
                "enabled": bool(preset.get("enabled", True)),
                "rating": "普通",
            }
        )
    return items


PRESET_KINDS: tuple[PresetKind, ...] = (
    PresetKind(
        kind="pose",
        label="体位",
        order=0,
        catalog_key="poses",
        api_path="/api/prompt-agent/pose-presets",
        image_directory="pose-presets",
        image_extension="png",
        taxonomy_key="pose",
        composition_field="pose_id",
        list_loader=_pose_presets,
        scope_capable=False,
        max_per_scope=None,
        selection_type="single",
    ),
    PresetKind(
        kind="clothing",
        label="服装",
        order=1,
        catalog_key="clothing",
        api_path="/api/prompt-agent/clothing-presets",
        image_directory="clothing-presets",
        image_extension="webp",
        taxonomy_key="clothing",
        composition_field="clothing",
        list_loader=_clothing_presets,
        max_per_scope=3,
        supports_colors=True,
    ),
    PresetKind(
        kind="scene",
        label="场景",
        order=2,
        catalog_key="scenes",
        api_path="/api/prompt-agent/scene-presets",
        image_directory="scene-presets",
        image_extension="webp",
        taxonomy_key="scene",
        composition_field="scene_id",
        list_loader=_scene_presets,
        scope_capable=False,
        selection_type="single",
    ),
    PresetKind(
        kind="body",
        label="身体改造",
        order=3,
        catalog_key="body_modifications",
        api_path="/api/prompt-agent/body-modification-presets",
        image_directory="body-modification-presets",
        image_extension="webp",
        taxonomy_key="body",
        composition_field="body_modifications",
        list_loader=_body_modification_presets,
        max_per_scope=2,
    ),
    PresetKind(
        kind="expansion",
        label="扩张",
        order=4,
        catalog_key="expansions",
        api_path="/api/prompt-agent/expansion-presets",
        image_directory="expansion-presets",
        image_extension="webp",
        taxonomy_key="expansion",
        composition_field="expansions",
        list_loader=_expansion_presets,
        max_per_scope=2,
        supports_colors=False,
    ),
    PresetKind(
        kind="toy",
        label="性玩具",
        order=5,
        catalog_key="toys",
        api_path="/api/prompt-agent/toy-presets",
        image_directory="toy-presets",
        image_extension="webp",
        taxonomy_key="toy",
        composition_field="toys",
        list_loader=_toy_presets,
        max_per_scope=3,
        supports_colors=True,
    ),
    PresetKind(
        kind="character",
        label="角色",
        order=6,
        catalog_key="characters",
        api_path="/api/prompt-agent/appearance-presets",
        image_directory="character-appearance-presets",
        image_extension="webp",
        taxonomy_key="character",
        composition_field="character_id",
        list_loader=_character_presets,
        scope_capable=False,
        max_per_scope=None,
        selection_type="single",
        composition_enabled=False,
    ),
)

PRESET_KIND_BY_KEY = {item.kind: item for item in PRESET_KINDS}
PRESET_KIND_BY_CATALOG_KEY = {item.catalog_key: item for item in PRESET_KINDS}
PRESET_KIND_BY_COMPOSITION_FIELD = {
    item.composition_field: item
    for item in PRESET_KINDS
    if item.composition_enabled
}


def kind_metadata(item: PresetKind) -> dict[str, Any]:
    """Serialize registry metadata for the frontend without preset payloads."""
    return {
        "kind": item.kind,
        "label": item.label,
        "order": item.order,
        "catalog_key": item.catalog_key,
        "api_path": item.api_path,
        "image_directory": item.image_directory,
        "image_extension": item.image_extension,
        "taxonomy_key": item.taxonomy_key,
        "composition_field": item.composition_field,
        "scope_capable": item.scope_capable,
        "max_per_scope": item.max_per_scope,
        "selection_type": item.selection_type,
        "supports_colors": item.supports_colors,
        "supports_thumbnail": item.supports_thumbnail,
        "composition_enabled": item.composition_enabled,
    }


def list_metadata() -> list[dict[str, Any]]:
    return [kind_metadata(item) for item in PRESET_KINDS]


def get_presets(kind: str) -> list[dict[str, Any]]:
    item = PRESET_KIND_BY_KEY.get(kind)
    if not item:
        raise KeyError(f"unknown preset kind: {kind}")
    return item.list_loader()
