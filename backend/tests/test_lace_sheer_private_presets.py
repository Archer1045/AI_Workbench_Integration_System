"""Lace, sheer, private, and open-structure clothing expansion contract."""
from __future__ import annotations

from collections import Counter

import clothing_presets
import lace_sheer_private_presets
import preset_taxonomy


def test_lace_sheer_private_expansion_is_complete() -> None:
    generated = lace_sheer_private_presets.build_presets(clothing_presets._p)
    generated_ids = [item["id"] for item in generated]
    catalog_by_id = {item["id"]: item for item in clothing_presets.CLOTHING_PRESETS}

    assert len(generated) == 98
    assert len(generated_ids) == len(set(generated_ids))
    assert set(generated_ids) <= set(catalog_by_id)
    assert all(catalog_by_id[preset_id]["has_image"] is False for preset_id in generated_ids)
    assert all(catalog_by_id[preset_id]["nsfw"] is True for preset_id in generated_ids)
    assert all(catalog_by_id[preset_id]["gender"] == "女" for preset_id in generated_ids)

    categories = Counter(item["category"] for item in generated)
    assert categories == {
        "情趣内衣": 25,
        "内衣/睡衣": 7,
        "泳装/运动": 4,
        "配饰": 6,
        "情趣礼服": 14,
        "情趣婚纱": 11,
        "情趣泳装": 12,
        "袜": 18,
        "日常服装": 1,
    }

    assert {
        "sheer_tulle_frame_bralette_set",
        "transparent_lace_contour_bodysuit",
        "lace_illusion_garter_teddy",
        "open_nipple_lace_halter",
        "open_lower_lace_skirt_set",
        "dual_open_lace_dress",
        "lace_top_sheer_pantyhose",
        "high_neck_lace_bodystocking",
        "open_back_lace_wedding_gown",
        "lace_corset_bikini_set",
    } <= set(generated_ids)


def test_lace_sheer_private_taxonomy_is_exposed() -> None:
    assert {
        "情趣礼服",
        "情趣婚纱",
        "情趣泳装",
        "袜",
    } <= set(clothing_presets.CATEGORIES)

    assert preset_taxonomy.CLOTHING_CATEGORY_MAP["情趣礼服"] == (
        "礼服主题",
        "情趣礼服",
    )
    assert preset_taxonomy.CLOTHING_CATEGORY_MAP["情趣婚纱"] == (
        "礼服主题",
        "情趣婚纱",
    )
    assert preset_taxonomy.CLOTHING_CATEGORY_MAP["情趣泳装"] == (
        "日常制服",
        "情趣泳装",
    )
    assert preset_taxonomy.CLOTHING_CATEGORY_MAP["袜"] == (
        "配饰鞋袜",
        "袜",
    )
