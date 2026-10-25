"""服装预设数据完整性与 API 过滤测试。"""
from __future__ import annotations

import clothing_presets
from clothing_presets import (
    CATEGORIES,
    CLOTHING_PRESETS,
    GENDERS,
    INTENSITIES,
    LAYER_STATES,
    MATERIALS,
    PARTS,
)


def test_clothing_preset_data_is_complete() -> None:
    assert len(CLOTHING_PRESETS) == 1013
    ids = [item["id"] for item in CLOTHING_PRESETS]
    assert len(ids) == len(set(ids))
    body_jewelry_ids = {item["id"] for item in clothing_presets.BODY_JEWELRY_PRESETS}
    assert len(body_jewelry_ids) == 80
    assert body_jewelry_ids <= set(ids)
    new_ids = {
        "british_academy_uniform",
        "florist_apron_outfit",
        "french_countryside_dress",
        "modern_chinese_banquet_dress",
        "velvet_ribbon_lingerie_set",
    }
    assert new_ids <= set(ids)
    support_ids = {
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
    assert support_ids <= set(ids)
    swimwear_ids = {
        "piercing_window_monokini",
        "detachable_ring_side_bikini",
        "double_slit_one_piece_swimsuit",
        "pearl_chain_open_back_swimsuit",
        "lace_panel_jewelry_swimsuit",
        "open_waist_jewelry_bikini",
        "high_neck_chest_window_swimsuit",
        "chain_side_string_bikini",
        "convertible_coverup_swimsuit",
        "asymmetric_high_slit_swimsuit",
        "velvet_touch_bikini",
        "pearl_shoulder_chain_bikini",
    }
    assert swimwear_ids <= set(ids)
    open_body_ids = {
        "open_bust_jeweled_frame_teddy",
        "open_lower_pearl_waist_bodysuit",
        "double_window_lace_teddy",
        "front_open_open_lower_slip",
        "detachable_cup_open_lower_set",
        "open_hip_lace_corset",
        "strappy_open_bust_babydoll",
        "jewel_chain_front_open_negligee",
        "open_cup_high_waist_swimsuit",
        "side_open_open_lower_bikini",
        "pearl_frame_open_front_monokini",
        "lace_window_open_cut_swimsuit",
        "satin_front_open_open_lower_gown",
        "lace_front_open_lounge_set",
        "ribbon_open_waist_robe",
        "pearl_chain_open_back_negligee",
        "jeweled_back_open_hip_gown",
        "sheer_open_bust_ball_gown",
        "moonlit_front_open_robe",
        "desert_jewel_open_bust_tunic",
    }
    assert open_body_ids <= set(ids)
    adult_pair_ids = {
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
    assert adult_pair_ids <= set(ids)
    gentle_pair_ids = {
        "oversized_shirt_soft_loungewear",
        "apron_soft_home_dress",
        "open_shoulder_cotton_nightgown",
        "bath_towel_wrap_set",
        "sheer_seaside_coverup",
        "soft_silk_lap_robe",
    }
    assert gentle_pair_ids <= set(ids)
    aggressive_pair_ids = {
        "mirror_command_open_corset",
        "forced_kneel_open_lower_lingerie",
        "hair_pull_toy_open_bodysuit",
        "piercing_tension_jewel_frame_corset",
        "intimate_bite_open_bust_set",
        "sibling_lap_open_nightgown",
        "maternal_floor_open_gown",
        "size_contrast_open_swimsuit",
        "multi_point_open_back_lingerie",
        "aftercare_open_wrap_robe",
    }
    assert aggressive_pair_ids <= set(ids)
    by_id = {item["id"]: item for item in CLOTHING_PRESETS}
    for preset_id in (
        new_ids
        | support_ids
        | swimwear_ids
        | open_body_ids
        | adult_pair_ids
        | gentle_pair_ids
        | aggressive_pair_ids
    ):
        assert by_id[preset_id]["has_image"] is False
    for preset_id in swimwear_ids:
        item = by_id[preset_id]
        assert item["category"] == "泳装/运动"
        assert item["nsfw"] is True
    for preset_id in body_jewelry_ids:
        item = by_id[preset_id]
        assert item["category"] == "配饰"
        assert item["part"] == "配饰"
        assert item["nsfw"] is True
        assert item["has_image"] is False
    assert sum(item["has_image"] for item in CLOTHING_PRESETS) == 336
    assert sum(item["category"] == "角色服装" for item in CLOTHING_PRESETS) == 290
    for item in CLOTHING_PRESETS:
        assert item["schema_version"] == 2
        assert item["category"] in CATEGORIES
        assert item["gender"] in GENDERS
        assert item["part"] in PARTS
        assert item["intensity"] in INTENSITIES
        assert item["layer_state"] in LAYER_STATES
        assert isinstance(item["materials"], list)
        assert all(material in MATERIALS for material in item["materials"])
        assert isinstance(item["color_slots"], list)
        assert all(slot in clothing_presets.COLOR_SLOTS for slot in item["color_slots"])
        assert isinstance(item["accessories"], list)
        assert isinstance(item["compatibility"], list)
        assert isinstance(item["has_image"], bool)
        tags = item["tags"]
        assert tags
        assert len(tags) == len(set(tags))
        assert isinstance(item["nsfw"], bool)
    textured_ribbed_swimsuit = by_id["textured_ribbed_swimsuit"]
    assert "monochrome" not in textured_ribbed_swimsuit["tags"]
    assert {
        "single-color swimsuit",
        "vivid color swimwear",
        "tonal fabric shading",
    } <= set(textured_ribbed_swimsuit["tags"])


def test_clothing_presets_api_returns_all_when_unrestricted(client) -> None:
    response = client.get("/api/prompt-agent/clothing-presets")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1013
    assert body["restricted"] is False
    assert any(item["nsfw"] for item in body["items"])
    assert {"rating", "tag_count", "materials", "layer_state", "color_slots"} <= set(body["items"][0])
    assert sum(1 for item in body["items"] if item["image"]) == 445
    assert all(bool(item["image"]) == item["has_image"] for item in body["items"])


def test_clothing_presets_api_hides_r18_when_restricted(client, monkeypatch) -> None:
    import routers.prompt as prompt_router

    monkeypatch.setattr(prompt_router, "content_restriction_enabled", lambda: True)
    response = client.get("/api/prompt-agent/clothing-presets")
    assert response.status_code == 200
    body = response.json()
    assert body["restricted"] is True
    assert body["items"]
    assert all(not item["nsfw"] for item in body["items"])


def test_clothing_presets_api_supports_filters(client) -> None:
    response = client.get(
        "/api/prompt-agent/clothing-presets",
        params={"rating": "R18", "category": "内衣/睡衣", "gender": "女"},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    assert all(item["nsfw"] and item["category"] == "内衣/睡衣" and item["gender"] == "女" for item in items)

    keyword_response = client.get("/api/prompt-agent/clothing-presets", params={"keyword": "校服"})
    assert keyword_response.status_code == 200
    assert any("校服" in item["label"] or "校服" in item["translation"] for item in keyword_response.json()["items"])

    lingerie_response = client.get(
        "/api/prompt-agent/clothing-presets",
        params={"rating": "R18", "category": "情趣内衣", "gender": "女"},
    )
    assert lingerie_response.status_code == 200
    lingerie_items = lingerie_response.json()["items"]
    assert len(lingerie_items) == 155
    assert all(
        item["nsfw"] and item["category"] == "情趣内衣" and item["gender"] == "女"
        for item in lingerie_items
    )

    material_response = client.get(
        "/api/prompt-agent/clothing-presets",
        params={"material": "乳胶", "layer_state": "完整", "intensity": "强化"},
    )
    assert material_response.status_code == 200
    assert material_response.json()["items"]
    assert all(
        "乳胶" in item["materials"]
        and item["layer_state"] == "完整"
        and item["intensity"] == "强化"
        for item in material_response.json()["items"]
    )


def test_standalone_shoes_are_in_the_footwear_category() -> None:
    by_id = {item["id"]: item for item in CLOTHING_PRESETS}
    assert "鞋" in CATEGORIES
    assert "鞋" in PARTS
    for preset_id in ("armored_high_boots", "leather_bondage_boots"):
        item = by_id[preset_id]
        assert item["category"] == "鞋"
        assert item["part"] == "鞋"
    shoe_items = [item for item in CLOTHING_PRESETS if item["category"] == "鞋"]
    assert len(shoe_items) == 18
    assert {item["part"] for item in shoe_items} == {"鞋"}
    assert all(item.get("footwear_type") for item in shoe_items if item["id"].startswith("shoe_"))
    # 整套服装里的鞋不拆分，仍留在原分类。
    assert by_id["latex_boots_dress_set"]["category"] != "鞋"


def test_new_legwear_and_footwear_presets_are_source_only() -> None:
    by_id = {item["id"]: item for item in CLOTHING_PRESETS}
    new_footwear = {
        "shoe_ivory_thigh_high_heel_boots": "thigh_high_boots",
        "shoe_burgundy_knee_high_boots": "knee_high_boots",
        "shoe_red_patent_stiletto_heels": "stiletto_heels",
        "shoe_white_pearl_strap_heels": "pumps",
    }
    new_legwear = {
        "legwear_white_sheer_pantyhose": "pantyhose",
        "legwear_charcoal_ribbed_pantyhose": "pantyhose",
        "legwear_diamond_lace_thighhighs": "thighhighs",
        "legwear_metallic_sheen_thighhighs": "thighhighs",
        "legwear_black_lace_suspender_stockings": "stockings",
        "legwear_white_satin_suspender_stockings": "stockings",
        "legwear_red_back_seam_suspender_stockings": "stockings",
        "legwear_gray_ribbed_suspender_stockings": "stockings",
        "legwear_navy_cross_strap_suspender_stockings": "stockings",
        "legwear_white_pearl_chain_suspender_stockings": "stockings",
    }
    assert all(by_id[preset_id]["has_image"] is False for preset_id in new_footwear)
    assert all(by_id[preset_id]["has_image"] is False for preset_id in new_legwear)
    assert {
        preset_id: by_id[preset_id]["footwear_type"]
        for preset_id in new_footwear
    } == new_footwear
    assert {
        preset_id: by_id[preset_id]["legwear_type"]
        for preset_id in new_legwear
    } == new_legwear


def test_black_wedding_and_bikini_presets_are_source_only() -> None:
    by_id = {item["id"]: item for item in CLOTHING_PRESETS}
    wedding_ids = {
        "black_lace_mermaid_wedding_gown",
        "black_satin_off_shoulder_wedding_gown",
        "black_gothic_cathedral_wedding_gown",
        "black_velvet_corset_wedding_gown",
    }
    bikini_ids = {
        "black_satin_triangle_bikini",
        "black_lace_halter_bikini",
        "black_strappy_high_cut_bikini",
        "black_glossy_bandeau_bikini",
    }
    assert all(by_id[preset_id]["has_image"] is False for preset_id in wedding_ids)
    assert all(by_id[preset_id]["has_image"] is False for preset_id in bikini_ids)
    assert {by_id[preset_id]["category"] for preset_id in wedding_ids} == {"礼服/正式"}
    assert {by_id[preset_id]["category"] for preset_id in bikini_ids} == {"泳装/运动"}
    assert {by_id[preset_id]["part"] for preset_id in bikini_ids} == {"泳装"}


def test_bridal_lingerie_presets_are_complete_source_only_entries() -> None:
    by_id = {item["id"]: item for item in CLOTHING_PRESETS}
    ids = {
        "black_satin_bridal_chemise",
        "ivory_pearl_bridal_bodysuit",
        "champagne_embroidery_bridal_set",
        "silver_lace_bridal_nightgown",
        "black_lace_bridal_garter_set",
        "blush_pink_bridal_satin_teddy",
    }
    assert ids <= set(by_id)
    assert {by_id[preset_id]["category"] for preset_id in ids} == {"情趣内衣"}
    assert {by_id[preset_id]["part"] for preset_id in ids} == {"内衣"}
    assert all(by_id[preset_id]["nsfw"] is True for preset_id in ids)
    assert all(by_id[preset_id]["has_image"] is False for preset_id in ids)


def test_new_fantasy_lingerie_costumes_are_source_only() -> None:
    by_id = {item["id"]: item for item in CLOTHING_PRESETS}
    ids = {
        "black_gold_gothic_corset_gown",
        "wine_velvet_backless_evening_gown",
        "violet_tulle_train_lingerie_gown",
        "silver_ring_corset_bodysuit",
        "midnight_blue_lace_high_slit_gown",
        "champagne_feather_bolero_lingerie_set",
    }
    assert ids <= set(by_id)
    assert all(by_id[preset_id]["nsfw"] is True for preset_id in ids)
    assert all(by_id[preset_id]["has_image"] is False for preset_id in ids)
    assert {
        by_id[preset_id]["category"] for preset_id in ids
    } == {"情趣礼服", "情趣内衣"}


def test_new_swimwear_and_underwear_presets_are_source_only() -> None:
    by_id = {item["id"]: item for item in CLOTHING_PRESETS}
    swimwear_ids = {
        "swim_emerald_ruched_bikini",
        "swim_pearl_white_high_neck_one_piece",
        "swim_coral_cutout_monokini",
        "swim_black_gold_chain_bikini",
        "swim_sky_blue_scalloped_bikini",
        "swim_rose_ribbed_one_piece",
    }
    underwear_ids = {
        "underwear_midnight_lace_bralette_set",
        "underwear_cream_satin_slip_set",
        "underwear_blush_rose_lace_teddy",
        "underwear_black_mesh_corset_set",
        "underwear_lavender_ribbon_babydoll",
        "underwear_pearl_ivory_camisole_set",
    }
    assert all(by_id[preset_id]["category"] == "泳装/运动" for preset_id in swimwear_ids)
    assert all(by_id[preset_id]["part"] == "泳装" for preset_id in swimwear_ids)
    assert all(by_id[preset_id]["category"] == "情趣内衣" for preset_id in underwear_ids)
    assert all(by_id[preset_id]["part"] == "内衣" for preset_id in underwear_ids)
    assert all(
        by_id[preset_id]["has_image"] is False
        for preset_id in swimwear_ids | underwear_ids
    )


def test_legwear_category_migration_and_expansion() -> None:
    by_id = {item["id"]: item for item in CLOTHING_PRESETS}
    assert "袜" in CATEGORIES
    assert "袜" in PARTS

    migrated = {
        "thighhigh_stockings",
        "opaque_black_pantyhose",
        "sheer_black_pantyhose",
        "white_lace_thighhigh_stockings",
        "standalone_fishnet_stockings",
        "stay_up_stockings",
        "cuban_heel_stockings",
        "back_seam_stockings",
        "ripped_stockings",
        "crotchless_pantyhose",
        "open_toe_bodystocking",
        "glossy_latex_stockings",
        "wet_look_stockings",
        "black_lace_cuff_thighhigh",
        "sheer_overknee_lace_socks",
        "ribbon_thighhigh_stockings",
        "scalloped_lace_thighhigh",
        "thigh_window_lace_stockings",
        "bridal_tulle_thighhigh",
        "lace_top_sheer_pantyhose",
        "scalloped_lace_pantyhose",
        "floral_lace_pantyhose",
        "double_layer_tulle_pantyhose",
        "ribbon_lace_pantyhose",
        "lace_waist_pantyhose",
        "distressed_lace_pantyhose",
        "crotchless_lace_pantyhose",
    }
    for preset_id in migrated:
        assert by_id[preset_id]["category"] == "袜"
        assert by_id[preset_id]["part"] == "袜"

    # 连身袜仍归袜类，但部位保持内衣，不拆内衣套装。
    for preset_id in (
        "high_neck_lace_bodystocking",
        "open_back_tulle_bodystocking",
        "corset_lace_bodystocking",
        "open_lower_lace_bodystocking",
    ):
        assert by_id[preset_id]["category"] == "袜"
        assert by_id[preset_id]["part"] == "内衣"

    new_legwear = {
        "legwear_gray_sheer_tights",
        "legwear_navy_opaque_tights",
        "legwear_vertical_striped_stockings",
        "legwear_slouch_socks",
        "legwear_leg_warmers",
        "legwear_footless_tights",
        "legwear_white_opaque_thighhighs",
        "legwear_navy_thighhighs",
        "legwear_gray_ribbed_thighhighs",
        "legwear_black_knit_thighhighs",
        "legwear_white_ribbon_thighhighs",
        "legwear_two_tone_thighhighs",
        "legwear_striped_thighhighs",
        "legwear_asymmetrical_thighhighs",
        "legwear_thighhighs_with_garter",
        "legwear_cable_knit_thighhighs",
        "legwear_white_opaque_pantyhose",
        "legwear_navy_sheer_pantyhose",
        "legwear_gray_opaque_pantyhose",
        "legwear_brown_sheer_pantyhose",
        "legwear_vertical_stripe_pantyhose",
        "legwear_polka_dot_pantyhose",
        "legwear_velvet_pantyhose",
        "legwear_seamless_pantyhose",
        "legwear_glossy_pantyhose",
        "legwear_gradient_pantyhose",
        "legwear_white_sheer_pantyhose",
        "legwear_charcoal_ribbed_pantyhose",
        "legwear_diamond_lace_thighhighs",
        "legwear_metallic_sheen_thighhighs",
        "legwear_black_lace_suspender_stockings",
        "legwear_white_satin_suspender_stockings",
        "legwear_red_back_seam_suspender_stockings",
        "legwear_gray_ribbed_suspender_stockings",
        "legwear_navy_cross_strap_suspender_stockings",
        "legwear_white_pearl_chain_suspender_stockings",
    }
    assert new_legwear <= set(by_id)
    assert all(by_id[preset_id].get("legwear_type") for preset_id in new_legwear)
    assert "legwear_white_opaque_tights" not in by_id
    assert "legwear_velvet_tights" not in by_id

    legwear_items = [item for item in CLOTHING_PRESETS if item["category"] == "袜"]
    assert len(legwear_items) == 67
    assert sum(item["part"] == "袜" for item in legwear_items) == 63
    assert sum(item["part"] == "内衣" for item in legwear_items) == 4
