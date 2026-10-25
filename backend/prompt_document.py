"""PromptDocumentV1 normalization, validation, and prompt resolution."""
from __future__ import annotations

import copy
import re
from typing import Iterable

import config
import content_filter
import database
import expression_presets
import prompt_agent
import preset_composer
import preset_registry
import water_presets


class PromptDocumentError(ValueError):
    """Raised when a prompt document is malformed or cannot be resolved."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


PROMPT_DOCUMENT_VERSION = 1
TEMPLATE_VERSION = "prompt_document_v1"
DEFAULT_ROLES = ("girlA", "girlB", "boyA", "boyB")
DEFAULT_ROLE_LABELS = {
    "girlA": "女A",
    "girlB": "女B",
    "boyA": "男A",
    "boyB": "男B",
}
ROLE_PROMPTS = {
    "girlA": "the first girl",
    "girlB": "the second girl",
    "boyA": "the first boy",
    "boyB": "the second boy",
}
CHARACTER_BLOCKS = (
    "appearance",
    "clothing",
    "body_modifications",
    "pose_or_action",
    "expression",
    "state",
)
HEIGHT_FRAME_PROMPTS: dict[str, tuple[str, ...]] = {
    "none": (),
    "petite_adult": (
        "petite adult woman",
        "small stature",
        "mature adult proportions",
    ),
    "standard_height": (
        "average-height adult woman",
        "natural adult proportions",
    ),
    "tall": (
        "tall adult woman",
        "long legs",
        "mature adult proportions",
    ),
}
BODY_BUILD_PROMPTS: dict[str, tuple[str, ...]] = {
    "none": (),
    "standard": (
        "natural adult proportions",
        "average build",
    ),
    "slim": (
        "slender adult woman",
        "slim body",
        "narrow waist",
        "flat stomach",
        "slender thighs",
    ),
    "athletic": (
        "athletic adult woman",
        "toned body",
        "firm waist",
    ),
    "curvy": (
        "curvy adult woman",
        "defined waist",
        "full hips",
    ),
    "plump": (
        "plump adult woman",
        "soft rounded body",
        "round belly",
        "thick thighs",
        "wide hips",
        "soft waist",
    ),
}
GLOBAL_BLOCKS = ("quality", "style", "scene", "camera", "lighting", "constraints")
NEGATIVE_BLOCKS = ("quality", "anatomy", "composition", "style", "content", "custom")
APPEARANCE_CATEGORIES = (
    "角色",
    "脸部",
    "头发",
    "眼睛",
    "体型",
    "肤色与皮肤特征",
    "身体特征与配饰",
    "表情",
    "自由备注",
)
_REFERENCE_KINDS = {
    "clothing": "clothing",
    "body_modifications": "body",
    "scene": "scene",
    "toys": "toy",
}


def _text(value: object) -> str:
    return str(value or "").strip()


def _tags(value: object) -> list[str]:
    if isinstance(value, list):
        raw = value
    elif isinstance(value, str):
        raw = re.split(r"[,\n]", value)
    else:
        raw = []
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = str(item or "").strip()
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            result.append(tag)
    return result


def _merge_tags(*groups: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            tag = _text(item)
            key = tag.lower()
            if tag and key not in seen:
                seen.add(key)
                result.append(tag)
    return result


def _block(raw: object, kind: str) -> dict:
    if isinstance(raw, list) or isinstance(raw, str):
        data: dict = {"tags": raw}
    elif isinstance(raw, dict):
        data = raw
    else:
        data = {}
    refs: list[dict] = []
    raw_refs = data.get("preset_refs") or []
    if isinstance(raw_refs, dict):
        raw_refs = [raw_refs]
    if isinstance(raw_refs, list):
        for item in raw_refs:
            ref_id = _text(item.get("preset_id") if isinstance(item, dict) else item)
            if not ref_id:
                continue
            ref = {"preset_id": ref_id}
            if isinstance(item, dict):
                try:
                    ref["version"] = max(1, int(item.get("version") or 1))
                except (TypeError, ValueError):
                    ref["version"] = 1
                if item.get("scope"):
                    ref["scope"] = prompt_composer_scope(item.get("scope"))
            refs.append(ref)
    snapshot = data.get("preset_snapshot")
    return {
        "id": _text(data.get("id")) or f"{kind}-block",
        "kind": kind,
        "tags": _tags(data.get("tags")),
        "preset_refs": refs,
        "preset_snapshot": copy.deepcopy(snapshot) if isinstance(snapshot, (dict, list)) else {},
        "locked": bool(data.get("locked")),
        "enabled": data.get("enabled", True) is not False,
        "source": _text(data.get("source")) or "manual",
        "order": int(data.get("order") or 0),
    }


def prompt_composer_scope(value: object) -> str:
    return preset_composer._canonical_scope(value)


def _default_role(index: int, gender: str) -> tuple[str, str]:
    if gender == "男":
        if index < 2:
            role_id = f"boy{'AB'[index]}"
        else:
            role_id = f"boy{index - 1}"
    elif index < 2:
        role_id = f"girl{'AB'[index]}"
    else:
        role_id = f"girl{index - 1}"
    return role_id, DEFAULT_ROLE_LABELS.get(role_id, f"角色{index + 1}")


def _profile_value(
    value: object,
    *,
    field_name: str,
    options: dict[str, tuple[str, ...]],
) -> str:
    profile_id = _text(value) or "none"
    if profile_id not in options:
        raise PromptDocumentError(f"不支持的 {field_name} 选项：{profile_id}")
    return profile_id


def _character(raw: object, index: int) -> dict:
    data = raw if isinstance(raw, dict) else {}
    gender = _text(data.get("gender"))
    default_role, default_name = _default_role(index, gender)
    role_id = _text(data.get("role_id")) or default_role
    display_name = _text(data.get("display_name")) or DEFAULT_ROLE_LABELS.get(role_id, default_name)
    character_id = _text(data.get("id")) or f"character-{index + 1}"
    item = {
        "id": character_id,
        "role_id": role_id,
        "display_name": display_name,
        "gender": gender,
        "height_frame": _profile_value(
            data.get("height_frame"),
            field_name="height_frame",
            options=HEIGHT_FRAME_PROMPTS,
        ),
        "body_build": _profile_value(
            data.get("body_build"),
            field_name="body_build",
            options=BODY_BUILD_PROMPTS,
        ),
        "order": int(data.get("order") if data.get("order") is not None else index),
        "enabled": data.get("enabled", True) is not False,
    }
    for kind in CHARACTER_BLOCKS:
        item[kind] = _block(data.get(kind), kind)
    return item


def normalize_document(raw: object) -> dict:
    """Return a complete PromptDocumentV1 without mutating the input."""
    data = raw if isinstance(raw, dict) else {}
    mode = _text(data.get("mode"))
    if mode not in ("structured", "legacy"):
        mode = "legacy" if data.get("raw_override") else "structured"
    global_raw = data.get("global") if isinstance(data.get("global"), dict) else {}
    negative_raw = data.get("negative") if isinstance(data.get("negative"), dict) else {}
    interaction_raw = data.get("interaction") if isinstance(data.get("interaction"), dict) else {}
    custom_raw = data.get("custom") if isinstance(data.get("custom"), dict) else {}
    raw_override = data.get("raw_override") if isinstance(data.get("raw_override"), dict) else {}
    characters_raw = data.get("characters") if isinstance(data.get("characters"), list) else []
    characters = [_character(item, index) for index, item in enumerate(characters_raw)]
    characters.sort(key=lambda item: (item["order"], item["id"]))
    for index, item in enumerate(characters):
        item["order"] = index

    pose_raw = interaction_raw.get("pose_preset")
    pose_ref: dict = {}
    if isinstance(pose_raw, str) and pose_raw.strip():
        pose_ref = {"preset_id": pose_raw.strip(), "version": 1}
    elif isinstance(pose_raw, dict) and _text(pose_raw.get("preset_id") or pose_raw.get("id")):
        pose_ref = {
            "preset_id": _text(pose_raw.get("preset_id") or pose_raw.get("id")),
            "version": max(1, int(pose_raw.get("version") or 1)),
        }
        if pose_raw.get("scope"):
            pose_ref["scope"] = prompt_composer_scope(pose_raw.get("scope"))

    return {
        "version": PROMPT_DOCUMENT_VERSION,
        "mode": mode,
        "global": {kind: _block(global_raw.get(kind), kind) for kind in GLOBAL_BLOCKS},
        "characters": characters,
        "interaction": {
            "pose_preset": pose_ref,
            "action_tags": _tags(interaction_raw.get("action_tags")),
            "contact_tags": _tags(interaction_raw.get("contact_tags")),
            "relationship_tags": _tags(interaction_raw.get("relationship_tags")),
            "composition_constraints": _tags(interaction_raw.get("composition_constraints")),
        },
        "custom": {
            "global_tags": _tags(custom_raw.get("global_tags") or custom_raw.get("tags")),
            "user_notes": _text(custom_raw.get("user_notes") or custom_raw.get("notes")),
        },
        "negative": {kind: _block(negative_raw.get(kind), kind) for kind in NEGATIVE_BLOCKS},
        "raw_override": {
            "prompt": _text(raw_override.get("prompt")),
            "negative_prompt": _text(raw_override.get("negative_prompt")),
        },
    }


def legacy_document(prompt: str, negative_prompt: str = "") -> dict:
    document = normalize_document({"mode": "legacy", "characters": [{"gender": "未设置"}]})
    document["raw_override"] = {
        "prompt": _text(prompt),
        "negative_prompt": _text(negative_prompt),
    }
    return document


def normalize_legacy_prompt(prompt: str, negative_prompt: str = "") -> dict:
    """Build a lossless structured draft while keeping the original in raw_override."""
    document = legacy_document(prompt, negative_prompt)
    document["mode"] = "structured"
    document["custom"]["global_tags"] = _tags(prompt)
    return document


def _catalog_item(kind: str, preset_id: str) -> tuple[dict | None, dict[str, dict]]:
    poses, clothing, scenes, modifications, toys, expansions = preset_composer._catalog_maps()
    maps = {
        "pose": poses,
        "clothing": clothing,
        "scene": scenes,
        "body": modifications,
        "toy": toys,
        "expansion": expansions,
    }
    return maps.get(kind, {}).get(preset_id), maps


def _preset_text(preset: dict, *, scope: str = "", role_id: str = "") -> str:
    fragment = preset_composer._fragment(preset)
    if not scope or scope == "all":
        return fragment
    label = ROLE_PROMPTS.get(prompt_composer_scope(scope), role_id or scope)
    return f"for {label}: {fragment}"


def _appearance_snapshot_tags(
    ref: dict,
    block_kind: str,
) -> tuple[list[str], dict | None]:
    preset_id = _text(ref.get("preset_id"))
    version = int(ref.get("version") or 1)
    preset = database.get_character_appearance_preset(preset_id, version)
    if not preset:
        return [], None
    field = {
        "appearance": "appearance_tags",
        "clothing": "clothing_tags",
        "expression": "expression_tags",
    }.get(block_kind, "appearance_tags")
    return _tags(preset.get(field) or []), preset


def _character_context(character: dict) -> str:
    return (
        f"for {ROLE_PROMPTS.get(character['role_id'], character['display_name'])} "
        f"({character['display_name']})"
    )


def _body_profile_tags(character: dict) -> list[str]:
    prefix = _character_context(character)
    profile_tags = _merge_tags(
        HEIGHT_FRAME_PROMPTS[character["height_frame"]],
        BODY_BUILD_PROMPTS[character["body_build"]],
    )
    return [f"{prefix}: {tag}" for tag in profile_tags]


def _block_tags(
    block: dict,
    *,
    character: dict | None = None,
    role_id: str = "",
) -> tuple[list[str], list[str], str]:
    tags = list(block.get("tags") or [])
    used_ids: list[str] = []
    rating = "普通"
    for ref in block.get("preset_refs") or []:
        preset_id = _text(ref.get("preset_id"))
        kind = _REFERENCE_KINDS.get(block.get("kind"))
        water = water_presets.WATER_PRESETS_BY_ID.get(preset_id)
        if water:
            tags = _merge_tags(tags, water.get("tags") or [])
            used_ids.append(preset_id)
            continue
        if block.get("kind") in ("appearance", "clothing", "expression"):
            if block.get("kind") == "expression":
                expression = expression_presets.EXPRESSION_PRESETS_BY_ID.get(
                    preset_id
                )
                if expression:
                    tags = _merge_tags(tags, expression.get("tags") or [])
                    used_ids.append(preset_id)
                    if _text(expression.get("rating")) == "R18":
                        rating = "R18"
                    continue
            snapshot_tags, snapshot = _appearance_snapshot_tags(ref, block.get("kind"))
            if snapshot_tags:
                tags = _merge_tags(tags, snapshot_tags)
                used_ids.append(preset_id)
            elif isinstance(block.get("preset_snapshot"), dict):
                snapshot = block["preset_snapshot"]
                field = {
                    "appearance": "appearance_tags",
                    "clothing": "clothing_tags",
                    "expression": "expression_tags",
                }.get(block.get("kind"), "appearance_tags")
                tags = _merge_tags(tags, _tags(snapshot.get(field) or []))
                used_ids.append(preset_id)
            continue
        if not kind:
            continue
        preset, _ = _catalog_item(kind, preset_id)
        if not preset:
            raise PromptDocumentError(f"不存在的预设 ID：{preset_id}")
        tags.append(
            _preset_text(
                preset,
                scope=_text(ref.get("scope")),
                role_id=role_id,
            )
        )
        used_ids.append(preset_id)
        if str(preset.get("rating") or ("R18" if preset.get("nsfw") else "普通")) == "R18":
            rating = "R18"
    if character:
        prefix = _character_context(character)
        return [f"{prefix}: {tag}" for tag in _merge_tags(tags)], used_ids, rating
    return _merge_tags(tags), used_ids, rating


def _enabled_characters(document: dict) -> list[dict]:
    return [item for item in document.get("characters") or [] if item.get("enabled", True)]


def _pose_role_slots(pose: dict) -> list[str]:
    return [_text(item) for item in pose.get("role_slots") or [] if _text(item)]


def resolve_document(
    raw_document: object,
    *,
    restriction_enabled: bool = False,
) -> dict:
    """Validate and resolve a PromptDocumentV1 into final prompts."""
    document = normalize_document(raw_document)
    if document["mode"] == "legacy":
        prompt = document["raw_override"]["prompt"]
        negative = document["raw_override"]["negative_prompt"]
        if not prompt:
            raise PromptDocumentError("legacy 文档缺少 raw_override.prompt")
        return {
            "prompt": prompt,
            "negative_prompt": negative,
            "rating": "普通",
            "warnings": [],
            "errors": [],
            "blocked": False,
            "used_ids": [],
            "roles": [],
            "resolved_document": document,
            "template_version": TEMPLATE_VERSION,
        }

    warnings: list[str] = []
    errors: list[str] = []
    used_ids: list[str] = []
    rating = "普通"
    pose_fragments: list[str] = []
    pose: dict | None = None
    pose_id = _text(document["interaction"].get("pose_preset", {}).get("preset_id"))
    if pose_id:
        pose, _ = _catalog_item("pose", pose_id)
        if not pose:
            raise PromptDocumentError(f"不存在的体位 ID：{pose_id}")
        pose_fragment = _preset_text(pose)
        if pose_fragment:
            pose_fragments.append(pose_fragment)
        used_ids.append(pose_id)
        if str(pose.get("rating") or ("R18" if pose.get("nsfw") else "普通")) == "R18":
            rating = "R18"

    characters = _enabled_characters(document)
    role_slots = _pose_role_slots(pose or {})
    if pose and pose.get("people") == "单人" and len(characters) > 1:
        errors.append("单人构图中只能启用一个角色")
    if pose and pose.get("people") in {"双人", "多人"} and role_slots and len(characters) != len(role_slots):
        label = "多人" if pose.get("people") == "多人" else "双人"
        errors.append(f"{label}体位需要 {len(role_slots)} 个角色，当前为 {len(characters)} 个")
    if characters:
        for index, character in enumerate(characters):
            if role_slots and index < len(role_slots):
                role_id = _text(character.get("role_id"))
                if role_id != role_slots[index]:
                    warnings.append(
                        f"角色 {character['display_name']} 的位次与体位槽位 {role_slots[index]} 不一致"
                    )

    global_fragments: dict[str, list[str]] = {}
    for kind in GLOBAL_BLOCKS:
        block = document["global"][kind]
        if not block.get("enabled", True):
            continue
        tags, ids, block_rating = _block_tags(block)
        global_fragments[kind] = tags
        used_ids.extend(ids)
        if block_rating == "R18":
            rating = "R18"

    character_fragments: list[str] = []
    for character in characters:
        selected_ids: list[str] = []
        parts: list[str] = []
        for kind in CHARACTER_BLOCKS:
            block = character[kind]
            if block.get("enabled", True):
                tags, ids, block_rating = _block_tags(
                    block,
                    character=character,
                    role_id=character["role_id"],
                )
                parts.extend(tags)
                selected_ids.extend(ids)
                used_ids.extend(ids)
                if block_rating == "R18":
                    rating = "R18"
            if kind == "appearance":
                parts.extend(_body_profile_tags(character))
        if len(character["clothing"].get("preset_refs") or []) > 3:
            errors.append(f"{character['display_name']} 的服装超过 3 个")
        if len(character["body_modifications"].get("preset_refs") or []) > 2:
            errors.append(f"{character['display_name']} 的身体改造超过 2 个")
        try:
            preset_composer._check_conflicts(selected_ids)
        except preset_composer.ComposeError as exc:
            warnings.append(str(exc))
        character_fragments.extend(_merge_tags(parts))

    interaction = document["interaction"]
    interaction_tags = _merge_tags(
        interaction.get("action_tags") or [],
        interaction.get("contact_tags") or [],
        interaction.get("relationship_tags") or [],
        interaction.get("composition_constraints") or [],
    )
    custom_tags = _merge_tags(document["custom"].get("global_tags") or [])
    notes = _text(document["custom"].get("user_notes"))
    if notes:
        custom_tags.append(notes)

    ordered = _merge_tags(
        global_fragments.get("quality", []),
        global_fragments.get("style", []),
        global_fragments.get("scene", []),
        pose_fragments,
        character_fragments,
        interaction_tags,
        global_fragments.get("camera", []),
        global_fragments.get("lighting", []),
        custom_tags,
        global_fragments.get("constraints", []),
    )
    positive = ", ".join(ordered)
    negative_blocks: list[str] = []
    for kind in NEGATIVE_BLOCKS:
        block = document["negative"][kind]
        if block.get("enabled", True):
            negative_blocks.append(", ".join(_tags(block.get("tags") or [])))
    negative = ", ".join(item for item in negative_blocks if item)

    if len(set(used_ids)) > config.PRESET_COMPOSITION_MAX_ITEMS:
        errors.append(f"单个文档最多引用 {config.PRESET_COMPOSITION_MAX_ITEMS} 个预设")
    blocked_text = content_filter.is_hard_blocked(f"{positive} {negative}")
    restriction_blocked = restriction_enabled and rating == "R18"
    if blocked_text:
        errors.append("内容命中永久禁止规则")
    if restriction_blocked:
        errors.append("内容限制已开启，已阻止 R18 内容")
    hard_blocked = bool(blocked_text or restriction_blocked)

    return {
        "prompt": positive,
        "negative_prompt": negative,
        "rating": rating,
        "warnings": warnings,
        "errors": errors,
        "blocked": hard_blocked,
        "used_ids": list(dict.fromkeys(used_ids)),
        "roles": [
            {
                "id": item["id"],
                "role_id": item["role_id"],
                "display_name": item["display_name"],
                "order": item["order"],
            }
            for item in characters
        ],
        "resolved_document": document,
        "template_version": TEMPLATE_VERSION,
    }


def apply_appearance_preset(document: dict, preset: dict, role_ids: list[str]) -> dict:
    """Apply one appearance preset to selected characters without sharing arrays."""
    normalized = normalize_document(document)
    selected = set(role_ids)
    ref = {"preset_id": preset["preset_id"], "version": int(preset.get("version") or 1)}
    for character in normalized["characters"]:
        if character["id"] not in selected and character["role_id"] not in selected:
            continue
        for kind, field in (
            ("appearance", "appearance_tags"),
            ("clothing", "clothing_tags"),
            ("expression", "expression_tags"),
        ):
            block = character[kind]
            block["tags"] = _merge_tags(block.get("tags") or [], preset.get(field) or [])
            block["preset_refs"] = [
                item
                for item in block.get("preset_refs") or []
                if item.get("preset_id") != ref["preset_id"]
            ]
            block["preset_refs"].append(dict(ref))
            block["preset_snapshot"] = {
                "name": preset.get("name") or "",
                "category": preset.get("category") or "",
                "appearance_tags": _tags(preset.get("appearance_tags") or []),
                "clothing_tags": _tags(preset.get("clothing_tags") or []),
                "expression_tags": _tags(preset.get("expression_tags") or []),
                "note": preset.get("note") or "",
            }
    return normalized
