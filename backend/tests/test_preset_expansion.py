"""场景、身体改造、组合器与提示词集组合元数据测试。"""
from __future__ import annotations

import json

import body_modification_presets
import clothing_presets
import prompt_agent
import pytest
import scene_presets
import preset_composer


def test_scene_presets_are_static_and_humanoid_only() -> None:
    assert len(scene_presets.SCENE_PRESETS) == 218
    ids = [item["id"] for item in scene_presets.SCENE_PRESETS]
    assert len(ids) == len(set(ids))
    assert sum(item["rating"] == "普通" for item in scene_presets.SCENE_PRESETS) == 81
    assert sum(item["rating"] == "R18" for item in scene_presets.SCENE_PRESETS) == 137
    assert {
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
    } <= set(ids)
    new_scene_ids = {
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
        "scene_moonlit_fae_court",
        "scene_vampire_manor_bedchamber",
        "scene_dragonkin_treasure_room",
        "scene_enchanted_forest_spring",
        "scene_witch_moonlit_cottage",
        "scene_family_home_bedroom_older_sister",
        "scene_shared_apartment_bathroom_night",
        "scene_small_apartment_after_dinner",
        "scene_home_study_desk_side",
        "scene_hotel_suite_mirror_room",
        "scene_private_pool_cabana_night",
        "scene_private_onsen_tatami_room",
        "scene_banquet_velvet_lounge_corner",
        "scene_moonlit_courtyard_garden",
        "scene_seaside_cottage_bedroom",
        "scene_mirror_bedroom_cnc_young_pair",
        "scene_warm_bathroom_cnc_young_pair",
        "scene_kitchen_counter_cnc_young_pair",
        "scene_low_sofa_cnc_young_pair",
        "scene_hotel_mirror_suite_cnc",
        "scene_moon_courtyard_stone_bench_cnc",
        "scene_onsen_tatami_cnc",
        "scene_private_pool_water_cnc",
        "scene_banquet_private_lounge_cnc",
        "scene_seaside_cottage_rain_cnc",
    }
    assert new_scene_ids <= set(ids)
    by_id = {item["id"]: item for item in scene_presets.SCENE_PRESETS}
    for preset_id in new_scene_ids:
        item = by_id[preset_id]
        assert item["rating"] == "R18"
        assert item["has_image"] is False
        assert item["image"] is None
    for item in scene_presets.SCENE_PRESETS:
        assert item["schema_version"] == 2
        assert item["category"] in scene_presets.CATEGORIES
        assert item["intensity"] in scene_presets.INTENSITIES
        assert item["rating"] in scene_presets.RATINGS
        assert item["has_image"] is False
        assert item["image"] is None
        assert item["draw_prompt"]
        draw_prompt = item["draw_prompt"].lower()
        assert "bestiality" not in draw_prompt
        assert "zoophilia" not in draw_prompt
        assert "animal sex" not in draw_prompt
        assert "wound" not in draw_prompt


def test_scene_prompt_variants_separate_empty_and_occupied_people_policy() -> None:
    assert len(scene_presets.SCENE_PRESETS) == 218
    empty_items = [
        item
        for item in scene_presets.SCENE_PRESETS
        if item["people_policy"] == "empty"
    ]
    assert len(empty_items) == 104
    assert sum(
        bool(scene_presets.PEOPLE_EXCLUSION_PATTERN.search(item["draw_prompt"]))
        for item in scene_presets.SCENE_PRESETS
    ) == 104
    for item in scene_presets.SCENE_PRESETS:
        assert item["people_policy"] in {"empty", "occupied"}
        assert item["empty_scene_prompt"]
        assert item["occupied_scene_prompt"]
        assert not scene_presets.PEOPLE_EXCLUSION_PATTERN.search(
            item["occupied_scene_prompt"]
        )
        if item["people_policy"] == "empty":
            assert item["empty_scene_prompt"] == item["draw_prompt"]
            assert item["occupied_scene_prompt"] != item["draw_prompt"]
        else:
            assert item["empty_scene_prompt"].endswith("no people")
            assert item["occupied_scene_prompt"] == item["draw_prompt"]


def test_scene_prompt_variant_stripping_preserves_following_scene_constraints() -> None:
    variants = scene_presets.scene_prompt_variants(
        "a garden courtyard with a table, no people and no barbecue grill"
    )
    assert variants["people_policy"] == "empty"
    assert variants["empty_scene_prompt"] == (
        "a garden courtyard with a table, no people and no barbecue grill"
    )
    assert variants["occupied_scene_prompt"] == (
        "a garden courtyard with a table and no barbecue grill"
    )


def test_multi_pose_people_count_and_role_slots_are_consistent() -> None:
    multi_poses = [
        item
        for item in prompt_agent.POSE_PRESETS
        if item.get("people") in {"双人", "多人"}
    ]
    assert len(multi_poses) == 303
    assert sum(item["people"] == "双人" for item in multi_poses) == 280
    assert sum(item["people"] == "多人" for item in multi_poses) == 23
    assert sum(len(item["role_slots"]) == 2 for item in multi_poses) == 280
    assert sum(len(item["role_slots"]) == 3 for item in multi_poses) == 17
    assert sum(len(item["role_slots"]) == 4 for item in multi_poses) == 6
    number_words = {
        2: "two",
        3: "three",
        4: "four",
        5: "five",
        6: "six",
    }
    for item in multi_poses:
        assert item["people_count"] == len(item["role_slots"])
        assert item["people_prompt"].startswith(
            f"exactly {number_words[item['people_count']]} people"
        )
        assert "separate bodies" in item["people_prompt"]


def test_body_modification_presets_are_finished_static_results() -> None:
    assert len(body_modification_presets.BODY_MODIFICATION_PRESETS) == 27
    ids = [item["id"] for item in body_modification_presets.BODY_MODIFICATION_PRESETS]
    assert len(ids) == len(set(ids))
    for item in body_modification_presets.BODY_MODIFICATION_PRESETS:
        assert item["schema_version"] == 2
        assert item["category"] in body_modification_presets.CATEGORIES
        assert item["modification_type"] in body_modification_presets.MODIFICATION_TYPES
        assert item["location"] in body_modification_presets.LOCATIONS
        assert item["intensity"] in body_modification_presets.INTENSITIES
        assert item["has_image"] is False
        assert item["image"] is None
        assert item["draw_prompt"]
        draw_prompt = item["draw_prompt"].lower()
        assert "bleeding" not in draw_prompt
        assert "infection" not in draw_prompt
        assert "medical risk" not in draw_prompt


def test_non_mechanical_preset_expansion_is_complete() -> None:
    expected = {
        "pose": {
            "pose_window_glance_back",
            "pose_kneeling_with_flowers",
            "pose_shared_reading",
            "pose_sofa_embrace",
            "pose_slow_dance_embrace",
        },
        "clothing": {
            "british_academy_uniform",
            "florist_apron_outfit",
            "french_countryside_dress",
            "modern_chinese_banquet_dress",
            "velvet_ribbon_lingerie_set",
        },
        "scene": {
            "scene_rainy_night_study",
            "scene_old_town_flower_shop",
            "scene_rooftop_stargazing_tea",
            "scene_autumn_maple_walk",
            "scene_school_music_room",
        },
        "body": {
            "mod_petal_ear_jewelry",
            "mod_butterfly_eye_trace",
            "mod_starlight_back_chain",
            "mod_vine_arm_wrap",
            "mod_firefly_floral_veins",
        },
    }
    collections = {
        "pose": prompt_agent.POSE_PRESETS,
        "clothing": clothing_presets.CLOTHING_PRESETS,
        "scene": scene_presets.SCENE_PRESETS,
        "body": body_modification_presets.BODY_MODIFICATION_PRESETS,
    }
    forbidden_style_terms = (
        "mechanical",
        "cybernetic",
        "industrial",
        "mecha",
        "robot",
        "servo",
        "机械",
        "工业",
        "义体",
        "赛博",
        "机甲",
    )
    new_items: list[dict] = []
    for kind, preset_ids in expected.items():
        by_id = {item["id"]: item for item in collections[kind]}
        assert preset_ids <= set(by_id)
        for preset_id in preset_ids:
            item = by_id[preset_id]
            assert item.get("has_image") is False
            if "image" in item:
                assert item["image"] is None
            searchable = " ".join(
                [
                    str(item.get("id") or ""),
                    str(item.get("label") or ""),
                    str(item.get("translation") or ""),
                    str(item.get("category") or ""),
                    *[str(tag) for tag in item.get("tags") or []],
                ]
            ).lower()
            assert not any(term in searchable for term in forbidden_style_terms)
            new_items.append(item)
    assert len(new_items) == 20


def test_pain_piercing_play_and_support_expansion_is_complete() -> None:
    expected_pose_ids = {
        "solo_mirror_nipple_jewelry_tension",
        "solo_navel_chain_guided_tension",
        "solo_intimate_jewelry_insertion_feedback",
        "solo_dual_toy_alternating_rhythm",
        "solo_kneeling_dilation_pain_feedback",
        "solo_wall_supported_toy_insertion",
        "solo_piercing_tension_release_afterplay",
        "duo_face_to_face_hair_pull_feedback",
        "duo_front_rear_jewelry_tension",
        "duo_cowgirl_piercing_control",
        "duo_side_entry_bite_feedback",
        "duo_partner_guided_dilation_pain",
        "duo_oral_nipple_jewelry_tension",
        "duo_lesbian_reciprocal_jewelry_control",
        "duo_scissor_finger_pain_feedback",
        "duo_mutual_remote_toy_control",
        "duo_position_shift_with_jewelry_tension",
        "duo_bathtub_face_to_face_entry",
        "duo_multi_point_piercing_guided_release",
        "duo_slow_withdrawal_pain_afterplay",
    }
    expected_clothing_ids = {
        "silk_open_front_jewelry_bodysuit",
        "lace_backless_jewelry_display_set",
        "velvet_navel_cutout_dress",
        "high_slit_satin_jewelry_gown",
        "wet_look_cutout_swimsuit",
        "latex_open_chest_halter_dress",
        "lace_waist_window_lingerie_set",
        "silk_side_tie_lounge_dress",
        "off_shoulder_velvet_play_dress",
        "lace_thigh_window_garter_set",
        "ear_to_collar_jewelry_chain",
        "chest_jewelry_connector_chain",
        "navel_to_waist_vertical_chain",
        "intimate_jewelry_waist_chain",
        "multi_point_body_jewelry_link_set",
        "upper_arm_piercing_ring_set",
        "thigh_piercing_chain_set",
        "spine_back_jewelry_chain",
        "pearl_body_jewelry_link_set",
        "lace_finger_chain_gloves",
    }
    poses_by_id = {item["id"]: item for item in prompt_agent.POSE_PRESETS}
    clothing_by_id = {item["id"]: item for item in clothing_presets.CLOTHING_PRESETS}
    assert expected_pose_ids <= set(poses_by_id)
    assert expected_clothing_ids <= set(clothing_by_id)
    assert len(expected_pose_ids | expected_clothing_ids) == 40

    for preset_id in expected_pose_ids:
        item = poses_by_id[preset_id]
        assert item["rating"] == "R18"
        assert item["image"] is None
        assert item["has_image"] is False
    for preset_id in expected_pose_ids & set(prompt_agent.SOLO_R18_POSE_IDS):
        assert poses_by_id[preset_id]["people"] == "单人"
    for preset_id in expected_pose_ids - set(prompt_agent.SOLO_R18_POSE_IDS):
        assert poses_by_id[preset_id]["people"] == "双人"

    accessory_ids = {
        "ear_to_collar_jewelry_chain",
        "chest_jewelry_connector_chain",
        "navel_to_waist_vertical_chain",
        "intimate_jewelry_waist_chain",
        "multi_point_body_jewelry_link_set",
        "upper_arm_piercing_ring_set",
        "thigh_piercing_chain_set",
        "spine_back_jewelry_chain",
        "pearl_body_jewelry_link_set",
        "lace_finger_chain_gloves",
    }
    for preset_id in expected_clothing_ids:
        item = clothing_by_id[preset_id]
        assert item["has_image"] is False
        assert item["category"] in clothing_presets.CATEGORIES
    for preset_id in accessory_ids:
        assert clothing_by_id[preset_id]["category"] == "配饰"


def test_adult_pair_visual_age_gap_expansion_is_complete() -> None:
    expected_pose_ids = {
        "young_male_forced_wall_pin_consensual",
        "young_male_forced_kneel_control_consensual",
        "young_male_hair_pull_command_consensual",
        "young_male_forced_toy_insertion_consensual",
        "young_male_intimate_biting_control_consensual",
        "young_male_piercing_tension_control_consensual",
        "sibling_dynamic_mirror_command_consensual",
        "maternal_dynamic_lap_control_consensual",
        "size_contrast_reverse_dominance_consensual",
        "young_pair_pain_aftercare_check_consensual",
    }
    expected_clothing_ids = {
        "pearl_open_hip_babydoll",
        "jewel_frame_open_lower_swimsuit",
        "ribbon_open_chest_lounge_set",
        "pierced_flower_corset_set",
        "cutout_back_coverup_swimsuit",
        "open_waist_velvet_ball_gown",
        "moonstone_open_bust_gown",
        "lace_open_hip_bodysuit",
        "pearl_open_front_nightgown",
        "silk_backless_open_waist_robe",
    }
    poses_by_id = {item["id"]: item for item in prompt_agent.POSE_PRESETS}
    clothing_by_id = {item["id"]: item for item in clothing_presets.CLOTHING_PRESETS}
    assert expected_pose_ids <= set(poses_by_id)
    assert expected_clothing_ids <= set(clothing_by_id)
    for preset_id in expected_pose_ids:
        item = poses_by_id[preset_id]
        assert item["people"] == "双人"
        assert item["rating"] == "R18"
        assert item["image"] is None
        assert item["has_image"] is False
    for preset_id in expected_clothing_ids:
        item = clothing_by_id[preset_id]
        assert item["rating"] == "R18"
        assert item["has_image"] is False


def test_gentle_adult_pair_expansion_is_complete() -> None:
    expected_pose_ids = {
        "gentle_lap_rest_younger_male_consensual",
        "gentle_rear_hug_younger_male_consensual",
        "gentle_bath_wash_younger_male_consensual",
        "gentle_bedtime_cuddle_younger_male_consensual",
        "gentle_apron_embrace_younger_male_consensual",
        "gentle_mirror_dress_help_younger_male_consensual",
    }
    expected_scene_ids = {
        "scene_cozy_apartment_kitchen_evening",
        "scene_shared_bathroom_warm_night",
        "scene_small_bedroom_morning_light",
        "scene_sofa_reading_corner",
        "scene_seaside_cottage_veranda",
        "scene_private_tea_room_rainy_day",
    }
    expected_clothing_ids = {
        "oversized_shirt_soft_loungewear",
        "apron_soft_home_dress",
        "open_shoulder_cotton_nightgown",
        "bath_towel_wrap_set",
        "sheer_seaside_coverup",
        "soft_silk_lap_robe",
    }
    poses_by_id = {item["id"]: item for item in prompt_agent.POSE_PRESETS}
    scenes_by_id = {item["id"]: item for item in scene_presets.SCENE_PRESETS}
    clothing_by_id = {item["id"]: item for item in clothing_presets.CLOTHING_PRESETS}
    assert expected_pose_ids <= set(poses_by_id)
    assert expected_scene_ids <= set(scenes_by_id)
    assert expected_clothing_ids <= set(clothing_by_id)
    for preset_id in expected_pose_ids:
        item = poses_by_id[preset_id]
        assert item["people"] == "双人"
        assert item["rating"] == "普通"
        assert item["image"] is None
        assert item["has_image"] is False
    for preset_id in expected_scene_ids:
        item = scenes_by_id[preset_id]
        assert item["rating"] == "普通"
        assert item["has_image"] is False
    for preset_id in expected_clothing_ids:
        item = clothing_by_id[preset_id]
        assert item["rating"] == "R18"
        assert item["has_image"] is False


def test_r18_adult_pair_30_preset_expansion_is_complete() -> None:
    expected_pose_ids = {
        "cnc_smaller_male_forced_penetration_r18",
        "cnc_smaller_male_forced_oral_r18",
        "cnc_smaller_male_forced_toy_double_r18",
        "cnc_smaller_male_piercing_penetration_r18",
        "cnc_smaller_male_intimate_biting_r18",
        "cnc_sister_dynamic_mirror_penetration_r18",
        "cnc_maternal_dynamic_lap_penetration_r18",
        "cnc_size_contrast_reverse_carry_r18",
        "cnc_young_pair_restraint_toy_r18",
        "cnc_young_pair_pain_aftercare_r18",
        "r18_young_male_guided_tease",
        "r18_young_male_oral_service",
        "r18_young_male_mutual_masturbation",
        "r18_young_male_cowgirl_control",
        "r18_young_male_spooning_intimacy",
        "r18_young_male_bathtub_together",
        "r18_young_male_sofa_lap_sex",
        "r18_young_male_shower_embrace_sex",
        "r18_young_male_gentle_toy_control",
        "r18_young_male_afterglow_embrace",
        "sibling_dynamic_internal_dilation_view_r18",
        "sibling_dynamic_fluid_fill_expansion_r18",
        "sibling_dynamic_solid_fill_expansion_r18",
        "sibling_dynamic_uterine_hand_contact_r18",
        "sibling_dynamic_uterine_tool_contact_r18",
        "sibling_dynamic_internal_urination_visual_r18",
        "sibling_dynamic_mirror_internal_dilation_r18",
        "sibling_dynamic_bathtub_internal_fill_r18",
        "sibling_dynamic_speculum_internal_touch_r18",
        "sibling_dynamic_aftercare_internal_check_r18",
    }
    by_id = {item["id"]: item for item in prompt_agent.POSE_PRESETS}
    assert expected_pose_ids <= set(by_id)
    assert len(expected_pose_ids) == 30
    for preset_id in expected_pose_ids:
        item = by_id[preset_id]
        assert item["people"] == "双人"
        assert item["rating"] == "R18"
        assert item["image"] is None
        assert item["has_image"] is False


def test_preset_payloads_do_not_include_explanatory_qualifiers() -> None:
    payload = json.dumps(
        {
            "poses": prompt_agent.POSE_PRESETS,
            "clothing": clothing_presets.CLOTHING_PRESETS,
            "scenes": scene_presets.SCENE_PRESETS,
            "body_modifications": body_modification_presets.BODY_MODIFICATION_PRESETS,
        },
        ensure_ascii=False,
    ).lower()
    forbidden = (
        "幻想",
        "奇幻",
        "fantasy",
        "no injury",
        "no blood",
        "no procedure",
        "safely spaced",
    )
    for term in forbidden:
        assert term not in payload


def test_scene_api_and_restriction(client, monkeypatch) -> None:
    response = client.get("/api/prompt-agent/scene-presets")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 218
    assert body["restricted"] is False
    assert body["categories"]
    assert body["items"][0]["image"] == "/scene-presets/scene_rope_bed.webp"
    assert body["items"][0]["has_image"] is True
    assert body["items"][0]["people_policy"] in {"empty", "occupied"}
    assert body["items"][0]["empty_scene_prompt"]
    assert body["items"][0]["occupied_scene_prompt"]

    import routers.prompt as prompt_router

    monkeypatch.setattr(prompt_router, "content_restriction_enabled", lambda: True)
    restricted = client.get("/api/prompt-agent/scene-presets").json()
    assert restricted["restricted"] is True
    assert restricted["total"] == 81
    assert all(item["rating"] == "普通" for item in restricted["items"])


def test_body_modification_api_and_restriction(client, monkeypatch) -> None:
    response = client.get("/api/prompt-agent/body-modification-presets")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 27
    assert body["restricted"] is False
    assert any(item["rating"] == "R18" for item in body["items"])
    assert body["items"][0]["image"] == "/body-modification-presets/mod_ear_chain.webp"
    assert body["items"][0]["has_image"] is True

    import routers.prompt as prompt_router

    monkeypatch.setattr(prompt_router, "content_restriction_enabled", lambda: True)
    restricted = client.get("/api/prompt-agent/body-modification-presets").json()
    assert restricted["restricted"] is True
    assert restricted["items"]
    assert all(item["rating"] != "R18" for item in restricted["items"])


def test_preset_catalog_counts_and_restriction(client, monkeypatch) -> None:
    catalog = client.get("/api/prompt-agent/preset-catalog").json()
    assert catalog["restricted"] is False
    assert len(catalog["poses"]) == 446
    assert len(catalog["clothing"]) == 1013
    assert len(catalog["scenes"]) == 218
    assert len(catalog["body_modifications"]) == 27
    assert len(catalog["expansions"]) == 8
    assert len(catalog["toys"]) == 13
    assert next(
        item for item in catalog["poses"] if item["id"] == "duo_face_to_face_seated"
    )["image"] == "/pose-presets/duo_face_to_face_seated.png"
    duo = next(
        item for item in catalog["poses"] if item["id"] == "duo_face_to_face_seated"
    )
    assert duo["people_count"] == 2
    assert duo["people_prompt"] == "exactly two people, two separate bodies"
    assert next(
        item for item in catalog["clothing"] if item["id"] == "bunny_suit_classic"
    )["image"] == "/clothing-presets/bunny_suit_classic.webp"

    import routers.prompt as prompt_router

    monkeypatch.setattr(prompt_router, "content_restriction_enabled", lambda: True)
    restricted = client.get("/api/prompt-agent/preset-catalog").json()
    assert restricted["restricted"] is True
    assert len(restricted["scenes"]) == 81
    assert all(item["rating"] == "普通" for item in restricted["scenes"])
    assert len(restricted["body_modifications"]) == 18


def test_solo_r18_pose_expansion_is_complete_and_solo_safe() -> None:
    assert len(prompt_agent.SOLO_R18_POSE_IDS) == 127
    assert len(prompt_agent.SOLO_R18_POSE_IDS) == len(set(prompt_agent.SOLO_R18_POSE_IDS))
    expected_sentinels = {
        "solo_back_knees_up_touch",
        "solo_remote_toy_standing",
        "solo_wrist_cuffs_front_kneel",
        "solo_kneeling_tremble_afterglow",
        "solo_side_top_leg_reach",
        "solo_speculum_back_supported",
        "solo_object_multi_insertion",
        "solo_prolapse_afterglow",
        "solo_spread_pussy_front",
        "solo_two_hand_spread",
        "solo_speculum_side_open",
        "solo_dilation_afterglow",
        "solo_ice_cube_collarbone_touch",
        "solo_silk_ribbon_wrist_kneel",
        "solo_mirror_leather_glove_touch",
        "solo_warm_towel_aftercare",
        "solo_mirror_nipple_jewelry_tension",
        "solo_navel_chain_guided_tension",
        "solo_intimate_jewelry_insertion_feedback",
        "solo_dual_toy_alternating_rhythm",
        "solo_kneeling_dilation_pain_feedback",
        "solo_wall_supported_toy_insertion",
        "solo_piercing_tension_release_afterplay",
    }
    assert expected_sentinels.issubset(prompt_agent.SOLO_R18_POSE_IDS)

    by_id = {item["id"]: item for item in prompt_agent.POSE_PRESETS}
    for preset_id in prompt_agent.SOLO_R18_POSE_IDS:
        item = by_id[preset_id]
        assert item["people"] == "单人"
        assert item["orientation"] == "单人"
        assert item["role_slots"] == ["主体"]
        assert item["rating"] == "R18"
        assert item["intensity"] in {"强化", "极限"}
        assert item["body_separation"] is False
        assert item["contact_points"]
        assert item["camera"] in {"全景", "全身", "中景", "特写", "俯视", "仰视"}
        assert item["sequence"] in {"前戏", "进行中", "约束", "结束"}
        assert "exactly 1 anime woman" in item["draw_prompt"]
        assert "no second person" in item["draw_prompt"]


def test_pain_play_pose_expansion_is_complete_and_uses_exact_tags() -> None:
    expected = {
        "impact_spanking_over_knee_consensual": [
            "spanking",
            "impact play",
            "over knee",
            "adult",
            "consensual",
        ],
        "impact_spanking_bent_over_consensual": [
            "spanking",
            "bent over",
            "impact play",
            "consensual",
        ],
        "impact_paddle_pose_consensual": [
            "paddle",
            "impact play",
            "controlled intensity",
            "consensual",
        ],
        "impact_riding_crop_pose_consensual": [
            "riding crop",
            "impact play",
            "consensual",
            "controlled intensity",
        ],
        "impact_soft_flogger_back_consensual": [
            "soft flogger",
            "back",
            "impact play",
            "consensual",
        ],
        "wax_drip_back_consensual": [
            "wax play",
            "candle wax",
            "back",
            "temperature play",
        ],
        "wax_drip_chest_consensual": [
            "wax play",
            "candle wax",
            "chest",
            "temperature play",
        ],
        "wax_remove_aftercare_consensual": [
            "wax removal",
            "aftercare",
            "skin check",
            "calm",
        ],
        "nipple_clamp_chain_consensual": [
            "nipple clamps",
            "chain",
            "sensation play",
            "consensual",
        ],
        "nipple_clamp_weight_consensual": [
            "nipple clamps",
            "weights",
            "sensation play",
            "consensual",
        ],
        "clothespin_application_consensual": [
            "clothespins",
            "sensation play",
            "arranged",
            "consensual",
        ],
        "hair_pull_arch_consensual": [
            "hair pulling",
            "back arch",
            "controlled intensity",
            "consensual",
        ],
        "nail_scratch_back_consensual": [
            "nail scratches",
            "back",
            "skin marks",
            "consensual",
        ],
        "love_bite_neck_consensual": [
            "biting",
            "neck",
            "love bite",
            "consensual",
        ],
        "impact_mark_inspection_consensual": [
            "mark inspection",
            "aftercare",
            "skin check",
            "consent",
        ],
        "pain_aftercare_hydration_consensual": [
            "aftercare",
            "hydration",
            "blanket",
            "check-in",
        ],
    }
    by_id = {item["id"]: item for item in prompt_agent.POSE_PRESETS}
    assert set(expected).issubset(by_id)
    for preset_id, tags in expected.items():
        item = by_id[preset_id]
        assert item["category"] == "痛感玩法"
        assert item["tags"] == tags
        assert item["rating"] == "R18"
        assert item["intensity"] in {"标准", "强化", "极限"}
        assert item["people"] == "双人"
        assert item["body_separation"] is False
        assert item["draw_prompt"]
        assert "exactly 2" in item["draw_prompt"].lower()


def test_new_intimate_and_pain_play_expansion_is_complete() -> None:
    expected_duo_ids = {
        "duo_countertop_front_lift",
        "duo_shower_wall_embrace",
        "duo_bathtub_spooning",
        "duo_bathtub_face_to_face",
        "duo_mirror_front_back_embrace",
        "duo_chair_face_to_face_embrace",
        "duo_lap_pillow_soothing",
        "duo_sofa_reclining_mutual_touch",
        "duo_oil_massage_lying",
        "duo_feather_mutual_tease",
        "duo_ice_cube_body_trail",
        "duo_soft_ribbon_wrist_play",
    }
    expected_new_pain_tags = {
        "impact_spanking_standing_wall_consensual": [
            "spanking",
            "standing wall",
            "hard open-hand spanking",
            "impact play",
            "red hand marks",
            "consensual",
        ],
        "impact_paddle_padded_bench_consensual": [
            "hard leather paddle",
            "padded bench",
            "heavy impact play",
            "visible red welt",
            "consensual",
        ],
        "impact_flogger_outer_thigh_consensual": [
            "heavy suede flogger",
            "outer thigh",
            "hard impact play",
            "raised red welts",
            "consensual",
        ],
        "impact_crop_inner_thigh_consensual": [
            "riding crop",
            "inner thigh",
            "sharp impact play",
            "raised red line",
            "consensual",
        ],
        "wax_drip_thigh_consensual": [
            "wax play",
            "low temperature massage candle",
            "outer thigh",
            "layered hot wax",
            "sharp heat sensation",
            "consensual",
        ],
        "wax_drip_abdomen_consensual": [
            "wax play",
            "low temperature massage candle",
            "abdomen",
            "layered hot wax",
            "sharp heat sensation",
            "consensual",
        ],
        "nipple_clamp_light_pull_consensual": [
            "weighted nipple clamps",
            "hard chain pull",
            "sensation pain",
            "visible tension",
            "consensual",
        ],
        "clothespin_removal_aftercare_consensual": [
            "many clothespins",
            "removal pain",
            "deep skin indentations",
            "aftercare",
            "consensual",
        ],
        "hair_pull_kneeling_consensual": [
            "hair pulling",
            "kneeling",
            "firm backward pull",
            "arched neck",
            "pain reaction",
            "consensual",
        ],
        "love_bite_shoulder_consensual": [
            "hard biting",
            "shoulder",
            "deep love bite",
            "teeth indentation",
            "bruised mark",
            "consensual",
        ],
        "nail_scratch_thigh_consensual": [
            "hard nail scratching",
            "outer thigh",
            "raised red scratches",
            "skin indentation",
            "consensual",
        ],
        "ice_cube_chest_abdomen_consensual": [
            "ice cube",
            "deep cold pressure",
            "chest",
            "abdomen",
            "red cold flush",
            "sensation pain",
            "consensual",
        ],
    }
    by_id = {item["id"]: item for item in prompt_agent.POSE_PRESETS}
    assert expected_duo_ids <= set(by_id)
    assert set(expected_new_pain_tags) <= set(by_id)
    assert len(prompt_agent.POSE_PRESETS) == 446
    assert len({item["id"] for item in prompt_agent.POSE_PRESETS}) == 446

    for preset_id in expected_duo_ids:
        item = by_id[preset_id]
        assert item["category"] in {"双人接触", "双人玩法"}
        assert item["people"] == "双人"
        assert item["rating"] == "R18"
        assert item["image"] is None
        assert item["has_image"] is False
        assert len(item["role_slots"]) == 2
        assert item["contact_points"]
        draw_prompt = item["draw_prompt"].lower()
        assert "exactly 2 separate adult anime" in draw_prompt
        assert "one continuous" in draw_prompt
        assert "complete bod" in draw_prompt
        assert "no extra people" in draw_prompt
        assert "no collage" in draw_prompt

    for preset_id, tags in expected_new_pain_tags.items():
        item = by_id[preset_id]
        assert item["category"] == "痛感玩法"
        assert item["tags"] == tags
        assert item["rating"] == "R18"
        assert item["people"] == "双人"
        assert item["body_separation"] is False
        assert item["image"] is None
        assert item["has_image"] is False
        draw_prompt = item["draw_prompt"].lower()
        assert "exactly 2 separate adult anime" in draw_prompt
        assert "one continuous" in draw_prompt
        assert any(
            phrase in draw_prompt
            for phrase in (
                "red",
                "welt",
                "bruis",
                "indentation",
                "flinch",
                "pain reaction",
            )
        )
        assert "controlled distance" not in draw_prompt
        assert "light touch" not in draw_prompt
        assert "no impact marks" not in draw_prompt
        assert "intact unmarked skin" not in draw_prompt
        assert "no tension" not in draw_prompt
        assert "no weights" not in draw_prompt
        assert "no upward tension" not in draw_prompt
        assert "no extra people" in draw_prompt
        assert "no collage" in draw_prompt


def test_extreme_consensual_expansion_is_complete() -> None:
    expected_solo_ids = {
        "solo_dilation_stage_two_braced",
        "solo_dilation_stage_three_supine",
        "solo_dilation_hold_timer_side",
        "solo_dilation_release_aftercare",
        "solo_speculum_to_dilation_sequence",
        "solo_object_ladder_sequence",
        "solo_fisting_partial_hold",
        "solo_labia_clamp_spread",
        "solo_clamp_chain_dilation_combo",
        "solo_body_jewelry_weighted_tension",
        "solo_intimate_jewelry_chain_tension",
        "solo_predicament_dilation_hold",
    }
    expected_duo_ids = {
        "partner_dilation_stage_two_guided",
        "partner_dilation_stage_three_guided",
        "partner_dilation_hold_control",
        "partner_speculum_adjustment_guided",
        "partner_object_ladder_guided",
        "partner_fisting_assist",
        "partner_dual_object_coordinated",
        "partner_labia_clamp_control",
        "partner_nipple_jewelry_tension",
        "partner_intimate_jewelry_traction",
        "partner_body_jewelry_multipoint_traction",
        "partner_restraint_dilation_predicament",
    }
    expected_sm_tags = {
        "sm_nipple_jewelry_weighted_traction_consensual": [
            "nipple jewelry",
            "piercing jewelry",
            "weighted chain",
            "downward traction",
            "sensation pain",
            "consensual",
        ],
        "sm_intimate_jewelry_chain_tension_consensual": [
            "intimate jewelry",
            "piercing jewelry",
            "chain tension",
            "firm pull",
            "sensation pain",
            "consensual",
        ],
        "sm_navel_chain_weighted_consensual": [
            "navel jewelry",
            "piercing jewelry",
            "weighted chain",
            "downward traction",
            "skin tension",
            "consensual",
        ],
        "sm_body_jewelry_multipoint_tension_consensual": [
            "body jewelry",
            "piercing jewelry",
            "multipoint tension",
            "central chain pull",
            "sensation pain",
            "consensual",
        ],
        "sm_wartenberg_wheel_thigh_consensual": [
            "wartenberg wheel",
            "outer thigh",
            "firm rolling pressure",
            "red pressure trails",
            "sensation pain",
            "consensual",
        ],
        "sm_wartenberg_wheel_back_consensual": [
            "wartenberg wheel",
            "upper back",
            "firm rolling pressure",
            "red pressure trails",
            "sensation pain",
            "consensual",
        ],
        "sm_clamp_zipper_chain_pull_consensual": [
            "clamp zipper",
            "clothespins",
            "cord pull",
            "sustained pressure",
            "pain reaction",
            "consensual",
        ],
        "sm_clamp_zipper_release_consensual": [
            "clamp zipper",
            "clothespins",
            "rapid release",
            "concentrated pain spike",
            "pain reaction",
            "consensual",
        ],
        "sm_labia_clamp_weighted_tension_consensual": [
            "labia clamps",
            "weighted clamps",
            "spreader tension",
            "sustained stretch",
            "sensation pain",
            "consensual",
        ],
        "sm_clamp_endurance_timer_consensual": [
            "clamp endurance",
            "clothespins",
            "both thighs",
            "timer",
            "sustained pressure",
            "consensual",
        ],
        "sm_rope_harness_tension_floor_consensual": [
            "rope harness",
            "floor restraint",
            "body tension",
            "low position",
            "predicament",
            "consensual",
        ],
        "sm_predicament_clamp_dilation_hold_consensual": [
            "labia clamps",
            "dilation hold",
            "timer",
            "combined predicament",
            "sustained stretch",
            "consensual",
        ],
    }
    by_id = {item["id"]: item for item in prompt_agent.POSE_PRESETS}
    expected_ids = expected_solo_ids | expected_duo_ids | set(expected_sm_tags)
    assert len(expected_ids) == 36
    assert expected_ids <= set(by_id)

    for preset_id in expected_solo_ids:
        item = by_id[preset_id]
        assert preset_id in prompt_agent.SOLO_R18_POSE_IDS
        assert item["category"].startswith("单人")
        assert item["people"] == "单人"
        assert item["rating"] == "R18"
        assert item["image"] is None
        assert item["has_image"] is False
        assert "exactly 1 anime woman" in item["draw_prompt"]

    for preset_id in expected_duo_ids:
        item = by_id[preset_id]
        assert item["category"] == "双人玩法"
        assert item["people"] == "双人"
        assert item["orientation"] in {"男女", "女女", "中性"}
        assert item["rating"] == "R18"
        assert item["intensity"] == "极限"
        assert item["image"] is None
        assert item["has_image"] is False
        assert item["role_slots"]
        assert item["contact_points"]
        assert "exactly 2 separate adult anime" in item["draw_prompt"]
        assert "no extra people" in item["draw_prompt"]
        assert "no collage" in item["draw_prompt"]

    for preset_id, tags in expected_sm_tags.items():
        item = by_id[preset_id]
        assert item["category"] == "痛感玩法"
        assert item["people"] == "双人"
        assert item["tags"] == tags
        assert item["rating"] == "R18"
        assert item["intensity"] == "极限"
        assert item["image"] is None
        assert item["has_image"] is False
        assert "exactly 2 separate adult anime" in item["draw_prompt"]
        assert "no extra people" in item["draw_prompt"]
        assert "no collage" in item["draw_prompt"]


def test_compose_presets_is_role_aware_and_uses_only_ids_and_colors() -> None:
    result = preset_composer.compose_presets(
        {
            "pose_id": "missionary",
            "clothing": [
                {
                    "id": "school_uniform_jk",
                    "scope": "girlA",
                    "colors": {"primary": "navy", "accent": "red"},
                }
            ],
            "body_modifications": [{"id": "mod_ear_chain", "scope": "all"}],
        }
    )
    assert result["blocked"] is False
    assert result["rating"] == "普通"
    assert result["used_ids"] == ["missionary", "school_uniform_jk", "mod_ear_chain"]
    assert "for the first girl" in result["prompt"]
    assert "primary color navy" in result["prompt"]
    assert "accent color red" in result["prompt"]
    assert "exactly two people" in result["prompt"]
    assert "two separate bodies" in result["prompt"]


def test_compose_presets_uses_occupied_scene_prompt_by_default() -> None:
    result = preset_composer.compose_presets(
        {"scene_id": "scene_home_bathroom"}
    )
    assert "complete home bathroom" in result["prompt"]
    assert "without people" not in result["prompt"]
    assert "no people" not in result["prompt"]


def test_compose_presets_enforces_multi_role_order_and_count() -> None:
    with pytest.raises(preset_composer.ComposeError, match="需要 3 个角色"):
        preset_composer.compose_presets(
            {
                "pose_id": "threesome_2f1m",
                "role_order": ["girlA", "boyA"],
            }
        )
    result = preset_composer.compose_presets(
        {
            "pose_id": "threesome_2f1m",
            "role_order": ["girlA", "girlB", "boyA"],
        }
    )
    assert result["roles"] == ["the first girl", "the second girl", "the first boy"]
    assert result["prompt"].startswith("character roles from left to right:")


def test_compose_presets_rejects_role_scopes_for_single_person_pose() -> None:
    with pytest.raises(preset_composer.ComposeError, match="单人构图"):
        preset_composer.compose_presets(
            {
                "pose_id": "solo_supported_sit",
                "clothing": [{"id": "school_uniform_jk", "scope": "girlA"}],
            }
        )


def test_compose_presets_rejects_unknown_ids_limits_conflicts_and_r18() -> None:
    with pytest.raises(preset_composer.ComposeError, match="不存在的体位"):
        preset_composer.compose_presets({"pose_id": "missing_pose"})
    with pytest.raises(preset_composer.ComposeError, match="超过上限"):
        preset_composer.compose_presets(
            {
                "clothing": [
                    {"id": "school_uniform_jk", "scope": "girlA"},
                    {"id": "sailor_uniform", "scope": "girlA"},
                    {"id": "maid_outfit", "scope": "girlA"},
                    {"id": "nurse_outfit", "scope": "girlA"},
                ]
            }
        )
    with pytest.raises(preset_composer.ComposeError, match="冲突"):
        preset_composer.compose_presets(
            {
                "body_modifications": [
                    {"id": "mod_chest_chain", "scope": "all"},
                    {"id": "mod_collarbone_bar", "scope": "all"},
                ]
            }
        )
    with pytest.raises(preset_composer.ComposeError, match="R18"):
        preset_composer.compose_presets(
            {"body_modifications": [{"id": "mod_chest_chain", "scope": "all"}]},
            restriction_enabled=True,
        )


def test_compose_presets_rejects_permanent_blocked_text(monkeypatch) -> None:
    import prompt_agent

    original_tags = prompt_agent.POSE_PRESETS[0]["tags"]
    monkeypatch.setitem(prompt_agent.POSE_PRESETS[0], "tags", ["bestiality", "animal sex"])
    with pytest.raises(preset_composer.ComposeError, match="永久禁止"):
        preset_composer.compose_presets({"pose_id": prompt_agent.POSE_PRESETS[0]["id"]})
    monkeypatch.setitem(prompt_agent.POSE_PRESETS[0], "tags", original_tags)


def test_composition_json_is_persisted_and_returned(client) -> None:
    composition = {
        "pose_id": "missionary",
        "scene_id": None,
        "clothing": [{"id": "school_uniform_jk", "scope": "girlA"}],
        "body_modifications": [],
    }
    response = client.post(
        "/api/prompt-sets",
        json={
            "name": "组合迁移测试",
            "type": "组合",
            "content": "school uniform, missionary",
            "translation": "学校制服、传教士体位",
            "composition_json": composition,
        },
    )
    assert response.status_code == 200
    item = response.json()["item"]
    assert item["type"] == "组合"
    assert json.loads(item["composition_json"]) == composition

    listed = client.get("/api/prompt-sets", params={"type": "组合"}).json()
    assert listed["total"] == 1
    assert json.loads(listed["items"][0]["composition_json"]) == composition


def test_real_world_public_scene_expansion_is_complete() -> None:
    by_id = {item["id"]: item for item in scene_presets.SCENE_PRESETS}
    ids = {
        "scene_airport_terminal_waiting_hall",
        "scene_commercial_airplane_cabin",
        "scene_city_bus_interior",
        "scene_ferry_deck_sea_view",
        "scene_shopping_mall_atrium",
        "scene_supermarket_aisle",
        "scene_modern_art_museum_gallery",
        "scene_planetarium_dome_hall",
        "scene_cinema_auditorium",
        "scene_modern_fitness_gym",
        "scene_small_livehouse_venue",
        "scene_christmas_market",
    }
    assert ids <= set(by_id)
    for preset_id in ids:
        item = by_id[preset_id]
        assert item["rating"] == "普通"
        assert item["has_image"] is False
        assert item["people_policy"] == "empty"
        assert item["empty_scene_prompt"]
        assert item["occupied_scene_prompt"]
        assert "empty" not in item["occupied_scene_prompt"].lower()
