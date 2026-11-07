"""属性查询与多角色对比。"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

import config

HAIR_KEYWORDS = ("发色", "头发颜色", "头发是什么色", "什么颜色的头发", "hair color", "hair_color")
EYES_KEYWORDS = ("瞳色", "眼睛颜色", "眼睛是什么色", "眼珠颜色", "eye color", "eye_color")
COMPARE_KEYWORDS = ("对比", "比较", "区别", "分别是什么", "各是什么", "都是什么")

HAIR_TAGS = {
    "black_hair", "brown_hair", "blonde_hair", "white_hair", "grey_hair",
    "silver_hair", "red_hair", "orange_hair", "pink_hair", "purple_hair",
    "blue_hair", "green_hair", "aqua_hair", "multicolored_hair", "gradient_hair",
}
EYES_TAGS = {
    "black_eyes", "brown_eyes", "blue_eyes", "red_eyes", "green_eyes",
    "yellow_eyes", "purple_eyes", "pink_eyes", "orange_eyes", "grey_eyes",
    "aqua_eyes", "heterochromia",
}


def detect_attribute(text: str) -> str | None:
    if any(word in text for word in HAIR_KEYWORDS):
        return "hair"
    if any(word in text for word in EYES_KEYWORDS):
        return "eyes"
    return None


def wants_compare(text: str) -> bool:
    return any(word in text for word in COMPARE_KEYWORDS)


def pick_attribute(appearance: list[str], attribute: str) -> list[str]:
    pool = HAIR_TAGS if attribute == "hair" else EYES_TAGS
    return [tag for tag in appearance if tag in pool]


def _load_appearance(preset_id: str) -> list[str]:
    con = sqlite3.connect(f"{config.DB_PATH.as_uri()}?mode=ro", uri=True)
    row = con.execute(
        "select appearance_tags from character_appearance_presets"
        " where enabled = 1 and preset_id = ?",
        (preset_id,),
    ).fetchone()
    con.close()
    if not row:
        return []
    try:
        return json.loads(row[0] or "[]")
    except json.JSONDecodeError:
        return []


def character_attribute_reply(character: dict[str, Any], attribute: str) -> str:
    label = "发色" if attribute == "hair" else "瞳色"
    values = pick_attribute(character["appearance"], attribute)
    if values:
        return f"{character['name']}的{label}：{'、'.join(values)}"
    return f"{character['name']}目前没有标注{label}。"


def work_attribute_reply(work: str, items: list[dict[str, Any]], attribute: str) -> str:
    label = "发色" if attribute == "hair" else "瞳色"
    lines = [f"「{work}」各角色的{label}："]
    for item in items:
        values = pick_attribute(item["appearance"], attribute)
        lines.append(f"{item['name']}：{'、'.join(values) if values else '（未标注）'}")
    return "\n".join(lines)
