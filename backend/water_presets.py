"""Reusable water-scene modifiers for existing pose and scene presets."""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1
CATEGORIES = ("浸水状态", "动态水体", "湿身细节", "环境氛围")
WATER_LEVELS = ("浅水", "膝水", "腰水", "全身", "环境")
TARGETS = ("角色", "环境")


def _preset(
    preset_id: str,
    category: str,
    label: str,
    translation: str,
    tags: tuple[str, ...],
    water_level: str,
    target: str,
    intensity: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "id": f"water_{preset_id}",
        "category": category,
        "label": label,
        "translation": translation,
        "tags": list(tags),
        "water_level": water_level,
        "target": target,
        "intensity": intensity,
        "rating": "普通",
        "nsfw": False,
        "source": "builtin",
    }


WATER_PRESETS: list[dict[str, Any]] = [
    _preset(
        "standing_shallow",
        "浸水状态",
        "浅水站立",
        "角色站在浅水中，水面到脚踝或小腿，腿部周围有细小水纹",
        ("standing in shallow water", "water at ankles", "gentle water ripples", "wet feet"),
        "浅水",
        "角色",
        "轻",
    ),
    _preset(
        "wading_knee",
        "浸水状态",
        "涉水到膝",
        "角色涉水前行，水面接近膝部，身体重心与腿部动作清楚",
        ("wading in knee-deep water", "waterline near knees", "ripples around legs", "wet clothing hem"),
        "膝水",
        "角色",
        "中",
    ),
    _preset(
        "half_submerged",
        "浸水状态",
        "半身浸水",
        "角色身体下半部浸在水中，腰线附近形成清晰水纹和反光",
        ("waist-deep water", "half-submerged body", "waterline at waist", "water surface reflections"),
        "腰水",
        "角色",
        "中",
    ),
    _preset(
        "floating",
        "浸水状态",
        "漂浮水面",
        "角色放松漂浮在水面，身体轮廓和四肢保持清楚",
        ("floating on water", "relaxed floating pose", "water surface reflections", "clear body silhouette"),
        "全身",
        "角色",
        "中",
    ),
    _preset(
        "pool_edge_sit",
        "浸水状态",
        "池边坐姿",
        "角色坐在池边，双脚浸入水中，池水与地面接触关系明确",
        ("sitting on pool edge", "feet in water", "water droplets", "poolside reflections"),
        "浅水",
        "角色",
        "轻",
    ),
    _preset(
        "wet_hair",
        "湿身细节",
        "湿发",
        "头发被水打湿，发束贴服并带有清晰水滴",
        ("wet hair", "damp hair strands", "water droplets", "glistening hair"),
        "环境",
        "角色",
        "轻",
    ),
    _preset(
        "wet_skin",
        "湿身细节",
        "湿身",
        "皮肤表面带水光和水滴，但人体结构与服装边界保持清楚",
        ("wet skin", "water droplets on skin", "subtle glossy sheen", "natural skin texture"),
        "环境",
        "角色",
        "中",
    ),
    _preset(
        "surface_ripples",
        "动态水体",
        "水面涟漪",
        "角色动作周围形成环形水纹和破碎倒影",
        ("water surface ripples", "concentric water rings", "broken reflections", "gentle water movement"),
        "环境",
        "环境",
        "中",
    ),
    _preset(
        "splash",
        "动态水体",
        "水花飞溅",
        "动作接触水面时产生受控水花，不遮挡人物面部与四肢",
        ("water splash", "controlled droplets", "dynamic water spray", "faces and limbs unobstructed"),
        "环境",
        "环境",
        "强",
    ),
    _preset(
        "steam",
        "环境氛围",
        "温泉蒸汽",
        "温泉或浴池上方升起柔和蒸汽，形成空气透视",
        ("rising steam", "hot spring mist", "soft atmospheric haze", "warm diffused light"),
        "环境",
        "环境",
        "中",
    ),
    _preset(
        "underwater_caustics",
        "环境氛围",
        "水下光斑",
        "水下光线折射成流动光斑，水体呈蓝绿色层次",
        ("underwater light caustics", "blue-green water glow", "floating particles", "refracted light"),
        "全身",
        "环境",
        "强",
    ),
    _preset(
        "misty_reflection",
        "环境氛围",
        "雾面倒影",
        "低角度薄雾叠加平静水面倒影，保持人物边缘可辨识",
        ("low mist over water", "still water reflection", "soft reflected lights", "readable silhouettes"),
        "环境",
        "环境",
        "轻",
    ),
]

WATER_PRESETS_BY_ID = {
    str(item["id"]): item for item in WATER_PRESETS
}
