"""Composable outfit sets built from replaceable clothing presets."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import clothing_presets

SCHEMA_VERSION = 1
MAX_ITEMS = 12
MAX_COLOR_LENGTH = 40

SLOTS = (
    "headwear",
    "underwear",
    "top",
    "bottom",
    "outerwear",
    "full_body",
    "legwear",
    "footwear",
    "accessory",
)
SLOT_LABELS = {
    "headwear": "头饰",
    "underwear": "内衣",
    "top": "上装",
    "bottom": "下装",
    "outerwear": "外套",
    "full_body": "全身装",
    "legwear": "袜",
    "footwear": "鞋",
    "accessory": "配饰",
}
MULTI_OCCUPANCY_SLOTS = frozenset(("accessory",))
COLOR_SLOTS = frozenset(("primary", "secondary", "accent"))


class OutfitSetError(ValueError):
    """Raised when an outfit cannot be resolved or contains a conflict."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def _catalog() -> dict[str, dict[str, Any]]:
    return {
        str(item["id"]): item
        for item in clothing_presets.CLOTHING_PRESETS
    }


def _clean_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for entry in value:
        text = str(entry or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _rating(item: dict[str, Any]) -> str:
    return str(item.get("rating") or ("R18" if item.get("nsfw") else "普通"))


def _has_any_tag(item: dict[str, Any], values: tuple[str, ...]) -> bool:
    haystack = " ".join(str(tag) for tag in item.get("tags") or []).casefold()
    return any(value in haystack for value in values)


def infer_slot(item: dict[str, Any]) -> str:
    """Infer the primary wearer slot from the atomic clothing preset."""
    part = str(item.get("part") or "")
    category = str(item.get("category") or "")
    if part == "鞋" or category == "鞋":
        return "footwear"
    if part == "袜":
        return "legwear"
    if part == "上装":
        if _has_any_tag(item, ("jacket", "coat", "cardigan", "blazer")):
            return "outerwear"
        return "top"
    if part == "下装":
        return "bottom"
    if part == "内衣":
        if _has_any_tag(item, ("bodysuit", "leotard", "catsuit", "romper")):
            return "full_body"
        return "underwear"
    if part in {"泳装", "全身"}:
        return "full_body"
    if part == "配饰":
        if _has_any_tag(item, ("hat", "headwear", "veil", "headpiece")):
            return "headwear"
        return "accessory"
    return "full_body"


def default_covers(slot: str, item: dict[str, Any] | None = None) -> list[str]:
    """Return slots hidden by a garment that spans several body areas."""
    if slot != "full_body":
        return []
    covers = ["top", "bottom"]
    if item and _has_any_tag(item, ("bodysuit", "leotard", "catsuit", "romper")):
        covers.append("underwear")
    return covers


def item_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    """Copy prompt-relevant catalog fields so old outfits remain inspectable."""
    return {
        "id": str(item["id"]),
        "label": str(item.get("label") or item["id"]),
        "translation": str(item.get("translation") or ""),
        "category": str(item.get("category") or ""),
        "part": str(item.get("part") or ""),
        "tags": _clean_strings(item.get("tags")),
        "draw_prompt": str(item.get("draw_prompt") or ""),
        "rating": _rating(item),
        "source": str(item.get("source") or "builtin"),
        "schema_version": int(item.get("schema_version") or 1),
        "layer_state": str(item.get("layer_state") or "完整"),
        "materials": _clean_strings(item.get("materials")),
        "accessories": _clean_strings(item.get("accessories")),
    }


def _normalize_colors(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    colors: dict[str, str] = {}
    for key, value in raw.items():
        slot = str(key or "").strip().lower()
        color = str(value or "").strip()
        if not color:
            continue
        if slot not in COLOR_SLOTS:
            raise OutfitSetError(f"不支持的颜色槽：{slot}")
        if len(color) > MAX_COLOR_LENGTH:
            raise OutfitSetError(f"颜色值过长：{slot}")
        colors[slot] = color
    return colors


def _fragment(item: dict[str, Any], colors: dict[str, str]) -> str:
    text = str(item.get("draw_prompt") or "").strip()
    if not text:
        text = ", ".join(_clean_strings(item.get("tags")))
    color_terms = [
        f"{slot} color {value}"
        for slot, value in colors.items()
    ]
    if color_terms:
        return f"{text}, {', '.join(color_terms)}" if text else ", ".join(color_terms)
    return text


def normalize_outfit_payload(
    payload: dict[str, Any],
    *,
    restriction_enabled: bool = False,
) -> dict[str, Any]:
    """Validate and normalize a new outfit draft.

    The result is deterministic and contains only catalog-derived prompts. The
    content hash intentionally covers clothing references and overrides so a
    changed combination cannot reuse an older preview.
    """
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise OutfitSetError("套装 items 必须是数组")
    if not raw_items:
        raise OutfitSetError("套装至少需要一件服装")
    if len(raw_items) > MAX_ITEMS:
        raise OutfitSetError(f"单个套装最多包含 {MAX_ITEMS} 件服装")

    catalog = _catalog()
    normalized: list[dict[str, Any]] = []
    explicit_orders: set[int] = set()
    rating = "普通"
    occupied: dict[str, str] = {}
    enabled_assignment_count: dict[str, int] = {}

    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise OutfitSetError(f"第 {index + 1} 件服装格式无效")
        clothing_id = str(raw_item.get("clothing_id") or "").strip()
        item = catalog.get(clothing_id)
        if not item:
            raise OutfitSetError(f"不存在的服装 ID：{clothing_id or '(空)'}")
        item_rating = _rating(item)
        if restriction_enabled and item_rating == "R18":
            raise OutfitSetError(f"内容限制已开启，不能加入 R18 服装：{item['label']}")
        if item_rating == "R18":
            rating = "R18"

        inferred_slot = infer_slot(item)
        slot = str(raw_item.get("slot") or inferred_slot).strip()
        if slot not in SLOTS:
            raise OutfitSetError(f"不支持的套装槽位：{slot}")
        covers = _clean_strings(raw_item.get("covers"))
        if "covers" not in raw_item:
            covers = default_covers(slot, item)
        unknown_covers = [value for value in covers if value not in SLOTS]
        if unknown_covers:
            raise OutfitSetError(f"不支持的覆盖槽位：{', '.join(unknown_covers)}")
        covers = [value for value in covers if value != slot]

        enabled = raw_item.get("enabled") is not False
        raw_order = raw_item.get("order")
        if raw_order is None:
            order = index
        else:
            try:
                order = int(raw_order)
            except (TypeError, ValueError) as exc:
                raise OutfitSetError(f"第 {index + 1} 件服装的 order 无效") from exc
            if order < 0:
                raise OutfitSetError("套装层级顺序不能为负数")
            if order in explicit_orders:
                raise OutfitSetError(f"套装层级顺序重复：{order}")
            explicit_orders.add(order)

        colors = _normalize_colors(raw_item.get("colors"))
        layer_state = str(
            raw_item.get("layer_state")
            or item.get("layer_state")
            or "完整"
        ).strip()
        if layer_state not in clothing_presets.LAYER_STATES:
            raise OutfitSetError(f"不支持的层次状态：{layer_state}")

        normalized.append(
            {
                "clothing_id": clothing_id,
                "slot": slot,
                "colors": colors,
                "layer_state": layer_state,
                "order": order,
                "enabled": enabled,
                "covers": covers,
                "clothing_version": int(item.get("schema_version") or 1),
                "snapshot": item_snapshot(item),
            }
        )

        if not enabled:
            continue
        for occupied_slot in [slot, *covers]:
            if occupied_slot in occupied and occupied_slot not in MULTI_OCCUPANCY_SLOTS:
                other = occupied[occupied_slot]
                raise OutfitSetError(
                    f"槽位冲突：{SLOT_LABELS[occupied_slot]}同时由 {other} 和 {clothing_id} 占用"
                )
            occupied.setdefault(occupied_slot, clothing_id)
        enabled_assignment_count[slot] = enabled_assignment_count.get(slot, 0) + 1
        if (
            slot in MULTI_OCCUPANCY_SLOTS
            and enabled_assignment_count[slot] > 4
        ):
            raise OutfitSetError(f"{SLOT_LABELS[slot]}最多 4 件")

    normalized.sort(key=lambda item: (int(item["order"]), item["clothing_id"]))
    for order, item in enumerate(normalized):
        item["order"] = order

    enabled_items = [item for item in normalized if item["enabled"]]
    if not enabled_items:
        raise OutfitSetError("套装至少需要一件启用的服装")
    prompt = ", ".join(
        fragment
        for item in enabled_items
        if (fragment := _fragment(item["snapshot"], item["colors"]))
    )
    hash_payload = [
        {
            "clothing_id": item["clothing_id"],
            "slot": item["slot"],
            "colors": item["colors"],
            "layer_state": item["layer_state"],
            "enabled": item["enabled"],
            "covers": item["covers"],
            "order": item["order"],
            "clothing_version": item["clothing_version"],
            "tags": item["snapshot"]["tags"],
            "draw_prompt": item["snapshot"]["draw_prompt"],
        }
        for item in normalized
    ]
    content_hash = hashlib.sha256(
        json.dumps(
            hash_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    name = str(payload.get("name") or "未命名套装").strip()
    if not name:
        raise OutfitSetError("套装名称不能为空")
    if len(name) > 80:
        raise OutfitSetError("套装名称最多 80 个字符")
    description = str(payload.get("description") or "").strip()
    if len(description) > 500:
        raise OutfitSetError("套装说明最多 500 个字符")
    category = str(payload.get("category") or "用户套装").strip() or "用户套装"
    gender_scope = str(payload.get("gender_scope") or "女").strip() or "女"
    character_scope = _clean_strings(payload.get("character_scope"))

    warnings: list[str] = []
    seen_tags: set[str] = set()
    duplicate_tags: set[str] = set()
    for item in enabled_items:
        for tag in item["snapshot"]["tags"]:
            key = tag.casefold()
            if key in seen_tags:
                duplicate_tags.add(tag)
            seen_tags.add(key)
    if duplicate_tags:
        warnings.append(
            f"不同服装包含重复标签：{', '.join(sorted(duplicate_tags))}"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "description": description,
        "category": category,
        "gender_scope": gender_scope,
        "character_scope": character_scope,
        "rating": rating,
        "prompt": prompt,
        "content_hash": content_hash,
        "occupied_slots": sorted(occupied),
        "warnings": warnings,
        "items": normalized,
    }


def render_outfit_prompt(items: list[dict[str, Any]]) -> str:
    """Render stored item snapshots in their saved layer order."""
    fragments: list[str] = []
    for item in sorted(
        (entry for entry in items if entry.get("enabled", True)),
        key=lambda entry: int(entry.get("order") or 0),
    ):
        snapshot = item.get("snapshot") if isinstance(item.get("snapshot"), dict) else {}
        fragment = _fragment(snapshot, item.get("colors") or {})
        if fragment:
            fragments.append(fragment)
    return ", ".join(fragments)


BUILTIN_OUTFITS: tuple[dict[str, Any], ...] = (
    {
        "preset_id": "outfit_campus_cream",
        "name": "奶油校园",
        "description": "JK 校服搭配乐福鞋与贝雷帽。",
        "category": "校园",
        "items": [
            {"clothing_id": "school_uniform_jk"},
            {"clothing_id": "shoe_black_leather_loafers"},
            {"clothing_id": "hat"},
        ],
    },
    {
        "preset_id": "outfit_office_noir",
        "name": "夜色办公",
        "description": "深色职业装搭配高跟鞋和颈饰。",
        "category": "职业",
        "items": [
            {"clothing_id": "office_lady_ol"},
            {"clothing_id": "shoe_black_stiletto_heels"},
            {"clothing_id": "choker_necklace"},
        ],
    },
    {
        "preset_id": "outfit_gothic_tea",
        "name": "哥特下午茶",
        "description": "哥特洋装、白色过膝袜与薄纱头饰。",
        "category": "主题",
        "items": [
            {"clothing_id": "gothic_lolita"},
            {"clothing_id": "white_lace_thighhigh_stockings"},
            {"clothing_id": "shoe_mary_janes"},
            {"clothing_id": "veiled_headpiece"},
        ],
    },
    {
        "preset_id": "outfit_ivory_ball",
        "name": "象牙舞会",
        "description": "舞会礼服搭配长手套与象牙白高跟长靴。",
        "category": "礼服",
        "items": [
            {"clothing_id": "ball_gown"},
            {"clothing_id": "long_gloves"},
            {"clothing_id": "shoe_ivory_thigh_high_heel_boots"},
            {"clothing_id": "veiled_headpiece"},
        ],
    },
    {
        "preset_id": "outfit_qipao_red",
        "name": "红漆旗袍",
        "description": "旗袍搭配红色漆皮高跟鞋和颈饰。",
        "category": "民族",
        "items": [
            {"clothing_id": "qipao"},
            {"clothing_id": "shoe_red_patent_stiletto_heels"},
            {"clothing_id": "choker_necklace"},
        ],
    },
    {
        "preset_id": "outfit_hanfu_moon",
        "name": "月下汉服",
        "description": "正式汉服搭配芭蕾平底鞋和薄纱头饰。",
        "category": "民族",
        "items": [
            {"clothing_id": "hanfu_formal"},
            {"clothing_id": "shoe_ballet_flats"},
            {"clothing_id": "veiled_headpiece"},
        ],
    },
    {
        "preset_id": "outfit_maid_sunday",
        "name": "周日女仆",
        "description": "经典女仆装搭配白色过膝袜和玛丽珍鞋。",
        "category": "主题",
        "items": [
            {"clothing_id": "maid_outfit"},
            {"clothing_id": "white_lace_thighhigh_stockings"},
            {"clothing_id": "shoe_mary_janes"},
            {"clothing_id": "choker_necklace"},
        ],
    },
    {
        "preset_id": "outfit_summer_boardwalk",
        "name": "夏日海滨",
        "description": "夏日连衣裙搭配细带凉鞋与宽檐帽。",
        "category": "日常",
        "items": [
            {"clothing_id": "summer_dress"},
            {"clothing_id": "shoe_strappy_sandals"},
            {"clothing_id": "hat"},
        ],
    },
    {
        "preset_id": "outfit_winter_layer",
        "name": "冬日层次",
        "description": "冬日大衣搭配不透黑色连裤袜和短靴。",
        "category": "日常",
        "items": [
            {"clothing_id": "winter_coat"},
            {"clothing_id": "opaque_black_pantyhose"},
            {"clothing_id": "shoe_black_ankle_boots"},
        ],
    },
    {
        "preset_id": "outfit_formal_after_dark",
        "name": "暗夜礼服",
        "description": "露背晚礼服搭配歌剧长手套和黑色细高跟。",
        "category": "礼服",
        "items": [
            {"clothing_id": "backless_evening_dress"},
            {"clothing_id": "long_gloves"},
            {"clothing_id": "shoe_black_stiletto_heels"},
            {"clothing_id": "choker_necklace"},
        ],
    },
    {
        "preset_id": "outfit_tulle_garden",
        "name": "薄纱花园",
        "description": "欧根纱罩衫与层叠薄纱中长裙的轻层次组合。",
        "category": "日常",
        "items": [
            {"clothing_id": "organza_overlay_shirt"},
            {"clothing_id": "tulle_tiered_midi_skirt"},
            {"clothing_id": "shoe_ballet_flats"},
            {"clothing_id": "hat"},
        ],
    },
    {
        "preset_id": "outfit_beach_cobalt",
        "name": "钴蓝海滩",
        "description": "学校泳装搭配凉鞋与遮阳帽。",
        "category": "泳装",
        "items": [
            {"clothing_id": "school_swimsuit"},
            {"clothing_id": "shoe_strappy_sandals"},
            {"clothing_id": "hat"},
        ],
    },
)
