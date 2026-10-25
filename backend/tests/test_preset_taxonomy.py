"""Two-level preset taxonomy, compatibility, and asset-intent tests."""
from __future__ import annotations

import body_modification_presets
import clothing_presets
import expansion_presets
import preset_taxonomy
import prompt_agent
import scene_presets
import toy_presets


def _enriched(kind: str) -> list[dict]:
    data = {
        "pose": prompt_agent.POSE_PRESETS,
        "clothing": clothing_presets.CLOTHING_PRESETS,
        "scene": scene_presets.SCENE_PRESETS,
        "body": body_modification_presets.BODY_MODIFICATION_PRESETS,
        "expansion": expansion_presets.EXPANSION_PRESETS,
        "toy": toy_presets.TOY_PRESETS,
    }[kind]
    return preset_taxonomy.enrich_presets(kind, data)


def test_all_presets_have_valid_two_level_taxonomy_and_asset_intents() -> None:
    for kind in ("pose", "clothing", "scene", "body", "expansion", "toy"):
        items = _enriched(kind)
        assert items
        valid_groups = set(preset_taxonomy.CATEGORY_GROUPS[kind])
        for item in items:
            assert item["category_group"] in valid_groups
            assert item["subcategory"] in preset_taxonomy.SUBCATEGORIES[kind][item["category_group"]]
            assert isinstance(item["sort_order"], int)
            assert isinstance(item["asset_intent"], list)
            assert set(item["asset_intent"]) <= set(preset_taxonomy.ASSET_INTENTS)

    assert len(preset_taxonomy.CATEGORY_GROUPS["pose"]) == 6
    assert len(preset_taxonomy.CATEGORY_GROUPS["clothing"]) == 7
    assert len(preset_taxonomy.CATEGORY_GROUPS["scene"]) == 5
    assert len(preset_taxonomy.CATEGORY_GROUPS["body"]) == 5


def test_explicit_asset_intent_ids_exist() -> None:
    clothing_ids = {item["id"] for item in clothing_presets.CLOTHING_PRESETS}
    scene_ids = {item["id"] for item in scene_presets.SCENE_PRESETS}
    for values in (
        preset_taxonomy._CLOTHING_LATEX_IDS,
        preset_taxonomy._CLOTHING_LEATHER_IDS,
        preset_taxonomy._CLOTHING_MECHANICAL_IDS,
        preset_taxonomy._CLOTHING_CYBERNETIC_IDS,
        preset_taxonomy._CLOTHING_ARMOR_IDS,
        preset_taxonomy._CLOTHING_RESTRAINT_IDS,
    ):
        assert values <= clothing_ids
    for values in (
        preset_taxonomy._SCENE_LATEX_IDS,
        preset_taxonomy._SCENE_LEATHER_IDS,
        preset_taxonomy._SCENE_MECHANICAL_IDS,
        preset_taxonomy._SCENE_INDUSTRIAL_IDS,
        preset_taxonomy._SCENE_CYBERNETIC_IDS,
        preset_taxonomy._SCENE_RESTRAINT_IDS,
    ):
        assert values <= scene_ids


def test_asset_intents_allow_only_explicit_themes() -> None:
    clothing = {item["id"]: item for item in _enriched("clothing")}
    scenes = {item["id"]: item for item in _enriched("scene")}
    poses = {item["id"]: item for item in _enriched("pose")}
    body = {item["id"]: item for item in _enriched("body")}

    assert "latex" in clothing["latex_catsuit"]["asset_intent"]
    assert "latex" in clothing["mirror_vinyl_bodysuit"]["asset_intent"]
    assert "mechanical" in clothing["mecha_pilot_suit"]["asset_intent"]
    assert "armor" in clothing["knight_armor"]["asset_intent"]
    assert "restraint_hardware" not in clothing["cage_bodysuit_harness"]["asset_intent"]
    assert scenes["scene_laundry_corner"]["asset_intent"] == []
    assert scenes["scene_cage_frame"]["category_group"] == "主题展示"
    assert scenes["scene_cage_frame"]["subcategory"] == "展示陈列"
    assert scenes["scene_cage_frame"]["asset_intent"] == []
    assert scenes["scene_chrome_runway_cage"]["category_group"] == "主题展示"
    assert scenes["scene_chrome_runway_cage"]["subcategory"] == "展示陈列"
    assert scenes["scene_chrome_runway_cage"]["asset_intent"] == []
    assert "cybernetic" in scenes["scene_prosthetic_maintenance_capsule"]["asset_intent"]
    assert scenes["scene_space_deck"]["category_group"] == "主题展示"
    assert scenes["scene_space_deck"]["subcategory"] == "展示陈列"
    assert scenes["scene_underground_pool"]["asset_intent"] == []
    assert "mechanical" in scenes["scene_biomech_ritual_garden"]["asset_intent"]
    assert "industrial_device" not in scenes["scene_biomech_ritual_garden"]["asset_intent"]
    for preset_id in preset_taxonomy._SCENE_MECHANICAL_IDS - {"scene_biomech_ritual_garden"}:
        assert {"mechanical", "industrial_device"} <= set(
            scenes[preset_id]["asset_intent"]
        )
    assert poses["solo_speculum_back_supported"]["category_group"] == "单人 R18"
    assert poses["solo_speculum_back_supported"]["subcategory"] == "玩具"
    assert "industrial_device" not in poses["solo_speculum_back_supported"]["asset_intent"]
    assert poses["solo_speculum_frame_support"]["category_group"] == "单人 R18"
    assert poses["solo_speculum_frame_support"]["subcategory"] == "玩具"
    assert poses["solo_speculum_frame_support"]["asset_intent"] == []
    assert "industrial_device" not in poses["solo_speculum_frame_support"]["asset_intent"]
    assert poses["solo_speculum_frame_stand"]["category_group"] == "单人 R18"
    assert poses["solo_speculum_frame_stand"]["subcategory"] == "玩具"
    assert poses["solo_speculum_frame_stand"]["asset_intent"] == []
    assert poses["solo_prolapse_speculum"]["category_group"] == "单人 R18"
    assert poses["solo_prolapse_speculum"]["subcategory"] == "极限"
    assert poses["solo_prolapse_speculum"]["asset_intent"] == []
    for preset_id in (
        "solo_spread_pussy_front",
        "solo_spread_pussy_sitting",
        "solo_spread_pussy_side",
        "solo_spread_pussy_kneeling",
        "solo_spread_pussy_mirror",
        "solo_two_hand_spread",
        "solo_vaginal_spread_close",
    ):
        assert poses[preset_id]["category_group"] == "单人 R18"
        assert poses[preset_id]["subcategory"] == "展示"
        assert poses[preset_id]["asset_intent"] == []
    assert poses["solo_speculum_front_open"]["category_group"] == "单人 R18"
    assert poses["solo_speculum_front_open"]["subcategory"] == "玩具"
    assert poses["solo_speculum_front_open"]["asset_intent"] == []
    assert poses["solo_dilation_stage_one"]["category_group"] == "单人 R18"
    assert poses["solo_dilation_stage_one"]["subcategory"] == "玩具"
    assert poses["solo_dilation_stage_one"]["asset_intent"] == []
    assert poses["solo_wand_vibrator_seated"]["category_group"] == "单人 R18"
    assert poses["solo_wand_vibrator_seated"]["subcategory"] == "玩具"
    assert poses["solo_wand_vibrator_seated"]["asset_intent"] == []
    assert poses["solo_dilation_afterglow"]["category_group"] == "单人 R18"
    assert poses["solo_dilation_afterglow"]["subcategory"] == "余韵"
    assert {"mechanical", "cybernetic"} <= set(body["mod_neck_port"]["asset_intent"])
    assert {"mechanical", "cybernetic"} <= set(body["mod_spine_ornament"]["asset_intent"])
    assert "leather" not in clothing["alchemist_coat"]["asset_intent"]
    assert "mechanical" not in clothing["alchemist_coat"]["asset_intent"]
    assert body["mod_forearm_rail"]["category_group"] == "义体接口"
    assert body["mod_knee_plate"]["category_group"] == "义体接口"
    assert {"mechanical", "cybernetic"} <= set(body["mod_forearm_rail"]["asset_intent"])
    assert {"mechanical", "cybernetic"} <= set(body["mod_knee_plate"]["asset_intent"])
    assert "mechanical" in clothing["metallic_bodysuit"]["asset_intent"]
    assert "latex" not in clothing["metallic_bodysuit"]["asset_intent"]
    assert "latex" in clothing["glowing_seam_bodysuit"]["asset_intent"]
    assert "cybernetic" in clothing["glowing_seam_bodysuit"]["asset_intent"]
    assert "cybernetic" in clothing["glow_cyber_lingerie"]["asset_intent"]
    assert {
        "mechanical",
        "cybernetic",
        "industrial_device",
        "restraint_hardware",
    } <= set(scenes["scene_hydraulic_restraint_capsule"]["asset_intent"])
    assert {"mechanical", "industrial_device"} <= set(
        scenes["scene_precision_assembly_table"]["asset_intent"]
    )
    assert "mechanical" not in body["mod_lip_ring"]["asset_intent"]
    for preset_id in (
        "mod_spine_ornament",
        "mod_forearm_rail",
        "mod_knee_plate",
        "mod_neck_port",
        "mod_shoulder_panel",
        "mod_hip_module",
    ):
        assert {"mechanical", "cybernetic"} <= set(body[preset_id]["asset_intent"])
    assert {"leather", "armor"} <= set(
        clothing["metal_breastplate_corset"]["asset_intent"]
    )
    assert "latex" not in clothing["metal_breastplate_corset"]["asset_intent"]
    assert "leather" in clothing["o_ring_choker"]["asset_intent"]
    assert "restraint_hardware" not in clothing["o_ring_choker"]["asset_intent"]
    assert "latex" in clothing["rubber_apron"]["asset_intent"]
    assert "leather" not in clothing["rubber_apron"]["asset_intent"]
    assert "latex" not in scenes["scene_polished_gallery"]["asset_intent"]
    assert "leather" not in scenes["scene_polished_gallery"]["asset_intent"]
    assert scenes["scene_polished_gallery"]["category_group"] == "主题展示"
    assert scenes["scene_polished_gallery"]["subcategory"] == "展示陈列"
    assert "leather" not in scenes["scene_chrome_harness_bar"]["asset_intent"]
    assert "restraint_hardware" not in scenes["scene_chrome_harness_bar"]["asset_intent"]
    assert "mechanical" not in scenes["scene_space_deck"]["asset_intent"]
    assert "industrial_device" not in scenes["scene_space_deck"]["asset_intent"]
    assert poses["duo_suspended_embrace"]["category_group"] == "双人常规"
    assert poses["duo_suspended_embrace"]["subcategory"] == "接触"
    assert poses["duo_suspended_embrace"]["asset_intent"] == []
    assert "restraint_hardware" not in scenes["scene_collar_display"]["asset_intent"]
    assert "latex" not in scenes["scene_blindfold_chamber"]["asset_intent"]
    assert "latex" not in scenes["scene_collar_display"]["asset_intent"]
    for preset_id in (
        "blindfold_gag_set",
        "cage_bodysuit_harness",
        "hooded_bodysuit_blindfold_set",
        "hooded_enclosure_dress",
        "leather_wrist_cuffs",
        "leash_chain_bodysuit",
        "lockable_belt_dress",
        "lockable_collar_dress",
        "cage_skirt_corset",
        "modular_full_body_harness",
        "petplay_harness_set",
        "pulley_harness_dress",
        "suspension_harness_dress",
    ):
        assert "restraint_hardware" not in clothing[preset_id]["asset_intent"]
    for preset_id in (
        "ankle_cuff_harness_dress",
        "armbinder_cape_dress",
        "detachable_armbinder_dress",
        "leather_sleepsack_suit",
        "posture_bar_bodysuit",
        "spreader_bar_dress",
        "straitjacket_dress",
        "wrist_thigh_restraint_dress",
    ):
        assert "restraint_hardware" in clothing[preset_id]["asset_intent"]
    for preset_id in ("lying_back", "lying_side", "kneeling", "standing"):
        assert poses[preset_id]["category_group"] == "单人基础"
        assert poses[preset_id]["subcategory"] == "展示"
        assert "restraint_hardware" not in poses[preset_id]["asset_intent"]
    for preset_id in (
        "stage_foreplay_kneeling",
        "stage_ongoing_side_sequence",
        "stage_aftercare_embrace",
        "camera_close_contact",
        "camera_full_body_wide",
        "camera_topdown_pair",
    ):
        assert poses[preset_id]["category_group"] == "双人常规"
    assert poses["stage_restraint_kneeling"]["category_group"] == "束缚/器械"
    assert poses["stage_restraint_kneeling"]["subcategory"] == "双人约束"
    for preset_id in (
        "solo_ankle_cuffs_side_recline",
        "solo_collar_leash_kneel",
        "solo_rope_harness_standing",
        "solo_rope_legging_recline",
        "solo_wrist_cuffs_back_standing",
        "solo_wrist_cuffs_front_kneel",
        "sm_dominant_respondent_standoff",
        "sm_floor_chain_kneel",
        "sm_kneeling_collar_display",
        "sm_sensory_blindfold_kneel",
        "sm_side_restraint_recline",
        "sm_wrist_cuffs_back",
    ):
        assert poses[preset_id]["category_group"] in {"单人基础", "双人常规"}
        assert poses[preset_id]["subcategory"] in {"展示", "接触", "常规"}
        assert "restraint_hardware" not in poses[preset_id]["asset_intent"]
    assert poses["sm_dominant_respondent_standoff"]["category_group"] == "双人常规"
    assert poses["sm_dominant_respondent_standoff"]["subcategory"] == "常规"
    for preset_id in (
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
    ):
        assert poses[preset_id]["category_group"] == "束缚/器械"
        assert poses[preset_id]["subcategory"] in {"单人束缚", "双人约束"}
        assert "restraint_hardware" in poses[preset_id]["asset_intent"]
    assert "cybernetic" not in body["mod_glow_tattoo"]["asset_intent"]
    assert "cybernetic" not in body["mod_crystal_veins"]["asset_intent"]


def test_new_play_and_home_scene_presets_have_clear_taxonomy() -> None:
    poses = {item["id"]: item for item in _enriched("pose")}
    scenes = {item["id"]: item for item in _enriched("scene")}

    expected_pose_groups = {
        "breast_sex_kneeling": ("双人常规", "乳交"),
        "nursing_intimate_side": ("双人常规", "授乳"),
        "consensual_spanking_over_knee": ("双人进阶", "痛感"),
        "leather_paddle_short_flogger_play": ("双人进阶", "痛感"),
        "suede_flogger_sensation_play": ("双人进阶", "痛感"),
        "rattan_sensation_experience": ("双人进阶", "痛感"),
        "wax_play_low_temperature": ("双人进阶", "痛感"),
    }
    for preset_id, expected in expected_pose_groups.items():
        assert (poses[preset_id]["category_group"], poses[preset_id]["subcategory"]) == expected

    for preset_id in (
        "consensual_spanking_over_knee",
        "leather_paddle_short_flogger_play",
        "suede_flogger_sensation_play",
        "rattan_sensation_experience",
        "wax_play_low_temperature",
    ):
        assert poses[preset_id]["asset_intent"] == []

    for preset_id in (
        "scene_home_bathroom",
        "scene_indoor_pool",
        "scene_outdoor_pool",
        "scene_home_garden_courtyard",
    ):
        assert scenes[preset_id]["category_group"] == "日常社交"
        assert scenes[preset_id]["rating"] == "普通"
        assert scenes[preset_id]["asset_intent"] == []

    ordinary_daily_scene_ids = {
        "scene_commuter_platform",
        "scene_pedestrian_overpass",
        "scene_neighborhood_bakery",
        "scene_public_library_reading_room",
        "scene_city_riverside_promenade",
        "scene_weekend_farmers_market",
        "scene_seaside_boardwalk",
        "scene_tropical_resort_lobby",
        "scene_island_beach_cove",
        "scene_lakeside_pier",
        "scene_mountain_lodge",
        "scene_onsen_town_street",
        "scene_farmhouse_kitchen",
        "scene_village_lane",
        "scene_countryside_field_path",
        "scene_orchard_afternoon",
        "scene_small_village_market",
        "scene_farm_greenhouse",
    }
    r18_daily_scene_ids = {
        "scene_love_hotel_suite",
        "scene_apartment_shared_late_night",
        "scene_executive_office_private_lounge",
        "scene_rooftop_private_terrace",
        "scene_city_hotel_balcony",
        "scene_city_loft_apartment_night",
        "scene_beach_cabana_private_night",
        "scene_island_guesthouse_bedroom",
        "scene_lakeside_boat_cabin",
        "scene_mountain_lodge_fireplace",
        "scene_cruise_private_cabin",
        "scene_resort_suite_balcony",
        "scene_farmhouse_private_bedroom",
        "scene_countryside_barn_loft",
        "scene_orchard_picnic_blanket",
        "scene_village_guesthouse_room",
        "scene_vineyard_cottage_evening",
        "scene_countryside_riverside_pavilion",
    }
    for preset_id in ordinary_daily_scene_ids:
        assert scenes[preset_id]["category_group"] == "日常社交"
        assert scenes[preset_id]["rating"] == "普通"
        assert scenes[preset_id]["asset_intent"] == []
    for preset_id in r18_daily_scene_ids:
        assert scenes[preset_id]["category_group"] == "日常社交"
        assert scenes[preset_id]["rating"] == "R18"
        assert scenes[preset_id]["asset_intent"] == []

    new_r18_scene_ids = {
        "scene_opera_private_box",
        "scene_theater_dressing_room",
        "scene_victorian_smoking_room",
        "scene_manor_boudoir",
        "scene_private_wine_cellar",
        "scene_luxury_sleeper_car",
        "scene_desert_oasis_tent",
        "scene_coastal_lighthouse_bedroom",
        "scene_sea_cave_onsen",
        "scene_snowfield_hunting_lodge",
        "scene_bamboo_tea_room_night",
        "scene_forest_treehouse_bedroom",
        "scene_moorish_private_bath",
        "scene_seaside_manor_bedroom",
        "scene_private_observatory_lounge",
        "scene_masquerade_powder_room",
        "scene_vintage_bookbinder_atelier",
        "scene_garden_maze_pavilion",
    }
    new_theme_scene_ids = {
        "scene_moonlit_fae_court",
        "scene_vampire_manor_bedchamber",
        "scene_dragonkin_treasure_room",
        "scene_enchanted_forest_spring",
        "scene_witch_moonlit_cottage",
    }
    for preset_id in new_r18_scene_ids:
        assert scenes[preset_id]["category_group"] == "日常社交"
        assert scenes[preset_id]["rating"] == "R18"
        assert scenes[preset_id]["asset_intent"] == []
    for preset_id in new_theme_scene_ids:
        assert scenes[preset_id]["category_group"] == "主题展示"
        assert scenes[preset_id]["subcategory"] == "异种主题"
        assert scenes[preset_id]["rating"] == "R18"
        assert scenes[preset_id]["asset_intent"] == []


def test_preset_apis_expose_two_level_categories_and_keep_legacy_filters(client) -> None:
    for path, expected_group in (
        ("/api/prompt-agent/pose-presets", "单人基础"),
        ("/api/prompt-agent/clothing-presets", "日常制服"),
        ("/api/prompt-agent/scene-presets", "日常社交"),
        ("/api/prompt-agent/body-modification-presets", "耳部与面部"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        body = response.json()
        assert body["category_groups"]
        assert body["subcategories"]
        assert body["items"]
        assert all(item["category_group"] and item["subcategory"] for item in body["items"])
        assert expected_group in body["category_groups"]

    grouped = client.get(
        "/api/prompt-agent/clothing-presets",
        params={"category_group": "日常制服", "subcategory": "校服制服"},
    )
    assert grouped.status_code == 200
    grouped_items = grouped.json()["items"]
    assert grouped_items
    assert all(
        item["category_group"] == "日常制服" and item["subcategory"] == "校服制服"
        for item in grouped_items
    )

    legacy = client.get(
        "/api/prompt-agent/clothing-presets",
        params={"category": "校服/制服"},
    )
    assert legacy.status_code == 200
    assert {item["id"] for item in legacy.json()["items"]} == {
        item["id"] for item in grouped_items
    }


def test_two_level_filters_keep_r18_restriction(client, monkeypatch) -> None:
    import routers.prompt as prompt_router

    monkeypatch.setattr(prompt_router, "content_restriction_enabled", lambda: True)
    response = client.get(
        "/api/prompt-agent/clothing-presets",
        params={"category_group": "情趣 R18"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["restricted"] is True
    assert body["items"]
    assert all(not item["nsfw"] and item["rating"] != "R18" for item in body["items"])
