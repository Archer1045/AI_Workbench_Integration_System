"""Preset taxonomy compatibility and thumbnail asset-intent rules."""
from __future__ import annotations

from collections.abc import Iterable

import character_presets
import expansion_presets
import toy_presets

ASSET_INTENTS = (
    "mechanical",
    "latex",
    "leather",
    "cybernetic",
    "industrial_device",
    "armor",
    "restraint_hardware",
)

DEFAULT_MAPPING = ("其他", "其他")

POSE_CATEGORY_MAP = {
    "单人构图": ("单人基础", "构图"),
    "动作阶段": ("单人基础", "动作"),
    "镜头变体": ("单人基础", "镜头"),
    "单人展示": ("单人基础", "展示"),
    "单人前戏": ("单人 R18", "前戏"),
    "单人自慰": ("单人 R18", "自慰"),
    "单人玩具": ("单人 R18", "玩具"),
    "单人极限": ("单人 R18", "极限"),
    "单人结束": ("单人 R18", "余韵"),
    "常规": ("双人常规", "常规"),
    "双人接触": ("双人常规", "接触"),
    "双人常规": ("双人常规", "常规"),
    "口交位": ("双人常规", "口交"),
    "手交": ("双人常规", "手交"),
    "足交": ("双人常规", "足交"),
    "乳交": ("双人常规", "乳交"),
    "授乳玩法": ("双人常规", "授乳"),
    "躺姿": ("双人常规", "基础姿势"),
    "跪姿": ("双人常规", "基础姿势"),
    "坐姿": ("双人常规", "基础姿势"),
    "站姿": ("双人常规", "基础姿势"),
    "站立": ("双人常规", "基础姿势"),
    "女同": ("双人常规", "女女"),
    "骑乘位": ("双人进阶", "骑乘"),
    "背后位": ("双人进阶", "背后"),
    "侧位": ("双人进阶", "侧位"),
    "双人玩法": ("双人进阶", "玩法"),
    "痛感玩法": ("双人进阶", "痛感"),
    "3P": ("多人组合", "3P"),
    "群交": ("多人组合", "群交"),
    "多人组合": ("多人组合", "多人"),
    "单人束缚": ("单人基础", "展示"),
    "SM/束缚": ("双人常规", "接触"),
}

CLOTHING_CATEGORY_MAP = {
    "日常服装": ("日常制服", "日常"),
    "校服/制服": ("日常制服", "校服制服"),
    "职业装": ("日常制服", "职业"),
    "泳装/运动": ("日常制服", "泳装运动"),
    "礼服/正式": ("礼服主题", "礼服正式"),
    "民族/主题": ("礼服主题", "民族主题"),
    "内衣/睡衣": ("内衣睡衣", "内衣睡衣"),
    "情趣内衣": ("情趣 R18", "情趣内衣"),
    "兔女郎": ("情趣 R18", "兔女郎"),
    "SM/束缚": ("束缚材质", "约束束带"),
    "乳胶/皮革": ("束缚材质", "乳胶皮革"),
    "配饰": ("配饰鞋袜", "身体饰品"),
    "配饰/鞋袜/材质": ("配饰鞋袜", "鞋袜材质"),
    "鞋": ("配饰鞋袜", "鞋"),
    "袜": ("配饰鞋袜", "袜"),
    "情趣礼服": ("礼服主题", "情趣礼服"),
    "情趣婚纱": ("礼服主题", "情趣婚纱"),
    "情趣泳装": ("日常制服", "情趣泳装"),
}

SCENE_CATEGORY_MAP = {
    "休闲娱乐": ("日常社交", "休闲娱乐"),
    "城市日常": ("日常社交", "城市"),
    "居家日常": ("日常社交", "居家"),
    "旅行季节": ("日常社交", "旅行季节"),
    "校园职场": ("日常社交", "校园职场"),
    "社交活动": ("日常社交", "社交活动"),
    "展示与陈列": ("主题展示", "展示陈列"),
    "主题异种": ("主题展示", "异种主题"),
    "乳胶/皮革": ("主题展示", "乳胶皮革"),
    "权力交换": ("亲密控制", "权力交换"),
    "感官控制": ("亲密控制", "感官控制"),
    "拘束与固定": ("拘束器械", "拘束固定"),
    "器械与工业": ("拘束器械", "器械工业"),
    "身体改造展示": ("身体改造", "展示"),
}

BODY_MODIFICATION_CATEGORY_MAP = {
    category: (category, category)
    for category in ("耳部与面部", "躯干与背部", "四肢", "义体接口", "发光结构")
}
TOY_CATEGORY_MAP = {
    category: (category, category)
    for category in toy_presets.CATEGORIES
}
EXPANSION_CATEGORY_MAP = {
    category: (category, category)
    for category in expansion_presets.CATEGORIES
}

CATEGORY_MAPS = {
    "pose": POSE_CATEGORY_MAP,
    "clothing": CLOTHING_CATEGORY_MAP,
    "scene": SCENE_CATEGORY_MAP,
    "body": BODY_MODIFICATION_CATEGORY_MAP,
    "toy": TOY_CATEGORY_MAP,
    "expansion": EXPANSION_CATEGORY_MAP,
}

_CHARACTER_CLOTHING_OVERRIDES = {
    str(item["outfit_id"]): ("角色服装", str(item["work"]))
    for item in character_presets.BUILTIN_CHARACTER_PRESETS
}

CATEGORY_OVERRIDES = {
    "pose": {
        "lying_back": ("单人基础", "展示"),
        "lying_side": ("单人基础", "展示"),
        "kneeling": ("单人基础", "展示"),
        "standing": ("单人基础", "展示"),
        "solo_speculum_frame_support": ("单人 R18", "玩具"),
        "solo_speculum_frame_stand": ("单人 R18", "玩具"),
        "solo_prolapse_speculum": ("单人 R18", "极限"),
        "solo_spread_pussy_front": ("单人 R18", "展示"),
        "solo_spread_pussy_sitting": ("单人 R18", "展示"),
        "solo_spread_pussy_side": ("单人 R18", "展示"),
        "solo_spread_pussy_kneeling": ("单人 R18", "展示"),
        "solo_spread_pussy_mirror": ("单人 R18", "展示"),
        "solo_two_hand_spread": ("单人 R18", "展示"),
        "solo_vaginal_spread_close": ("单人 R18", "展示"),
        "solo_cage_kneeling": ("束缚/器械", "单人束缚"),
        "solo_spreader_bar_recline": ("束缚/器械", "单人束缚"),
        "solo_spreader_bar_standing": ("束缚/器械", "单人束缚"),
        "solo_suspension_harness": ("束缚/器械", "单人束缚"),
        "solo_suspension_side": ("束缚/器械", "单人束缚"),
        "solo_wrist_chain_overhead": ("束缚/器械", "单人束缚"),
        "stage_foreplay_kneeling": ("双人常规", "接触"),
        "stage_restraint_kneeling": ("束缚/器械", "双人约束"),
        "stage_ongoing_side_sequence": ("双人常规", "常规"),
        "stage_aftercare_embrace": ("双人常规", "接触"),
        "camera_close_contact": ("双人常规", "接触"),
        "camera_full_body_wide": ("双人常规", "常规"),
        "camera_topdown_pair": ("双人常规", "常规"),
        "sm_dominant_respondent_standoff": ("双人常规", "常规"),
        "sm_rope_frame_standing": ("束缚/器械", "双人约束"),
        "sm_suspension_harness_pose": ("束缚/器械", "双人约束"),
        "sm_wall_strap_pose": ("束缚/器械", "双人约束"),
        "sm_wrist_raise_restraint": ("束缚/器械", "双人约束"),
    },
    "scene": {
        "scene_space_deck": ("主题展示", "展示陈列"),
        "scene_cage_frame": ("主题展示", "展示陈列"),
    },
    "clothing": {
        **_CHARACTER_CLOTHING_OVERRIDES,
    },
    "body": {
        "mod_forearm_rail": ("义体接口", "义体接口"),
        "mod_knee_plate": ("义体接口", "义体接口"),
    },
}


def _ordered_groups(
    category_map: dict[str, tuple[str, str]],
    overrides: dict[str, tuple[str, str]] | None = None,
) -> tuple[str, ...]:
    values = list(category_map.values()) + list((overrides or {}).values())
    return tuple(dict.fromkeys(group for group, _ in values))


def _ordered_subcategories(
    category_map: dict[str, tuple[str, str]],
    overrides: dict[str, tuple[str, str]] | None = None,
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    entries = list(category_map.values()) + list((overrides or {}).values())
    for group, subcategory in entries:
        group_values = result.setdefault(group, [])
        if subcategory not in group_values:
            group_values.append(subcategory)
    return {group: tuple(values) for group, values in result.items()}


CATEGORY_GROUPS = {
    kind: _ordered_groups(category_map, CATEGORY_OVERRIDES.get(kind))
    for kind, category_map in CATEGORY_MAPS.items()
}
SUBCATEGORIES = {
    kind: _ordered_subcategories(category_map, CATEGORY_OVERRIDES.get(kind))
    for kind, category_map in CATEGORY_MAPS.items()
}
GROUP_INDEX = {
    kind: {group: index for index, group in enumerate(groups)}
    for kind, groups in CATEGORY_GROUPS.items()
}
SUBCATEGORY_INDEX = {
    kind: {
        group: {subcategory: index for index, subcategory in enumerate(values)}
        for group, values in SUBCATEGORIES[kind].items()
    }
    for kind in CATEGORY_GROUPS
}

_CLOTHING_LATEX_IDS = {
    "bunny_suit_latex",
    "clear_pvc_apron_lingerie",
    "glossy_latex_stockings",
    "glowing_seam_bodysuit",
    "harness_bondage_leotard",
    "inflatable_latex_dress",
    "latex_bondage_dress",
    "latex_boots_dress_set",
    "latex_bow_back_dress",
    "latex_catsuit",
    "latex_corset_garter_set",
    "latex_dress",
    "latex_halter_babydoll",
    "latex_hobble_skirt",
    "latex_kimono_dress",
    "latex_maid",
    "latex_outfit",
    "latex_pencil_skirt_set",
    "latex_qipao",
    "latex_suspenders_leotard",
    "latex_waist_trainer_lingerie",
    "latex_wedding_dress",
    "mirror_vinyl_bodysuit",
    "rubber_apron",
    "transparent_latex_dress",
    "vinyl_gloss_lingerie_set",
}
_CLOTHING_LEATHER_IDS = {
    "ankle_cuff_harness_dress",
    "armbinder_cape_dress",
    "armored_high_boots",
    "blindfold_gag_set",
    "buckled_corset",
    "cage_skirt_corset",
    "collared_bondage_suit",
    "detachable_armbinder_dress",
    "dragon_knight_armor",
    "fingerless_gloves",
    "harness_cage_top",
    "hooded_bodysuit_blindfold_set",
    "hooded_enclosure_dress",
    "leash_chain_bodysuit",
    "leather_biker_harness_dress",
    "leather_bondage_boots",
    "leather_bondage_dress",
    "leather_bridal_harness_dress",
    "leather_corset_garter_set",
    "leather_harness_outfit",
    "leather_high_collar_coat",
    "leather_sleepsack_suit",
    "leather_strap_lingerie",
    "leather_wrist_cuffs",
    "leather_zip_bodysuit",
    "lockable_belt_dress",
    "lockable_collar_dress",
    "metal_breastplate_corset",
    "modular_full_body_harness",
    "o_ring_choker",
    "open_back_harness_catsuit",
    "petplay_harness_set",
    "posture_bar_bodysuit",
    "posture_collar_cape",
    "pulley_harness_dress",
    "restraint_sleeve_dress",
    "rope_harness_bodysuit",
    "spreader_bar_dress",
    "straitjacket_dress",
    "suspension_harness_dress",
    "wrist_thigh_restraint_dress",
}
_CLOTHING_MECHANICAL_IDS = {
    "mecha_pilot_suit",
    "metallic_bodysuit",
}
_CLOTHING_CYBERNETIC_IDS = {
    "cyber_visor",
    "glowing_seam_bodysuit",
    "glow_cyber_lingerie",
}
_CLOTHING_ARMOR_IDS = {
    "armored_high_boots",
    "dragon_knight_armor",
    "knight_armor",
    "metal_breastplate_corset",
    "shadow_assassin_outfit",
}
_CLOTHING_RESTRAINT_IDS = {
    "ankle_cuff_harness_dress",
    "armbinder_cape_dress",
    "detachable_armbinder_dress",
    "leather_sleepsack_suit",
    "posture_bar_bodysuit",
    "spreader_bar_dress",
    "straitjacket_dress",
    "wrist_thigh_restraint_dress",
}

_SCENE_LATEX_IDS = {
    "scene_latex_chamber",
    "scene_latex_showroom",
    "scene_mirror_latex_wet_room",
}
_SCENE_LEATHER_IDS = {
    "scene_black_glass_bondage_salon",
    "scene_cyber_bar",
    "scene_gothic_leather_lounge",
    "scene_leather_harness_room",
    "scene_leather_suspension_lounge",
}
_SCENE_MECHANICAL_IDS = {
    "scene_biomech_ritual_garden",
    "scene_cybernetic_altar",
    "scene_device_display_stage",
    "scene_glowing_implant_atelier",
    "scene_hydraulic_restraint_capsule",
    "scene_lab_frame",
    "scene_magnetic_levitation_chamber",
    "scene_precision_assembly_table",
    "scene_robotic_arm_stage",
    "scene_sensor_bay",
    "scene_servo_suspension_bay",
}
_SCENE_INDUSTRIAL_IDS = {
    "scene_chrome_body_lab",
    "scene_cybernetic_altar",
    "scene_device_display_stage",
    "scene_glowing_implant_atelier",
    "scene_hydraulic_restraint_capsule",
    "scene_lab_frame",
    "scene_magnetic_levitation_chamber",
    "scene_precision_assembly_table",
    "scene_prosthetic_maintenance_capsule",
    "scene_robotic_arm_stage",
    "scene_sensor_bay",
    "scene_servo_suspension_bay",
}
_SCENE_CYBERNETIC_IDS = {
    "scene_chrome_body_lab",
    "scene_cybernetic_altar",
    "scene_glowing_implant_atelier",
    "scene_hydraulic_restraint_capsule",
    "scene_prosthetic_maintenance_capsule",
    "scene_servo_suspension_bay",
}
_SCENE_RESTRAINT_IDS = {
    "scene_canopy_bondage_ring",
    "scene_dungeon_showcase",
    "scene_hydraulic_restraint_capsule",
    "scene_leather_harness_room",
    "scene_leather_suspension_lounge",
    "scene_open_restraint_gallery",
    "scene_padded_x_frame",
    "scene_rope_bed",
    "scene_rope_workshop",
    "scene_servo_suspension_bay",
    "scene_suspension_rig",
    "scene_transparent_restraint_cube",
    "scene_underbed_restraint_rail",
    "scene_wall_brace",
}

_POSE_LATEX_IDS = {"solo_latex_zip_partial"}
_POSE_RESTRAINT_IDS = {
    "solo_cage_kneeling",
    "solo_spreader_bar_recline",
    "solo_spreader_bar_standing",
    "solo_suspension_harness",
    "solo_suspension_side",
    "solo_wrist_chain_overhead",
    "sm_rope_frame_standing",
    "sm_suspension_harness_pose",
    "sm_wall_strap_pose",
    "sm_wrist_raise_restraint",
    "stage_restraint_kneeling",
}

_BODY_MECHANICAL_IDS = {
    "mod_forearm_rail",
    "mod_hip_module",
    "mod_knee_plate",
    "mod_neck_port",
    "mod_palm_connector",
    "mod_shoulder_panel",
    "mod_spine_ornament",
}
_BODY_CYBERNETIC_IDS = {
    "mod_energy_node",
    "mod_forearm_rail",
    "mod_hip_module",
    "mod_knee_plate",
    "mod_neck_port",
    "mod_palm_connector",
    "mod_shoulder_panel",
    "mod_spine_ornament",
}


def _asset_intents(kind: str, preset: dict) -> list[str]:
    preset_id = str(preset.get("id") or "")
    intents: set[str] = set()

    if kind == "clothing":
        if preset_id in _CLOTHING_LATEX_IDS:
            intents.add("latex")
        if preset_id in _CLOTHING_LEATHER_IDS:
            intents.add("leather")
        if preset_id in _CLOTHING_MECHANICAL_IDS:
            intents.add("mechanical")
        if preset_id in _CLOTHING_CYBERNETIC_IDS:
            intents.add("cybernetic")
        if preset_id in _CLOTHING_ARMOR_IDS:
            intents.add("armor")
        if preset_id in _CLOTHING_RESTRAINT_IDS:
            intents.add("restraint_hardware")
    elif kind == "scene":
        if preset_id in _SCENE_LATEX_IDS:
            intents.add("latex")
        if preset_id in _SCENE_LEATHER_IDS:
            intents.add("leather")
        if preset_id in _SCENE_MECHANICAL_IDS:
            intents.add("mechanical")
        if preset_id in _SCENE_INDUSTRIAL_IDS:
            intents.add("industrial_device")
        if preset_id in _SCENE_CYBERNETIC_IDS:
            intents.add("cybernetic")
        if preset_id in _SCENE_RESTRAINT_IDS:
            intents.add("restraint_hardware")
    elif kind == "body":
        if preset_id in _BODY_MECHANICAL_IDS:
            intents.add("mechanical")
        if preset_id in _BODY_CYBERNETIC_IDS:
            intents.add("cybernetic")
    elif kind == "pose":
        if preset_id in _POSE_LATEX_IDS:
            intents.add("latex")
        if preset_id in _POSE_RESTRAINT_IDS:
            intents.add("restraint_hardware")
    return [intent for intent in ASSET_INTENTS if intent in intents]


def enrich_preset(kind: str, preset: dict, index: int = 0) -> dict:
    """Return a copy with stable category and asset-intent metadata."""
    preset_id = str(preset.get("id") or "")
    category = str(preset.get("category") or "")
    category_map = CATEGORY_MAPS.get(kind, {})
    group, subcategory = CATEGORY_OVERRIDES.get(kind, {}).get(
        preset_id,
        category_map.get(category, DEFAULT_MAPPING),
    )
    group_index = GROUP_INDEX.get(kind, {}).get(group, 999)
    subcategory_index = SUBCATEGORY_INDEX.get(kind, {}).get(group, {}).get(subcategory, 999)
    return {
        **preset,
        "category_group": group,
        "subcategory": subcategory,
        "sort_order": group_index * 1_000_000 + subcategory_index * 10_000 + index,
        "asset_intent": _asset_intents(kind, preset),
    }


def enrich_presets(kind: str, presets: Iterable[dict]) -> list[dict]:
    return [enrich_preset(kind, preset, index) for index, preset in enumerate(presets)]


def matches_category(
    preset: dict,
    category: str = "",
    category_group: str = "",
    subcategory: str = "",
) -> bool:
    if category and category not in {
        str(preset.get("category") or ""),
        str(preset.get("category_group") or ""),
        str(preset.get("subcategory") or ""),
    }:
        return False
    if category_group and preset.get("category_group") != category_group:
        return False
    if subcategory and preset.get("subcategory") != subcategory:
        return False
    return True


def taxonomy_payload(kind: str) -> dict:
    return {
        "category_groups": list(CATEGORY_GROUPS.get(kind, ())),
        "subcategories": {
            group: list(values)
            for group, values in SUBCATEGORIES.get(kind, {}).items()
        },
    }
