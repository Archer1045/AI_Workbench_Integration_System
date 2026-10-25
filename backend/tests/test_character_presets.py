"""Built-in character identity presets and their default outfits."""
from __future__ import annotations

from pathlib import Path

import character_presets
import character_prompt_presets
import character_prompt_presets_fgo
import character_prompt_presets_genshin
import character_preset_separation
import clothing_presets


REQUIRED_CHARACTER_IDS = {
    "builtin_character_arknights_skadi_the_corrupting_heart",
    "builtin_character_arknights_theresa",
    "builtin_character_wuthering_waves_chisa",
    "builtin_character_wuthering_waves_lynae",
    "builtin_character_zenless_zone_zero_ye_shunguang",
    "builtin_character_zenless_zone_zero_remielle",
    "builtin_character_honkai_impact_3rd_vita",
    "builtin_character_honkai_impact_3rd_big_luna",
    "builtin_character_girls_frontline_2_tololo",
    "builtin_character_girls_frontline_2_groza",
    "builtin_character_girls_frontline_2_ots_14",
    "builtin_character_girls_frontline_2_yoohee",
}
GIRLS_FRONTLINE_2_CHARACTER_IDS = {
    "builtin_character_girls_frontline_2_tololo",
    "builtin_character_girls_frontline_2_sabrina",
    "builtin_character_girls_frontline_2_groza",
    "builtin_character_girls_frontline_2_nagant",
    "builtin_character_girls_frontline_2_daiyan",
    "builtin_character_girls_frontline_2_centaureissi",
    "builtin_character_girls_frontline_2_jiangyu",
    "builtin_character_girls_frontline_2_macchiato",
    "builtin_character_girls_frontline_2_suomi",
    "builtin_character_girls_frontline_2_springfield",
    "builtin_character_girls_frontline_2_qiuhua",
    "builtin_character_girls_frontline_2_nikketa",
    "builtin_character_girls_frontline_2_leva",
    "builtin_character_girls_frontline_2_lenna",
    "builtin_character_girls_frontline_2_klukai",
    "builtin_character_girls_frontline_2_soppo",
    "builtin_character_girls_frontline_2_ots_14",
    "builtin_character_girls_frontline_2_sextans",
    "builtin_character_girls_frontline_2_liushi",
    "builtin_character_girls_frontline_2_egretha",
    "builtin_character_girls_frontline_2_asteria",
    "builtin_character_girls_frontline_2_clarda",
    "builtin_character_girls_frontline_2_fuling",
    "builtin_character_girls_frontline_2_welrod",
    "builtin_character_girls_frontline_2_seria",
    "builtin_character_girls_frontline_2_lorelei",
    "builtin_character_girls_frontline_2_lewis",
    "builtin_character_girls_frontline_2_eve",
    "builtin_character_girls_frontline_2_robella",
    "builtin_character_girls_frontline_2_vector",
    "builtin_character_girls_frontline_2_yoohee",
}
CHARACTER_EXPANSION_IDS = {
    "builtin_character_azur_lane_laffey",
    "builtin_character_azur_lane_unicorn",
    "builtin_character_azur_lane_javelin",
    "builtin_character_azur_lane_ayanami",
    "builtin_character_azur_lane_z23",
    "builtin_character_azur_lane_bismarck",
    "builtin_character_azur_lane_tirpitz",
    "builtin_character_azur_lane_richelieu",
    "builtin_character_azur_lane_jean_bart",
    "builtin_character_azur_lane_st_louis",
    "builtin_character_arknights_nightingale",
    "builtin_character_arknights_shining",
    "builtin_character_arknights_saria",
    "builtin_character_arknights_hoshiguma",
    "builtin_character_arknights_schwarz",
    "builtin_character_arknights_mostima",
    "builtin_character_arknights_bagpipe",
    "builtin_character_arknights_rosmontis",
    "builtin_character_arknights_dusk",
    "builtin_character_arknights_specter",
    "builtin_character_hsr_himeko",
    "builtin_character_hsr_herta",
    "builtin_character_hsr_tingyun",
    "builtin_character_hsr_qingque",
    "builtin_character_hsr_sushang",
    "builtin_character_hsr_yukong",
    "builtin_character_hsr_huohuo",
    "builtin_character_hsr_hanya",
    "builtin_character_hsr_feixiao",
    "builtin_character_hsr_yunli",
    "builtin_character_wuthering_waves_yangyang",
    "builtin_character_wuthering_waves_baizhi",
    "builtin_character_wuthering_waves_danjin",
    "builtin_character_wuthering_waves_sanhua",
    "builtin_character_wuthering_waves_jianxin",
    "builtin_character_wuthering_waves_verina",
    "builtin_character_wuthering_waves_encore",
    "builtin_character_wuthering_waves_youhu",
    "builtin_character_wuthering_waves_lumi",
    "builtin_character_wuthering_waves_zhezhi",
    "builtin_character_wuthering_waves_aemeath",
    "builtin_character_honkai_impact_3rd_kallen_kaslana",
    "builtin_character_honkai_impact_3rd_aponia",
    "builtin_character_honkai_impact_3rd_mobius",
    "builtin_character_honkai_impact_3rd_pardofelis",
    "builtin_character_honkai_impact_3rd_vill_v",
    "builtin_character_honkai_impact_3rd_eden",
    "builtin_character_honkai_impact_3rd_griseo",
    "builtin_character_honkai_impact_3rd_rozaliya",
    "builtin_character_honkai_impact_3rd_liliya",
    "builtin_character_honkai_impact_3rd_shigure_kira",
}
ALL_CHARACTER_IDS = {
    item["preset_id"] for item in character_presets.BUILTIN_CHARACTER_PRESETS
}
CHARACTER_PROMPT_NEW_IDS = {
    "builtin_character_hsr_the_herta",
    "builtin_character_hsr_the_dahlia",
    "builtin_character_hsr_fugue",
    "builtin_character_hsr_cyrene",
    "builtin_character_hsr_castorice",
    "builtin_character_hsr_yao_guang",
    "builtin_character_hsr_hysilens",
    "builtin_character_hsr_evernight",
    "builtin_character_hsr_stelle",
    "builtin_character_hsr_bronya",
    "builtin_character_azur_lane_essex",
    "builtin_character_azur_lane_lion",
    "builtin_character_azur_lane_i_404",
    "builtin_character_azur_lane_z52",
    "builtin_character_azur_lane_gouden_leeuw",
    "builtin_character_azur_lane_chang_wu",
    "builtin_character_azur_lane_aquila",
    "builtin_character_azur_lane_impero",
    "builtin_character_azur_lane_implacable",
    "builtin_character_azur_lane_drake",
    "builtin_character_azur_lane_plymouth",
    "builtin_character_azur_lane_hakuhou",
    "builtin_character_azur_lane_azuma",
    "builtin_character_azur_lane_ulrich_von_hutten",
    "builtin_character_azur_lane_gotz_von_berlichingen",
    "builtin_character_azur_lane_u_2501",
    "builtin_character_azur_lane_agir",
    "builtin_character_azur_lane_hindenburg",
    "builtin_character_azur_lane_mecklenburg",
    "builtin_character_azur_lane_napoli",
    "builtin_character_azur_lane_alsace",
    "builtin_character_azur_lane_brest",
    "builtin_character_azur_lane_mogador",
    "builtin_character_azur_lane_helena",
    "builtin_character_azur_lane_sirius",
    "builtin_character_azur_lane_scylla",
    "builtin_character_azur_lane_howe",
    "builtin_character_azur_lane_perseus",
    "builtin_character_azur_lane_albion",
    "builtin_character_azur_lane_illustrious",
    "builtin_character_azur_lane_monarch",
    "builtin_character_azur_lane_cheshire",
    "builtin_character_azur_lane_hatsuzuki",
    "builtin_character_azur_lane_sakawa",
    "builtin_character_azur_lane_asama",
    "builtin_character_azur_lane_oumi",
    "builtin_character_azur_lane_ibuki",
    "builtin_character_azur_lane_emden",
    "builtin_character_azur_lane_duisburg",
    "builtin_character_azur_lane_august_von_parseval",
    "builtin_character_azur_lane_ying_swei",
    "builtin_character_azur_lane_chao_ho",
    "builtin_character_azur_lane_jian_wu",
    "builtin_character_azur_lane_zhen_hai",
    "builtin_character_azur_lane_maggiore_baracca",
    "builtin_character_azur_lane_argus",
    "builtin_character_azur_lane_elbe",
    "builtin_character_azur_lane_hai_tien",
    "builtin_character_azur_lane_suffren",
    "builtin_character_azur_lane_dunkerque",
    "builtin_character_azur_lane_elbing",
    "builtin_character_arknights_shu",
    "builtin_character_arknights_pozyomka",
    "builtin_character_arknights_typhon",
    "builtin_character_arknights_virtuosa",
    "builtin_character_arknights_haruka",
    "builtin_character_arknights_angelina_the_mellow_wish",
    "builtin_character_arknights_vulpisfoglia",
    "builtin_character_arknights_cantabile",
    "builtin_character_arknights_la_pluma",
    "builtin_character_arknights_whisperain",
    "builtin_character_arknights_indigo",
    "builtin_character_arknights_manticore",
    "builtin_character_wuthering_waves_dania",
    "builtin_character_wuthering_waves_iuno",
    "builtin_character_wuthering_waves_lupa",
    "builtin_character_wuthering_waves_female_rover",
}
CHARACTER_EXPANSION_IDS |= CHARACTER_PROMPT_NEW_IDS
CHARACTER_PROMPT_BATCH_IDS = {
    item["preset_id"] for item in character_prompt_presets.CHARACTER_PROMPT_PRESETS
}


def test_builtin_character_presets_are_complete_and_unique() -> None:
    items = character_presets.BUILTIN_CHARACTER_PRESETS
    assert len(items) == 290
    assert {item["preset_id"] for item in items} == set(
        character_presets.CHARACTER_PRESETS_BY_ID
    )
    assert REQUIRED_CHARACTER_IDS <= set(character_presets.CHARACTER_PRESETS_BY_ID)

    for item in items:
        assert item["category"] == "角色"
        assert item["name"]
        assert item["work"] in {
            "碧蓝航线",
            "明日方舟",
            "崩坏：星穹铁道",
            "鸣潮",
            "绝区零",
            "崩坏3",
            "少女前线2",
            "Fate/Grand Order",
            "原神",
        }
        assert item["appearance_tags"]
        assert item["outfit_id"]
        assert item["outfit_name"]
        assert item["outfit_translation"]
        assert item["outfit_tags"]
        assert len(item["appearance_tags"]) == len(set(item["appearance_tags"]))
        assert len(item["outfit_tags"]) == len(set(item["outfit_tags"]))
    assert (
        character_presets.CHARACTER_PRESETS_BY_ID[
            "builtin_character_honkai_impact_3rd_big_luna"
        ]["name"]
        == "月下誓约-予爱以心"
    )
    bronya = character_presets.CHARACTER_PRESETS_BY_ID["builtin_character_hsr_bronya"]
    assert bronya["work"] == "崩坏：星穹铁道"
    assert bronya["appearance_tags"][0] == "bronya_(honkai:_star_rail)"
    ulrich = character_presets.CHARACTER_PRESETS_BY_ID["builtin_character_azur_lane_ulrich_von_hutten"]
    assert ulrich["outfit_id"] == "outfit_azur_lane_ulrich_von_hutten_racing_skin"
    assert ulrich["appearance_tags"][0] == "ulrich_von_hutten_(azur_lane)"
    assert len(GIRLS_FRONTLINE_2_CHARACTER_IDS) == 31
    assert len(CHARACTER_EXPANSION_IDS) == 128
    assert CHARACTER_EXPANSION_IDS <= set(character_presets.CHARACTER_PRESETS_BY_ID)
    assert len(CHARACTER_PROMPT_BATCH_IDS) == 83
    assert CHARACTER_PROMPT_BATCH_IDS <= ALL_CHARACTER_IDS
    assert len(character_prompt_presets_fgo.CHARACTER_PRESETS) == 37
    assert {
        item["preset_id"] for item in character_prompt_presets_fgo.CHARACTER_PRESETS
    } <= ALL_CHARACTER_IDS
    fgo = [
        item for item in items if item["work"] == "Fate/Grand Order"
    ]
    assert len(fgo) == 37
    assert len({item["outfit_id"] for item in fgo}) == 37
    assert len(character_prompt_presets_genshin.CHARACTER_PRESETS) == 26
    assert {
        item["preset_id"]
        for item in character_prompt_presets_genshin.CHARACTER_PRESETS
    } <= ALL_CHARACTER_IDS
    genshin = [item for item in items if item["work"] == "原神"]
    assert len(genshin) == 26
    assert len({item["outfit_id"] for item in genshin}) == 26
    sirius = character_presets.CHARACTER_PRESETS_BY_ID["builtin_character_azur_lane_sirius"]
    assert sirius["appearance_tags"][0] == "sirius_(azur_lane)"
    assert sirius["outfit_id"] == "outfit_azur_lane_sirius_default"
    sakawa = character_presets.CHARACTER_PRESETS_BY_ID["builtin_character_azur_lane_sakawa"]
    assert sakawa["appearance_tags"][0] == "sakawa_(azur_lane)"
    assert sakawa["outfit_id"] == "outfit_azur_lane_sakawa_default"
    asama = character_presets.CHARACTER_PRESETS_BY_ID["builtin_character_azur_lane_asama"]
    assert asama["appearance_tags"][0] == "asama_(azur_lane)"
    assert asama["outfit_id"] == "outfit_azur_lane_asama_default"
    zhen_hai = character_presets.CHARACTER_PRESETS_BY_ID["builtin_character_azur_lane_zhen_hai"]
    assert zhen_hai["appearance_tags"][0] == "zhen_hai_(azur_lane)"
    assert zhen_hai["outfit_id"] == "outfit_azur_lane_zhen_hai_default"
    maggiore = character_presets.CHARACTER_PRESETS_BY_ID["builtin_character_azur_lane_maggiore_baracca"]
    assert maggiore["appearance_tags"][0] == "maggiore_baracca_(azur_lane)"
    assert maggiore["outfit_id"] == "outfit_azur_lane_maggiore_baracca_default"
    pozyomka = character_presets.CHARACTER_PRESETS_BY_ID["builtin_character_arknights_pozyomka"]
    assert pozyomka["appearance_tags"][0] == "pozyomka_(arknights)"
    assert pozyomka["outfit_id"] == "outfit_arknights_pozyomka_default"
    assert {
        item["preset_id"]
        for item in items
        if item["work"] == "少女前线2"
    } == GIRLS_FRONTLINE_2_CHARACTER_IDS


def test_character_default_outfits_are_registered_without_fake_images() -> None:
    by_id = {item["id"]: item for item in clothing_presets.CLOTHING_PRESETS}
    character_outfits = [
        item for item in clothing_presets.CLOTHING_PRESETS
        if item["category"] == "角色服装"
    ]
    assert len(character_outfits) == 290
    assert (
        by_id["outfit_honkai_impact_3rd_big_luna_default"]["label"]
        == "月下誓约-予爱以心 默认服装"
    )

    for character in character_presets.BUILTIN_CHARACTER_PRESETS:
        outfit = by_id[character["outfit_id"]]
        assert outfit["category"] == "角色服装"
        assert outfit["label"] == character["outfit_name"]
        assert outfit["translation"] == character["outfit_translation"]
        assert outfit["tags"] == character["outfit_tags"]
        assert outfit["has_image"] is False


def test_fgo_character_presets_have_stage_specific_previews() -> None:
    public_dir = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "public"
        / "character-appearance-presets"
    )
    fgo = [
        item
        for item in character_presets.BUILTIN_CHARACTER_PRESETS
        if item["work"] == "Fate/Grand Order"
    ]
    assert len(fgo) == 37
    assert all(
        (public_dir / f"{item['preset_id']}.webp").is_file()
        for item in fgo
    )
    typhon = [
        item for item in fgo if item["name"].startswith("堤丰·厄斐墨洛斯")
    ]
    assert len(typhon) == 3
    assert "一破（A1）" in typhon[0]["name"]
    assert "二破（A2）" in typhon[1]["name"]
    assert "三破（A3）" in typhon[2]["name"]
    lady_avalon = character_presets.CHARACTER_PRESETS_BY_ID[
        "builtin_character_fgo_2800300_pretender_a1"
    ]
    assert "一破（A1）" in lady_avalon["name"]
    lady_avalon_a2 = character_presets.CHARACTER_PRESETS_BY_ID[
        "builtin_character_fgo_2800300_pretender_a2"
    ]
    assert "二破（A2）" in lady_avalon_a2["name"]
    for preset_id in (
        "builtin_character_fgo_701300_berserker_a3",
        "builtin_character_fgo_302500_lancer_a3",
    ):
        assert "三破（A3）" in character_presets.CHARACTER_PRESETS_BY_ID[
            preset_id
        ]["name"]
    assert "builtin_character_fgo_2800300_pretender_a4" not in (
        character_presets.CHARACTER_PRESETS_BY_ID
    )


def test_genshin_character_presets_have_default_outfit_previews() -> None:
    public_dir = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "public"
        / "character-appearance-presets"
    )
    genshin = [
        item
        for item in character_presets.BUILTIN_CHARACTER_PRESETS
        if item["work"] == "原神"
    ]
    assert len(genshin) == 26
    assert all(
        (public_dir / f"{item['preset_id']}.webp").is_file()
        for item in genshin
    )
    assert "builtin_character_genshin_lumine" in character_presets.CHARACTER_PRESETS_BY_ID
    assert "builtin_character_genshin_columbina" in character_presets.CHARACTER_PRESETS_BY_ID
    columbina = character_presets.CHARACTER_PRESETS_BY_ID[
        "builtin_character_genshin_columbina"
    ]
    assert "dark purple hair" in columbina["appearance_tags"]
    assert "pink hair" not in columbina["appearance_tags"]


def test_all_builtin_identity_tags_are_separate_from_outfits() -> None:
    for item in character_presets.BUILTIN_CHARACTER_PRESETS:
        appearance_keys = {tag.lower() for tag in item["appearance_tags"]}
        outfit_keys = {tag.lower() for tag in item["outfit_tags"]}
        assert not appearance_keys & outfit_keys
        assert all(
            not character_preset_separation._is_attire(tag)
            for tag in item["appearance_tags"]
        )
        assert item["appearance_tags"][0] not in item["outfit_tags"]
        assert item["work"] not in item["outfit_tags"]
        assert "official_default_outfit" not in item["outfit_tags"]
        assert item["outfit_id"]


def test_character_presets_are_queryable_and_apply_without_clothing(client) -> None:
    response = client.get(
        "/api/prompt-agent/appearance-presets",
        params={"category": "角色", "source": "builtin"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 290
    assert all(item["source"] == "builtin" for item in body["items"])
    assert ALL_CHARACTER_IDS == {item["preset_id"] for item in body["items"]}
    assert REQUIRED_CHARACTER_IDS <= ALL_CHARACTER_IDS

    preset_id = "builtin_character_arknights_theresa"
    detail = client.get(f"/api/prompt-agent/appearance-presets/{preset_id}")
    assert detail.status_code == 200
    assert detail.json()["item"]["name"] == "特蕾西娅"

    applied = client.post(
        f"/api/prompt-agent/appearance-presets/{preset_id}/apply",
        json={},
    )
    assert applied.status_code == 200
    payload = applied.json()
    assert payload["appearance"]
    assert payload["clothing"] == []
    assert payload["expression"] == []

    columbina = client.get(
        "/api/prompt-agent/appearance-presets/builtin_character_genshin_columbina"
    ).json()["item"]
    assert columbina["outfit_id"] == "outfit_genshin_columbina_default"
    assert columbina["outfit_name"] == "哥伦比娅 默认服装"
    assert columbina["appearance_tags"] == [
        "columbina_(genshin_impact)",
        "genshin_impact",
        "1girl",
        "solo",
        "dark purple hair",
        "red eyes",
    ]
    assert columbina["clothing_tags"] == []
    applied_columbina = client.post(
        "/api/prompt-agent/appearance-presets/builtin_character_genshin_columbina/apply",
        json={},
    ).json()
    assert applied_columbina["clothing"] == []
    assert applied_columbina["default_outfit_id"] == "outfit_genshin_columbina_default"
    assert applied_columbina["default_outfit_name"] == "哥伦比娅 默认服装"


def test_character_default_outfits_are_listed_without_images(client) -> None:
    response = client.get(
        "/api/prompt-agent/clothing-presets",
        params={"category": "角色服装"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 290
    assert all(item["category"] == "角色服装" for item in body["items"])
    assert all(item["has_image"] is False for item in body["items"])
    assert all(item["image"] is None for item in body["items"])
