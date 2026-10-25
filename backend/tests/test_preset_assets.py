"""Preset thumbnail workshop storage, pipeline, and API safety tests."""
from __future__ import annotations

import base64
import io
import json
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

import comfy_worker
import config
import database
import preset_asset_pipeline as pipeline
import preset_asset_service as service
import preset_registry
import task_registry
from routers import preset_assets as preset_assets_router


EXPECTED_PRESET_ASSET_TARGETS = {
    "pose": {
        "generation_size": (832, 1216),
        "output_size": (512, 768),
        "format": "PNG",
        "quality": 95,
    },
    "clothing": {
        "generation_size": (540, 960),
        "output_size": (270, 480),
        "format": "WEBP",
        "quality": 90,
    },
    "scene": {
        "generation_size": (1024, 576),
        "output_size": (480, 270),
        "format": "WEBP",
        "quality": 90,
    },
    "body": {
        "generation_size": (540, 960),
        "output_size": (270, 480),
        "format": "WEBP",
        "quality": 90,
    },
    "character": {
        "generation_size": (540, 960),
        "output_size": (270, 480),
        "format": "WEBP",
        "quality": 90,
    },
}


def test_preset_asset_target_contract_matches_registry():
    registry_kinds = {definition.kind for definition in preset_registry.PRESET_KINDS}
    assert set(config.PRESET_ASSET_TARGETS) == registry_kinds
    assert config.PRESET_ASSET_TARGETS == EXPECTED_PRESET_ASSET_TARGETS

    serialized_targets = config.runtime_config()["preset_assets"]["targets"]
    assert set(serialized_targets) == registry_kinds
    for kind, target in EXPECTED_PRESET_ASSET_TARGETS.items():
        assert serialized_targets[kind] == {
            "generation_size": list(target["generation_size"]),
            "output_size": list(target["output_size"]),
            "format": target["format"],
            "quality": target["quality"],
        }


def _preset(kind: str, *, restricted: bool | None = None) -> dict:
    for item in preset_registry.PRESET_KIND_BY_KEY[kind].list_loader():
        is_restricted = service.preset_is_restricted(item)
        if restricted is None or is_restricted == restricted:
            return item
    pytest.skip(f"no {kind} preset satisfies restricted={restricted}")


def _image_bytes(
    image_format: str = "PNG",
    size: tuple[int, int] = (96, 144),
    *,
    orientation: int | None = None,
) -> bytes:
    image = Image.new("RGB", size, (96, 140, 180))
    buffer = io.BytesIO()
    options: dict = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[274] = orientation
        options["exif"] = exif
    image.save(buffer, format=image_format, **options)
    return buffer.getvalue()


def _data_url(data: bytes, mime_type: str = "image/png") -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _wait_until(predicate, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition was not met before timeout")


@pytest.fixture()
def workshop(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    managed_root = tmp_path / "managed"
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "workshop.db")
    monkeypatch.setattr(config, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(config, "PRESET_ASSET_ROOT", managed_root)
    monkeypatch.setattr(pipeline, "_AI_ACTIVE", False)
    monkeypatch.setattr(pipeline, "_GPU_CONDITION", threading.Condition())
    monkeypatch.setattr(pipeline, "_JOB_THREADS", {})
    monkeypatch.setattr(pipeline, "_JOB_THREADS_LOCK", threading.RLock())
    database.init_db()
    return project_root, managed_root


def test_migration_5_creates_workshop_tables(workshop):
    tables = {
        row["name"]
        for row in database.get_connection()
        .execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        .fetchall()
    }
    assert {
        "preset_asset_settings",
        "preset_asset_sources",
        "preset_asset_candidates",
        "preset_asset_versions",
        "preset_asset_job_items",
        "preset_asset_audit",
    } <= tables
    version = database.get_connection().execute("PRAGMA user_version").fetchone()[0]
    assert version == database.SCHEMA_VERSION
    assert version >= 5


def test_input_validation_rejects_traversal_forged_mime_and_limits(
    workshop, monkeypatch
):
    with pytest.raises(service.PresetAssetError) as unknown:
        service.resolve_preset("unknown", "x")
    assert unknown.value.status_code == 400

    with pytest.raises(service.PresetAssetError) as traversal:
        service.resolve_preset("pose", "../escape")
    assert traversal.value.status_code == 400

    with pytest.raises(service.PresetAssetError) as forged:
        service.validate_image_bytes(_image_bytes(), mime_type="image/jpeg")
    assert forged.value.status_code == 415

    with pytest.raises(service.PresetAssetError) as fake:
        service.validate_image_bytes(b"not-an-image")
    assert fake.value.status_code == 415

    monkeypatch.setattr(config, "PRESET_ASSET_UPLOAD_MAX_BYTES", 4)
    with pytest.raises(service.PresetAssetError) as too_large:
        service.validate_image_bytes(_image_bytes())
    assert too_large.value.status_code == 413

    monkeypatch.setattr(config, "PRESET_ASSET_UPLOAD_MAX_BYTES", 20 * 1024 * 1024)
    monkeypatch.setattr(config, "PRESET_ASSET_UPLOAD_MAX_PIXELS", 10)
    with pytest.raises(service.PresetAssetError) as too_many_pixels:
        service.validate_image_bytes(_image_bytes())
    assert too_many_pixels.value.status_code == 413

    outside = Path(workshop[1]).parent / "outside.png"
    with pytest.raises(service.PresetAssetError):
        service._ensure_under(outside, Path(config.PRESET_ASSET_ROOT))


def test_exif_orientation_is_applied_during_crop(workshop):
    preset = _preset("pose", restricted=False)
    source_data = _image_bytes("JPEG", (80, 40), orientation=6)
    source = service.import_source(
        "pose",
        str(preset["id"]),
        source_data,
        mime_type="image/jpeg",
    )
    candidate = service.create_crop_candidate(
        "pose",
        str(preset["id"]),
        source_id=int(source["id"]),
        crop={"mode": "contain", "focus_x": 0.5, "focus_y": 0.5},
    )
    assert candidate["status"] == "ready"
    assert (candidate["output_width"], candidate["output_height"]) == (512, 768)
    path = service.candidate_file(int(candidate["id"]))
    with Image.open(path) as image:
        assert image.size == (512, 768)


def test_prompt_snapshot_layers_and_seed_strategies(workshop, monkeypatch):
    preset = _preset("pose", restricted=False)
    snapshot = pipeline.build_prompt_snapshot(
        "pose",
        str(preset["id"]),
        {
            "style_positive": "style layer",
            "style_negative": "style negative",
            "user_positive": "user layer",
            "user_negative": "user negative",
            "seed_strategy": "fixed",
            "seed": 123,
            "candidate_count": 2,
            "model": "mock.safetensors",
        },
    )
    positive = snapshot["prompt_positive"]
    negative = snapshot["prompt_negative"]
    assert positive.index("style layer") < positive.index(str(preset["tags"][0]))
    assert positive.index(str(preset["tags"][0])) < positive.index("clear pose reference")
    assert positive.index("clear pose reference") < positive.index("user layer")
    assert negative.index("style negative") < negative.index("text, watermark")
    assert negative.index("text, watermark") < negative.index("extra characters")
    assert negative.index("extra characters") < negative.index("user negative")
    assert snapshot["template_version"] == config.PRESET_ASSET_TEMPLATE_VERSION
    assert snapshot["prompt_layers"]["preset_draw_prompt"] == preset.get("draw_prompt", "")
    assert pipeline._seed_for(snapshot, 0) == 123
    assert pipeline._seed_for(snapshot, 1) == 124

    snapshot["settings"]["seed_strategy"] = "derive"
    snapshot["settings"]["seed"] = 200
    assert pipeline._seed_for(snapshot, 2) == 202

    snapshot["settings"]["seed_strategy"] = "random"
    monkeypatch.setattr(
        pipeline.random.SystemRandom,
        "randrange",
        lambda _self, _start, _end: 4321,
    )
    assert pipeline._seed_for(snapshot, 0) == 4321


def test_workshop_default_style_is_decoupled_from_draw_default(workshop):
    legacy_defaults = {
        **config.PRESET_ASSET_DEFAULT_SETTINGS,
        "style_positive": config.DRAW_DEFAULT_PROMPT,
    }
    database.set_preset_asset_setting("defaults", legacy_defaults)

    migrated = service.settings_payload()["defaults"]
    assert migrated["style_positive"] == config.PRESET_ASSET_DEFAULT_STYLE_POSITIVE
    assert "school uniform" not in migrated["style_positive"]
    assert "sailor collar" not in migrated["style_positive"]
    assert "white shirt" not in migrated["style_positive"]
    assert "pleated skirt" not in migrated["style_positive"]
    stored = database.get_preset_asset_setting("defaults")
    assert stored["style_positive"] == config.PRESET_ASSET_DEFAULT_STYLE_POSITIVE
    audit = (
        database.get_connection()
        .execute(
            "SELECT COUNT(*) FROM preset_asset_audit WHERE event = ?",
            ("settings_migrated",),
        )
        .fetchone()[0]
    )
    assert audit == 1

    custom_defaults = {
        **legacy_defaults,
        "style_positive": "custom workshop style, no sailor collar",
    }
    database.set_preset_asset_setting("defaults", custom_defaults)
    custom = service.settings_payload()["defaults"]
    assert custom["style_positive"] == "custom workshop style, no sailor collar"
    assert database.get_preset_asset_setting("defaults")["style_positive"] == (
        "custom workshop style, no sailor collar"
    )


def test_workshop_settings_expose_limits_and_sanitize_lora_strengths(workshop):
    payload = service.settings_payload()
    limits = payload["limits"]
    assert limits["steps_min"] == config.DRAW_STEPS_MIN
    assert limits["steps_max"] == config.DRAW_STEPS_MAX
    assert limits["cfg_min"] == config.DRAW_CFG_MIN
    assert limits["cfg_max"] == config.DRAW_CFG_MAX
    assert limits["seed_min"] == config.DRAW_SEED_MIN
    assert limits["seed_max"] == config.DRAW_SEED_MAX
    assert limits["lora_strength_min"] == config.DRAW_LORA_STRENGTH_MIN
    assert limits["lora_strength_max"] == config.DRAW_LORA_STRENGTH_MAX

    cleaned = service.normalize_settings(
        {
            **config.PRESET_ASSET_DEFAULT_SETTINGS,
            "loras": ["style-a.safetensors", "style-a.safetensors", " "],
            "lora_strengths": {
                "style-a.safetensors": {
                    "model": config.DRAW_LORA_STRENGTH_MAX + 1,
                    "clip": config.DRAW_LORA_STRENGTH_MIN - 1,
                    "ignored": 0.5,
                },
                "invalid": "0.5",
                "": {"model": 0.5},
            },
        }
    )
    assert cleaned["loras"] == ["style-a.safetensors"]
    assert cleaned["lora_strengths"] == {
        "style-a.safetensors": {
            "model": config.DRAW_LORA_STRENGTH_MAX,
            "clip": config.DRAW_LORA_STRENGTH_MIN,
        }
    }


def test_clothing_thumbnail_uses_neutral_workshop_style(workshop):
    preset = _preset("clothing", restricted=False)
    snapshot = pipeline.build_prompt_snapshot(
        "clothing",
        str(preset["id"]),
        {"model": "mock.safetensors"},
    )
    style = snapshot["prompt_layers"]["style_positive"]
    assert style == config.PRESET_ASSET_DEFAULT_STYLE_POSITIVE
    assert "school uniform" not in style
    assert "sailor collar" not in style
    assert "target outfit replaces any base outfit" in snapshot["prompt_layers"][
        "type_positive"
    ]


def test_person_thumbnail_templates_keep_head_and_face_visible(workshop):
    for preset_type in ("pose", "clothing", "body", "character"):
        preset = _preset(preset_type, restricted=False)
        snapshot = pipeline.build_prompt_snapshot(
            preset_type,
            str(preset["id"]),
            {"model": "mock.safetensors"},
        )
        layers = snapshot["prompt_layers"]
        for value in (
            "zoomed out full-body shot",
            "complete head and both feet visible",
            "generous headroom above the head",
            "face fully inside frame",
            "both eyes and facial features visible and unobstructed",
        ):
            assert value in layers["type_positive"], (preset_type, value)
        for value in (
            "close-up framing",
            "upper-body crop",
            "waist-up shot",
            "cropped legs",
            "feet out of frame",
            "cropped head",
            "top of head cut off",
            "head out of frame",
            "face out of frame",
            "eyes out of frame",
            "obscured face",
            "faceless",
        ):
            assert value in layers["type_negative"], (preset_type, value)
        if preset_type == "character":
            assert snapshot["preset_version"] == int(preset["version"])

    scene = _preset("scene", restricted=False)
    scene_snapshot = pipeline.build_prompt_snapshot(
        "scene",
        str(scene["id"]),
        {"model": "mock.safetensors"},
    )
    scene_layers = scene_snapshot["prompt_layers"]
    assert "zoomed out full-body shot" not in scene_layers["type_positive"]
    assert "face fully inside frame" not in scene_layers["type_positive"]
    assert "close-up framing" not in scene_layers["type_negative"]
    assert "cropped head" not in scene_layers["type_negative"]


def test_toy_thumbnail_uses_single_character_context(workshop):
    snapshot = pipeline.build_prompt_snapshot(
        "toy",
        "toy_wand_vibrator",
        {"model": "mock.safetensors"},
    )
    layers = snapshot["prompt_layers"]
    assert snapshot["thumbnail_mode"] == "toy_character_context"
    assert "exactly one adult anime woman" in layers["thumbnail_positive"]
    assert "holding or positioning the featured toy" in layers["thumbnail_positive"]
    assert "single private bedroom or lounge interior" in layers["thumbnail_positive"]
    assert "isolated product shot only" in layers["thumbnail_negative"]
    assert "human body" not in layers["thumbnail_negative"]
    assert "centered product presentation" not in layers["type_positive"]


def test_expansion_thumbnail_uses_minimal_prompt_mode(workshop):
    vaginal = pipeline.build_prompt_snapshot(
        "expansion",
        "expansion_vaginal_display",
        {"model": "mock.safetensors"},
    )
    vaginal_layers = vaginal["prompt_layers"]
    assert vaginal["prompt_mode"] == "minimal_expansion"
    assert vaginal["thumbnail_mode"] == "expansion_minimal"
    assert vaginal["thumbnail_style"] == "minimal_expansion"
    assert vaginal["prompt_positive"] == (
        "uncensored, anime illustration, 2d anime style, cel shading, "
        "one adult woman, solo, visible face, clearly visible vaginal dilation, "
        "visibly widened opening, obvious expansion state, supine pose with "
        "knees raised and apart, pelvic area centered and clearly visible from "
        "the camera, pelvis tilted toward the viewer, stable body silhouette, "
        "target pelvic area unobstructed by hands, thighs, or hair, "
        "visible expansion state only, no additional internal detail"
    )
    assert vaginal["prompt_negative"] == (
        "photorealistic, realistic photo, 3d render, live-action, photographic skin, "
        "censor bar, black bar, white bar, horizontal censorship bar, censorship, "
        "mosaic censorship, bar censor, frame, border"
    )
    assert vaginal_layers["style_positive"] == ""
    assert vaginal_layers["preset_draw_prompt"] == ""
    assert vaginal_layers["preset_tags"] == ""
    assert vaginal_layers["type_positive"] == ""
    assert vaginal_layers["thumbnail_negative"] == (
        "photorealistic, realistic photo, 3d render, live-action, photographic skin, "
        "censor bar, black bar, white bar, horizontal censorship bar, censorship, "
        "mosaic censorship, bar censor, frame, border"
    )
    assert vaginal["masked_prompt_positive"] == ""

    anal = pipeline.build_prompt_snapshot(
        "expansion",
        "expansion_anal_display",
        {"model": "mock.safetensors"},
    )
    assert anal["prompt_mode"] == "minimal_expansion"
    assert anal["prompt_positive"] == (
        "uncensored, anime illustration, 2d anime style, cel shading, "
        "one adult woman, solo, visible face, clearly visible anal dilation, "
        "visibly widened opening, obvious expansion state, side-lying pose "
        "with hips raised, hips raised toward the camera, rear pelvic area "
        "clearly visible, torso adjusted for face visibility, rear pelvic area "
        "oriented toward the viewer, stable body silhouette, target pelvic area "
        "unobstructed by hands, thighs, or hair, visible expansion state only, "
        "no additional internal detail"
    )
    assert anal["prompt_negative"] == (
        "photorealistic, realistic photo, 3d render, live-action, photographic skin, "
        "censor bar, black bar, white bar, horizontal censorship bar, censorship, "
        "mosaic censorship, bar censor, frame, border"
    )

    liquid = pipeline.build_prompt_snapshot(
        "expansion",
        "expansion_vaginal_liquid_fill",
        {"model": "mock.safetensors"},
    )
    assert "visible expansion state only" not in liquid["prompt_positive"]
    assert "fluid originates at the vaginal opening" in liquid["prompt_positive"]
    assert "natural gravity-driven flow" in liquid["prompt_positive"]
    assert "visible overflow allowed" in liquid["prompt_positive"]
    assert "localized wetness around the opening and adjacent tissue" in liquid["prompt_positive"]
    assert "nearby shallow pooling allowed" in liquid["prompt_positive"]
    assert "self-contained liquid-holding space" not in liquid["prompt_positive"]
    assert "glossy" not in liquid["prompt_positive"]
    assert "transparent fluid volume inside the expanded opening" not in liquid["prompt_positive"]
    assert "crystalline" not in liquid["prompt_positive"]
    assert "contact prop" not in liquid["prompt_positive"]
    assert "fluid from elsewhere" in liquid["prompt_negative"]
    assert "fluid flowing upward" in liquid["prompt_negative"]
    assert "impossible flow direction" in liquid["prompt_negative"]
    assert "separate container" in liquid["prompt_negative"]
    assert "cup" in liquid["prompt_negative"]
    assert "external liquid" not in liquid["prompt_negative"]
    assert "dripping liquid" not in liquid["prompt_negative"]
    assert "puddles" not in liquid["prompt_negative"]
    assert "transparent cutaway" in liquid["prompt_negative"]
    assert "internal cavity view" in liquid["prompt_negative"]

    anal_liquid = pipeline.build_prompt_snapshot(
        "expansion",
        "expansion_anal_liquid_fill",
        {"model": "mock.safetensors"},
    )
    assert "clearly visible anal dilation" in anal_liquid["prompt_positive"]
    assert "fluid originates at the anal opening" in anal_liquid["prompt_positive"]
    assert "natural gravity-driven flow" in anal_liquid["prompt_positive"]
    assert "visible overflow allowed" in anal_liquid["prompt_positive"]
    assert "localized wetness around the opening and adjacent tissue" in anal_liquid["prompt_positive"]
    assert "nearby shallow pooling allowed" in anal_liquid["prompt_positive"]
    assert "glossy" not in anal_liquid["prompt_positive"]
    assert "transparent fluid volume inside the expanded opening" not in anal_liquid["prompt_positive"]
    assert "fluid from elsewhere" in anal_liquid["prompt_negative"]
    assert "whole body wet gloss" in anal_liquid["prompt_negative"]
    assert "transparent cutaway" in anal_liquid["prompt_negative"]

    solid = pipeline.build_prompt_snapshot(
        "expansion",
        "expansion_vaginal_solid_fill",
        {"model": "mock.safetensors"},
    )
    assert "one clearly visible smooth solid insert already positioned inside the vaginal opening" in solid["prompt_positive"]
    assert "insert occupies and is partially visible at the opening" in solid["prompt_positive"]
    assert "readable solid object shape and size" in solid["prompt_positive"]
    assert "static insertion state" in solid["prompt_positive"]
    assert "no insertion motion" in solid["prompt_positive"]
    assert "normal human skin texture on the face, torso, arms, legs, and buttocks" in solid["prompt_positive"]
    assert "opaque skin" in solid["prompt_positive"]
    assert "normal skin shading" in solid["prompt_positive"]
    assert "body unchanged except at the opening" in solid["prompt_positive"]
    assert "empty opening" in solid["prompt_negative"]
    assert "missing insert" in solid["prompt_negative"]
    assert "insert hidden inside body" in solid["prompt_negative"]
    assert "insert too small" in solid["prompt_negative"]
    assert "insertion action" in solid["prompt_negative"]
    assert "hand holding insert" in solid["prompt_negative"]
    assert "object merged into body" in solid["prompt_negative"]
    assert "material covering body" in solid["prompt_negative"]
    assert "transparent cutaway" in solid["prompt_negative"]

    anal_solid = pipeline.build_prompt_snapshot(
        "expansion",
        "expansion_anal_solid_fill",
        {"model": "mock.safetensors"},
    )
    assert "clearly visible anal dilation" in anal_solid["prompt_positive"]
    assert "one clearly visible smooth solid insert already positioned inside the anal opening" in anal_solid["prompt_positive"]
    assert "insert occupies and is partially visible at the opening" in anal_solid["prompt_positive"]
    assert "readable solid object shape and size" in anal_solid["prompt_positive"]
    assert "static insertion state" in anal_solid["prompt_positive"]
    assert "no insertion motion" in anal_solid["prompt_positive"]
    assert "normal human skin texture on the face, torso, arms, legs, and buttocks" in anal_solid["prompt_positive"]
    assert "opaque skin" in anal_solid["prompt_positive"]
    assert "body unchanged except at the opening" in anal_solid["prompt_positive"]
    assert "empty opening" in anal_solid["prompt_negative"]
    assert "insert too small" in anal_solid["prompt_negative"]
    assert "insertion action" in anal_solid["prompt_negative"]


def test_expansion_liquid_validation_requires_internal_only_fill(workshop):
    preset = service.resolve_preset("expansion", "expansion_vaginal_liquid_fill")
    base = {
        "people_total": 1,
        "head_visible": True,
        "face_visible": True,
        "target_subject_visible": True,
        "front_shadow": False,
        "front_facing": True,
        "liquid_visible": True,
        "liquid_origin_at_opening": True,
        "flow_direction_consistent": True,
        "overflow_visible": True,
        "wet_area_localized": True,
        "whole_body_wetness": False,
        "circular_frame_detected": False,
        "physical_container_visible": False,
        "cutaway_detected": False,
    }
    failures, warnings = pipeline._thumbnail_validation_outcome(
        "expansion",
        preset,
        "expansion_minimal",
        False,
        base,
    )
    assert failures == []
    assert warnings == []

    failures, warnings = pipeline._thumbnail_validation_outcome(
        "expansion",
        preset,
        "expansion_minimal",
        False,
        {
            **base,
            "liquid_origin_at_opening": False,
            "flow_direction_consistent": False,
            "wet_area_localized": False,
            "whole_body_wetness": True,
            "circular_frame_detected": True,
            "physical_container_visible": True,
            "cutaway_detected": True,
        },
    )
    assert failures == [
        "liquid_origin_mismatch",
        "liquid_direction_inconsistent",
        "liquid_not_localized",
        "whole_body_wetness_detected",
        "circular_frame_detected",
        "physical_container_detected",
        "liquid_cutaway_detected",
    ]
    assert warnings == []


def test_expansion_solid_validation_requires_stable_visible_form(workshop):
    preset = service.resolve_preset("expansion", "expansion_vaginal_solid_fill")
    base = {
        "people_total": 1,
        "head_visible": True,
        "face_visible": True,
        "target_subject_visible": True,
        "front_shadow": False,
        "front_facing": True,
        "insert_visible": True,
        "insert_contact_opening": True,
        "insert_size_readable": True,
        "insertion_motion_visible": False,
        "hand_holding_insert": False,
        "solid_object_visible": True,
        "solid_material_confined_to_opening": True,
        "normal_skin_visible": True,
        "body_material_transformed": False,
        "object_merged_into_body": False,
        "solid_form_static": True,
        "solid_melting_visible": False,
        "solid_fragmentation_visible": False,
        "cutaway_detected": False,
    }
    failures, warnings = pipeline._thumbnail_validation_outcome(
        "expansion",
        preset,
        "expansion_minimal",
        False,
        base,
    )
    assert failures == []
    assert warnings == []

    failures, warnings = pipeline._thumbnail_validation_outcome(
        "expansion",
        preset,
        "expansion_minimal",
        False,
        {
            **base,
            "insert_visible": False,
            "insert_contact_opening": False,
            "insert_size_readable": False,
            "insertion_motion_visible": True,
            "hand_holding_insert": True,
            "solid_material_confined_to_opening": False,
            "normal_skin_visible": False,
            "body_material_transformed": True,
            "object_merged_into_body": True,
            "solid_form_static": False,
            "solid_melting_visible": True,
            "solid_fragmentation_visible": True,
            "cutaway_detected": True,
        },
    )
    assert failures == [
        "insert_required",
        "insert_opening_contact_required",
        "insert_size_unreadable",
        "insertion_action_detected",
        "solid_material_leak",
        "solid_form_unstable",
        "solid_cutaway_detected",
    ]
    assert warnings == []


def test_expansion_inpaint_mask_is_limited_to_pelvic_region(
    workshop,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(config, "COMFY_INPUT_DIR", tmp_path / "comfy-input")
    preset = service.resolve_preset("expansion", "expansion_vaginal_display")
    mask_name = pipeline._expansion_inpaint_mask(preset, 256, 256)
    mask_path = tmp_path / "comfy-input" / mask_name
    with Image.open(mask_path) as mask:
        assert mask.size == (256, 256)
        assert mask.getpixel((128, 165))[0] > 200
        assert mask.getpixel((128, 32))[0] < 20
        assert mask.getpixel((8, 248))[0] < 20


def test_masked_comfy_workflow_uses_two_stage_inpaint():
    graph, _seed = comfy_worker.build_workflow(
        "base prompt",
        "negative prompt",
        768,
        768,
        18,
        1.0,
        masked_prompt="internal prompt",
        mask_image="pelvis-mask.png",
    )
    classes = [node["class_type"] for node in graph.values()]
    assert classes.count("KSampler") == 2
    assert "LoadImage" in classes
    assert "ImageToMask" in classes
    assert "VAEEncodeForInpaint" in classes


def test_vaginal_cervix_visibility_requires_manual_review_not_failure(workshop):
    preset = service.resolve_preset("expansion", "expansion_vaginal_display")
    failures, warnings = pipeline._thumbnail_validation_outcome(
        "expansion",
        preset,
        "expansion_internal",
        False,
        {
            "people_total": 1,
            "head_visible": True,
            "face_visible": True,
            "target_subject_visible": True,
            "direct_internal_view": True,
            "cutaway_detected": False,
            "inner_wall_folds_visible": True,
            "cervix_visible": False,
            "unrelated_organs_visible": False,
            "fluid_visual_visible": True,
            "pose_matches": True,
            "front_shadow": False,
            "front_facing": True,
            "front_back_views": False,
            "identity_consistent": True,
            "front_view_visible": True,
            "scene_matches": True,
        },
    )
    assert failures == []
    assert warnings == ["cervix_manual_review_required"]


def test_expansion_people_and_cutaway_are_manual_review_warnings(workshop):
    preset = service.resolve_preset("expansion", "expansion_vaginal_display")
    failures, warnings = pipeline._thumbnail_validation_outcome(
        "expansion",
        preset,
        "expansion_internal",
        False,
        {
            "people_total": 0,
            "head_visible": True,
            "face_visible": True,
            "target_subject_visible": True,
            "direct_internal_view": True,
            "cutaway_detected": True,
            "inner_wall_folds_visible": True,
            "cervix_visible": False,
            "unrelated_organs_visible": True,
            "fluid_visual_visible": True,
            "pose_matches": True,
            "front_shadow": False,
            "front_facing": True,
            "front_back_views": False,
            "identity_consistent": True,
            "front_view_visible": True,
            "scene_matches": True,
        },
    )
    assert failures == []
    assert warnings == [
        "people_count_manual_review_required",
        "cervix_manual_review_required",
        "unrelated_organs_manual_review_required",
    ]


def test_thumbnail_validation_is_advisory_by_default(workshop, monkeypatch):
    project_root, _ = workshop
    project_root.mkdir(parents=True, exist_ok=True)
    image_path = project_root / "validation.png"
    image_path.write_bytes(_image_bytes())
    preset = _preset("pose", restricted=False)
    monkeypatch.setattr(config, "PRESET_ASSET_SEMANTIC_VALIDATION", "advisory")
    monkeypatch.setattr(
        pipeline,
        "_record_candidate_validation",
        lambda _candidate_id, _validation: None,
    )

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": json.dumps(
                    {
                        "people_total": 1,
                        "head_visible": True,
                        "face_visible": True,
                        "feet_visible": False,
                        "front_shadow": False,
                        "front_facing": True,
                        "front_back_views": False,
                        "identity_consistent": True,
                        "front_view_visible": True,
                        "scene_matches": True,
                        "issues": [],
                    }
                )
            }

    monkeypatch.setattr(
        pipeline.requests,
        "post",
        lambda *_args, **_kwargs: FakeResponse(),
    )
    validation = pipeline._validate_thumbnail_candidate(
        1,
        image_path,
        "pose",
        preset,
        {"thumbnail_mode": "full_body"},
    )
    assert validation["blocking"] is False
    assert validation["status"] == "advisory_failed"
    assert validation["advisory_failures"] == ["full_body_required"]


def test_character_presets_register_with_workshop_metadata_and_latest_version(workshop):
    preset_id = "test_character_workshop_registry"
    database.create_character_appearance_preset(
        preset_id,
        "Workshop Character",
        "Test Work",
        "角色",
        ["Silver Hair", "silver hair", "Red Eyes"],
        ["White Coat", "white coat"],
        ["Calm", "calm"],
        source="user",
    )

    definition = preset_registry.PRESET_KIND_BY_KEY["character"]
    assert definition.order == 4
    assert definition.label == "角色"
    assert definition.composition_enabled is False
    assert definition.supports_thumbnail is True

    initial = service.resolve_preset("character", preset_id)
    assert initial["version"] == 1
    assert initial["tags"] == [
        "Silver Hair",
        "Red Eyes",
        "White Coat",
        "Calm",
    ]
    assert initial["draw_prompt"] == (
        "Silver Hair, Red Eyes, White Coat, Calm"
    )

    database.update_character_appearance_preset(
        preset_id,
        "Workshop Character",
        "Test Work",
        "角色",
        ["Golden Eyes"],
        ["Black Dress"],
        ["Smile"],
        source="user",
    )
    latest = service.resolve_preset("character", preset_id)
    assert latest["version"] == 2
    assert latest["tags"] == ["Golden Eyes", "Black Dress", "Smile"]


def test_character_prompt_snapshot_and_batch_crop_keep_preset_version(
    workshop,
    monkeypatch,
):
    preset = _preset("character", restricted=False)
    preset_id = str(preset["id"])
    snapshot = pipeline.build_prompt_snapshot(
        "character",
        preset_id,
        {"model": "mock.safetensors"},
    )
    assert snapshot["preset_version"] == int(preset["version"])

    source = service.import_source(
        "character",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )
    started: list[tuple[str, set[int] | None]] = []
    monkeypatch.setattr(
        pipeline,
        "_start_job_thread",
        lambda job_id, only_indexes=None: started.append((job_id, only_indexes)),
    )
    job = pipeline.create_job(
        [
            {
                "preset_type": "character",
                "preset_id": preset_id,
                "mode": "crop",
                "source_id": int(source["id"]),
                "crop": {"mode": "cover"},
                "params": {"focus_x": 0.4},
            }
        ]
    )
    item = database.list_preset_asset_job_items(job["job_id"])[0]
    assert started == [(job["job_id"], None)]
    assert item["params"]["params"]["preset_version"] == int(preset["version"])
    assert item["params"]["params"]["focus_x"] == 0.4


@pytest.mark.parametrize(
    "candidate_params",
    [
        pytest.param({}, id="missing-version"),
        pytest.param({"preset_version": 1}, id="old-version"),
    ],
)
def test_stale_character_crop_candidate_cannot_be_adopted(
    workshop,
    candidate_params,
):
    project_root, _ = workshop
    preset_id = "test_character_stale_candidate"
    database.create_character_appearance_preset(
        preset_id,
        "Stale Character",
        "Test Work",
        "角色",
        ["Silver Hair"],
        ["White Coat"],
        [],
        source="user",
    )
    source = service.import_source(
        "character",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )
    candidate = service.create_crop_candidate(
        "character",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "cover"},
        params=candidate_params,
    )

    database.update_character_appearance_preset(
        preset_id,
        "Stale Character",
        "Test Work",
        "角色",
        ["Blue Hair"],
        ["Black Dress"],
        [],
        source="user",
    )
    with pytest.raises(service.PresetAssetError) as stale:
        service.adopt_candidate(int(candidate["id"]), expected_revision=0)

    assert stale.value.status_code == 409
    assert database.get_preset_asset_candidate(int(candidate["id"]))["status"] == "ready"
    assert database.get_active_preset_asset_version("character", preset_id) is None
    assert database.list_preset_asset_versions("character", preset_id) == []
    assert not (
        project_root
        / "studio"
        / "frontend"
        / "public"
        / "character-appearance-presets"
        / f"{preset_id}.webp"
    ).exists()


def test_character_thumbnail_status_does_not_index_unversioned_existing_file(
    workshop,
):
    project_root, _ = workshop
    preset_id = "test_character_existing_thumbnail"
    database.create_character_appearance_preset(
        preset_id,
        "Existing Character",
        "",
        "角色",
        ["Silver Hair"],
        [],
        [],
        source="user",
    )
    public_path = (
        project_root
        / "studio"
        / "frontend"
        / "public"
        / "character-appearance-presets"
        / f"{preset_id}.webp"
    )
    public_path.parent.mkdir(parents=True)
    public_path.write_bytes(b"existing-unversioned-image")

    status = service.character_thumbnail_status(preset_id)

    assert status["has_thumbnail"] is True
    assert status["thumbnail_stale"] is True
    assert status["thumbnail_version"] is None
    assert status["current_preset_version"] == 1
    assert database.get_active_preset_asset_version("character", preset_id) is None
    assert database.list_preset_asset_versions("character", preset_id) == []


def test_appearance_preset_api_exposes_character_thumbnail_status(client, workshop):
    preset_id = "test_character_api_thumbnail_status"
    database.create_character_appearance_preset(
        preset_id,
        "API Character",
        "",
        "角色",
        ["Silver Hair"],
        [],
        [],
        source="user",
    )

    response = client.get(
        "/api/prompt-agent/appearance-presets",
        params={"keyword": "API Character"},
    )

    assert response.status_code == 200
    item = next(
        item
        for item in response.json()["items"]
        if item["preset_id"] == preset_id
    )
    assert item["has_thumbnail"] is False
    assert item["thumbnail_url"] is None
    assert item["thumbnail_stale"] is False
    assert item["thumbnail_version"] is None
    assert item["current_preset_version"] == 1


def test_character_thumbnail_statuses_batch_load_versions_and_candidates(
    client,
    workshop,
    monkeypatch,
):
    preset_ids = [
        "test_batch_character_no_thumbnail",
        "test_batch_character_static_thumbnail",
        "test_batch_character_active_thumbnail",
        "test_batch_character_stale_thumbnail",
    ]
    for index, preset_id in enumerate(preset_ids, start=1):
        database.create_character_appearance_preset(
            preset_id,
            f"Batch Character {index}",
            "Test Work",
            "角色",
            [f"Tag {index}"],
            [],
            [],
            source="user",
        )

    project_root, _ = workshop
    public_root = (
        project_root
        / "studio"
        / "frontend"
        / "public"
        / "character-appearance-presets"
    )
    public_root.mkdir(parents=True)
    (public_root / f"{preset_ids[1]}.webp").write_bytes(b"static")

    def adopt_character_thumbnail(preset_id: str) -> None:
        source = service.import_source(
            "character",
            preset_id,
            _image_bytes("PNG", (180, 240)),
        )
        response = client.post(
            (
                "/api/preset-assets/presets/character/"
                f"{preset_id}/candidates/crop"
            ),
            json={
                "source_id": int(source["id"]),
                "crop": {"mode": "cover"},
            },
        )
        assert response.status_code == 200
        service.adopt_candidate(
            int(response.json()["id"]),
            expected_revision=0,
        )

    adopt_character_thumbnail(preset_ids[2])
    adopt_character_thumbnail(preset_ids[3])
    database.update_character_appearance_preset(
        preset_ids[3],
        "Batch Character 4",
        "Test Work",
        "角色",
        ["Updated Tag"],
        [],
        [],
        source="user",
    )

    version_query_count = 0
    candidate_query_count = 0
    original_list_versions = database.list_active_preset_asset_versions
    original_list_candidates = database.list_preset_asset_candidates_by_ids

    def counted_list_versions(kinds):
        nonlocal version_query_count
        version_query_count += 1
        return original_list_versions(kinds)

    def counted_list_candidates(candidate_ids):
        nonlocal candidate_query_count
        candidate_query_count += 1
        return original_list_candidates(candidate_ids)

    monkeypatch.setattr(
        database,
        "list_active_preset_asset_versions",
        counted_list_versions,
    )
    monkeypatch.setattr(
        database,
        "list_preset_asset_candidates_by_ids",
        counted_list_candidates,
    )
    monkeypatch.setattr(
        database,
        "list_preset_asset_candidates",
        lambda *args, **kwargs: pytest.fail("per-preset candidate query used"),
    )

    response = client.get(
        "/api/prompt-agent/appearance-presets",
        params={"keyword": "Batch Character"},
    )

    assert response.status_code == 200
    items = {
        item["preset_id"]: item
        for item in response.json()["items"]
    }
    assert items[preset_ids[0]]["has_thumbnail"] is False
    assert items[preset_ids[0]]["thumbnail_stale"] is False
    assert items[preset_ids[1]]["has_thumbnail"] is True
    assert items[preset_ids[1]]["thumbnail_stale"] is True
    assert items[preset_ids[1]]["thumbnail_version"] is None
    assert items[preset_ids[2]]["thumbnail_version"] == 1
    assert items[preset_ids[2]]["thumbnail_stale"] is False
    assert items[preset_ids[3]]["thumbnail_version"] == 1
    assert items[preset_ids[3]]["current_preset_version"] == 2
    assert items[preset_ids[3]]["thumbnail_stale"] is True
    assert version_query_count == 1
    assert candidate_query_count == 1


def test_direct_character_crop_route_records_current_preset_version(
    client,
    workshop,
):
    preset_id = "test_character_direct_crop_version"
    database.create_character_appearance_preset(
        preset_id,
        "Direct Crop Character",
        "",
        "角色",
        ["Silver Hair"],
        [],
        [],
        source="user",
    )
    source = service.import_source(
        "character",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )

    response = client.post(
        f"/api/preset-assets/presets/character/{preset_id}/candidates/crop",
        json={
            "source_id": int(source["id"]),
            "crop": {"mode": "cover"},
        },
    )

    assert response.status_code == 200
    candidate = database.get_preset_asset_candidate(
        int(response.json()["id"])
    )
    assert candidate is not None
    assert candidate["params"]["preset_version"] == 1
    adopted = service.adopt_candidate(int(candidate["id"]), expected_revision=0)
    assert adopted["ok"] is True


def test_thumbnail_validation_preserves_candidate_params(workshop):
    candidate_id = database.insert_preset_asset_candidate(
        "character",
        "test_character_validation_params",
        "ai",
        "ready",
        {
            "preset_version": 1,
            "template_version": "thumbnail_template_v25",
            "nested": {"kept": True},
        },
        prompt_positive="positive",
        prompt_negative="negative",
        template_version="thumbnail_template_v25",
        model="mock.safetensors",
    )

    pipeline._record_candidate_validation(
        candidate_id,
        {"status": "passed"},
    )

    candidate = database.get_preset_asset_candidate(candidate_id)
    assert candidate is not None
    assert candidate["params"]["preset_version"] == 1
    assert candidate["params"]["template_version"] == "thumbnail_template_v25"
    assert candidate["params"]["nested"] == {"kept": True}
    assert candidate["params"]["thumbnail_validation"] == {"status": "passed"}


def test_pose_prompts_do_not_force_nudity_or_strip_explicit_clothing(workshop):
    neutral_ids = (
        "solo_insertable_toy_back",
        "duo_soft_ribbon_wrist_play",
        "impact_spanking_over_knee_consensual",
        "group_triangle_three",
    )
    for preset_id in neutral_ids:
        snapshot = pipeline.build_prompt_snapshot(
            "pose",
            preset_id,
            {"model": "mock.safetensors"},
        )
        layers = snapshot["prompt_layers"]
        assert "completely nude" not in layers["type_positive"], preset_id
        assert "no clothing" not in layers["type_positive"], preset_id
        assert "partially dressed" not in layers["type_negative"], preset_id
        assert layers["generation_prompt"] == layers["preset_draw_prompt"], preset_id

    explicit_clothing_ids = (
        "solo_stocking_remove",
        "solo_open_shirt_bed",
        "solo_latex_zip_partial",
        "duo_chair_face_to_face_embrace",
    )
    for preset_id in explicit_clothing_ids:
        snapshot = pipeline.build_prompt_snapshot(
            "pose",
            preset_id,
            {"model": "mock.safetensors"},
        )
        layers = snapshot["prompt_layers"]
        assert "completely nude" not in layers["type_positive"], preset_id
        assert layers["generation_prompt"] == layers["preset_draw_prompt"], preset_id


def test_crop_adopt_manifest_conflict_discard_and_rollback(workshop):
    project_root, managed_root = workshop
    preset = _preset("clothing", restricted=False)
    preset_id = str(preset["id"])
    source = service.import_source(
        "clothing",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )
    first = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "cover", "focus_x": 0.5, "focus_y": 0.4, "zoom": 1.1},
    )
    adopted = service.adopt_candidate(int(first["id"]), expected_revision=0)
    public_path = (
        project_root / "studio" / "frontend" / "public" / "clothing-presets" / f"{preset_id}.webp"
    )
    dist_path = (
        project_root / "studio" / "frontend" / "dist" / "clothing-presets" / f"{preset_id}.webp"
    )
    assert public_path.read_bytes() == dist_path.read_bytes()
    manifest = json.loads((public_path.parent / "_manifest.json").read_text("utf-8"))
    assert manifest[preset_id] == f"/clothing-presets/{preset_id}.webp"
    assert Path(str(adopted["version"]["url"])).name

    second = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "contain"},
    )
    active = database.get_active_preset_asset_version("clothing", preset_id)
    public_before_conflict = public_path.read_bytes()
    with pytest.raises(service.PresetAssetError) as conflict:
        service.adopt_candidate(int(second["id"]), expected_revision=0)
    assert conflict.value.status_code == 409
    assert public_path.read_bytes() == public_before_conflict
    assert database.get_preset_asset_write_lease("clothing", preset_id) is None
    assert not list((Path(config.PRESET_ASSET_ROOT) / "journals").glob("*.json"))

    service.discard_candidate(int(second["id"]))
    assert database.get_preset_asset_candidate(int(second["id"]))["status"] == "discarded"
    assert database.get_preset_asset_write_lease("clothing", preset_id) is None

    rolled_back = service.rollback_version(
        "clothing",
        preset_id,
        1,
        expected_revision=int(active["id"]),
    )
    assert rolled_back["ok"] is True
    assert database.get_active_preset_asset_version("clothing", preset_id)["version"] == 1
    assert public_path.is_file()
    assert dist_path.is_file()


def test_concurrent_adoption_has_one_winner(workshop, monkeypatch):
    preset = _preset("clothing", restricted=False)
    preset_id = str(preset["id"])
    source = service.import_source(
        "clothing",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )
    candidates = [
        service.create_crop_candidate(
            "clothing",
            preset_id,
            source_id=int(source["id"]),
            crop={"mode": mode, "focus_x": focus},
        )
        for mode, focus in (("cover", 0.4), ("contain", 0.6))
    ]

    real_acquire = database.acquire_preset_asset_write_lease
    barrier = threading.Barrier(2)

    def synchronized_acquire(*args, **kwargs):
        barrier.wait(timeout=5)
        return real_acquire(*args, **kwargs)

    monkeypatch.setattr(
        database,
        "acquire_preset_asset_write_lease",
        synchronized_acquire,
    )
    results: list[tuple[str, int]] = []

    def run(candidate_id: int) -> None:
        try:
            service.adopt_candidate(candidate_id, expected_revision=0)
            results.append(("ok", candidate_id))
        except service.PresetAssetError as exc:
            results.append(("error", exc.status_code))

    threads = [
        threading.Thread(target=run, args=(int(candidate["id"]),))
        for candidate in candidates
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    successful = [candidate_id for status, candidate_id in results if status == "ok"]
    failed = [status_code for status, status_code in results if status == "error"]
    assert failed == [409]
    assert len(successful) == 1
    winner = successful[0]
    active = database.get_active_preset_asset_version("clothing", preset_id)
    assert active is not None
    assert int(active["candidate_id"]) == winner
    assert database.get_preset_asset_write_lease("clothing", preset_id) is None
    assert not list((Path(config.PRESET_ASSET_ROOT) / "journals").glob("*.json"))


def test_write_lease_renewal_cannot_revive_expired_owner(workshop):
    preset = _preset("pose", restricted=False)
    preset_id = str(preset["id"])
    candidate_id = database.insert_preset_asset_candidate(
        "pose",
        preset_id,
        "ai",
        "ready",
        {},
    )
    owner_token = "renewable-owner"
    assert database.acquire_preset_asset_write_lease(
        "pose",
        preset_id,
        "adopt",
        0,
        owner_token,
        candidate_id=candidate_id,
        ttl_seconds=30,
    ) == "acquired"
    first_expiry = float(
        database.get_preset_asset_write_lease("pose", preset_id)["expires_at"]
    )

    assert database.renew_preset_asset_write_lease(
        "pose",
        preset_id,
        owner_token,
        ttl_seconds=120,
    )
    renewed_expiry = float(
        database.get_preset_asset_write_lease("pose", preset_id)["expires_at"]
    )
    assert renewed_expiry > first_expiry

    with database.get_connection() as conn:
        conn.execute(
            """
            UPDATE preset_asset_write_leases
            SET expires_at = ?
            WHERE preset_type = ? AND preset_id = ?
            """,
            (time.time() - 1, "pose", preset_id),
        )
    assert not database.renew_preset_asset_write_lease(
        "pose",
        preset_id,
        owner_token,
        ttl_seconds=120,
    )


def test_stale_adoption_journal_restores_new_active_version(workshop, monkeypatch):
    project_root, _ = workshop
    preset = _preset("clothing", restricted=False)
    preset_id = str(preset["id"])
    source = service.import_source(
        "clothing",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )
    first = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "cover"},
    )
    service.adopt_candidate(int(first["id"]), expected_revision=0)
    first_active = database.get_active_preset_asset_version("clothing", preset_id)
    stale_candidate = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "contain", "focus_x": 0.2},
    )
    winning_candidate = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "contain", "focus_x": 0.8},
    )

    stale_owner = "stale-adoption-owner"
    assert database.acquire_preset_asset_write_lease(
        "clothing",
        preset_id,
        "adopt",
        int(first_active["id"]),
        stale_owner,
        candidate_id=int(stale_candidate["id"]),
        ttl_seconds=30,
    ) == "acquired"

    class AlwaysOwnedGuard:
        def assert_owned(self) -> None:
            return None

    stale_data = b"stale-late-adoption"
    public_path, dist_path, stale_journal = service._sync_files(
        "clothing",
        preset_id,
        stale_data,
        journal_event="adopt_candidate",
        owner_token=stale_owner,
        lease_guard=AlwaysOwnedGuard(),
        expected_revision=int(first_active["id"]),
        version_number=2,
        candidate_id=int(stale_candidate["id"]),
    )
    with database.get_connection() as conn:
        conn.execute(
            """
            UPDATE preset_asset_write_leases
            SET expires_at = ?
            WHERE preset_type = ? AND preset_id = ?
            """,
            (time.time() - 1, "clothing", preset_id),
        )

    monkeypatch.setattr(
        service,
        "_recover_stale_write_journals",
        lambda *_args, **_kwargs: [],
    )
    service.adopt_candidate(
        int(winning_candidate["id"]),
        expected_revision=int(first_active["id"]),
    )
    active = database.get_active_preset_asset_version("clothing", preset_id)
    active_data = service._version_archive_path(
        "clothing",
        preset_id,
        int(active["version"]),
    ).read_bytes()

    service._atomic_write(public_path, stale_data)
    service._atomic_write(dist_path, stale_data)
    assert service._recover_write_journal(stale_journal) == "restored"
    assert public_path.read_bytes() == active_data
    assert dist_path.read_bytes() == active_data
    assert not stale_journal.exists()
    assert database.get_active_preset_asset_version("clothing", preset_id)["id"] == active["id"]


def test_failed_old_writer_does_not_recover_new_owner_journal(workshop):
    project_root, _ = workshop
    preset = _preset("clothing", restricted=False)
    preset_id = str(preset["id"])
    source = service.import_source(
        "clothing",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )
    first = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "cover"},
    )
    service.adopt_candidate(int(first["id"]), expected_revision=0)
    first_active = database.get_active_preset_asset_version("clothing", preset_id)
    stale_candidate = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "contain", "focus_x": 0.2},
    )
    winning_candidate = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "contain", "focus_x": 0.8},
    )

    class AlwaysOwnedGuard:
        def assert_owned(self) -> None:
            return None

    stale_owner = "stale-writer-owner"
    assert database.acquire_preset_asset_write_lease(
        "clothing",
        preset_id,
        "adopt",
        int(first_active["id"]),
        stale_owner,
        candidate_id=int(stale_candidate["id"]),
        ttl_seconds=30,
    ) == "acquired"
    stale_data = b"stale-writer-data"
    public_path, dist_path, stale_journal = service._sync_files(
        "clothing",
        preset_id,
        stale_data,
        journal_event="adopt_candidate",
        owner_token=stale_owner,
        lease_guard=AlwaysOwnedGuard(),
        expected_revision=int(first_active["id"]),
        version_number=2,
        candidate_id=int(stale_candidate["id"]),
    )
    with database.get_connection() as conn:
        conn.execute(
            """
            UPDATE preset_asset_write_leases
            SET expires_at = ?
            WHERE preset_type = ? AND preset_id = ?
            """,
            (time.time() - 1, "clothing", preset_id),
        )

    new_owner = "new-writer-owner"
    assert database.acquire_preset_asset_write_lease(
        "clothing",
        preset_id,
        "adopt",
        int(first_active["id"]),
        new_owner,
        candidate_id=int(winning_candidate["id"]),
    ) == "acquired"
    recovered = service._recover_stale_write_journals(
        "clothing",
        preset_id,
        new_owner,
    )
    assert recovered[0]["status"] == "recovered"
    assert not stale_journal.exists()

    new_data = b"new-writer-data"
    _public_path, _dist_path, new_journal = service._sync_files(
        "clothing",
        preset_id,
        new_data,
        journal_event="adopt_candidate",
        owner_token=new_owner,
        lease_guard=AlwaysOwnedGuard(),
        expected_revision=int(first_active["id"]),
        version_number=2,
        candidate_id=int(winning_candidate["id"]),
    )
    service._recover_write_after_error(
        stale_journal,
        preset_type="clothing",
        preset_id=preset_id,
        owner_token=stale_owner,
    )

    assert public_path.read_bytes() == new_data
    assert dist_path.read_bytes() == new_data
    assert new_journal.is_file()
    lease = database.get_preset_asset_write_lease("clothing", preset_id)
    assert lease is not None
    assert lease["owner_token"] == new_owner

    assert service._recover_write_journal(
        new_journal,
        expected_owner_token=new_owner,
    ) == "restored"
    assert database.get_preset_asset_write_lease("clothing", preset_id) is None


def test_failed_old_writer_restores_active_after_new_owner_committed(workshop):
    project_root, _ = workshop
    preset = _preset("clothing", restricted=False)
    preset_id = str(preset["id"])
    source = service.import_source(
        "clothing",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )
    first = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "cover"},
    )
    service.adopt_candidate(int(first["id"]), expected_revision=0)
    first_active = database.get_active_preset_asset_version("clothing", preset_id)
    stale_candidate = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "contain", "focus_x": 0.2},
    )
    winning_candidate = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "contain", "focus_x": 0.8},
    )

    class AlwaysOwnedGuard:
        def assert_owned(self) -> None:
            return None

    stale_owner = "old-writer-owner"
    assert database.acquire_preset_asset_write_lease(
        "clothing",
        preset_id,
        "adopt",
        int(first_active["id"]),
        stale_owner,
        candidate_id=int(stale_candidate["id"]),
        ttl_seconds=30,
    ) == "acquired"
    stale_data = b"late-stale-writer-data"
    public_path, dist_path, stale_journal = service._sync_files(
        "clothing",
        preset_id,
        stale_data,
        journal_event="adopt_candidate",
        owner_token=stale_owner,
        lease_guard=AlwaysOwnedGuard(),
        expected_revision=int(first_active["id"]),
        version_number=2,
        candidate_id=int(stale_candidate["id"]),
    )
    with database.get_connection() as conn:
        conn.execute(
            """
            UPDATE preset_asset_write_leases
            SET expires_at = ?
            WHERE preset_type = ? AND preset_id = ?
            """,
            (time.time() - 1, "clothing", preset_id),
        )

    service.adopt_candidate(
        int(winning_candidate["id"]),
        expected_revision=int(first_active["id"]),
    )
    active = database.get_active_preset_asset_version("clothing", preset_id)
    active_data = service._version_archive_path(
        "clothing",
        preset_id,
        int(active["version"]),
    ).read_bytes()
    assert not stale_journal.exists()

    service._atomic_write(public_path, stale_data)
    service._atomic_write(dist_path, stale_data)
    service._recover_write_after_error(
        stale_journal,
        preset_type="clothing",
        preset_id=preset_id,
        owner_token=stale_owner,
    )

    assert public_path.read_bytes() == active_data
    assert dist_path.read_bytes() == active_data
    assert database.get_preset_asset_write_lease("clothing", preset_id) is None
    assert not list((Path(config.PRESET_ASSET_ROOT) / "journals").glob("*.json"))


def test_failed_old_rollback_writer_does_not_recover_new_owner_journal(workshop):
    project_root, _ = workshop
    preset = _preset("clothing", restricted=False)
    preset_id = str(preset["id"])
    source = service.import_source(
        "clothing",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )
    first = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "cover"},
    )
    service.adopt_candidate(int(first["id"]), expected_revision=0)
    first_active = database.get_active_preset_asset_version("clothing", preset_id)
    second = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "contain", "focus_x": 0.8},
    )
    service.adopt_candidate(
        int(second["id"]),
        expected_revision=int(first_active["id"]),
    )
    second_active = database.get_active_preset_asset_version("clothing", preset_id)
    first_archive = service._version_archive_path("clothing", preset_id, 1)

    class AlwaysOwnedGuard:
        def assert_owned(self) -> None:
            return None

    stale_owner = "stale-rollback-owner"
    assert database.acquire_preset_asset_write_lease(
        "clothing",
        preset_id,
        "rollback",
        int(second_active["id"]),
        stale_owner,
        target_version_id=int(first_active["id"]),
        ttl_seconds=30,
    ) == "acquired"
    stale_data = b"stale-rollback-data"
    public_path, dist_path, stale_journal = service._sync_files(
        "clothing",
        preset_id,
        stale_data,
        journal_event="rollback_version",
        owner_token=stale_owner,
        lease_guard=AlwaysOwnedGuard(),
        expected_revision=int(second_active["id"]),
        version_number=1,
        candidate_id=int(first_active["candidate_id"]),
        target_version_id=int(first_active["id"]),
    )
    with database.get_connection() as conn:
        conn.execute(
            """
            UPDATE preset_asset_write_leases
            SET expires_at = ?
            WHERE preset_type = ? AND preset_id = ?
            """,
            (time.time() - 1, "clothing", preset_id),
        )

    new_owner = "new-rollback-owner"
    assert database.acquire_preset_asset_write_lease(
        "clothing",
        preset_id,
        "rollback",
        int(second_active["id"]),
        new_owner,
        target_version_id=int(first_active["id"]),
    ) == "acquired"
    recovered = service._recover_stale_write_journals(
        "clothing",
        preset_id,
        new_owner,
    )
    assert recovered[0]["status"] == "recovered"
    assert not stale_journal.exists()

    new_data = first_archive.read_bytes()
    _public_path, _dist_path, new_journal = service._sync_files(
        "clothing",
        preset_id,
        new_data,
        journal_event="rollback_version",
        owner_token=new_owner,
        lease_guard=AlwaysOwnedGuard(),
        expected_revision=int(second_active["id"]),
        version_number=1,
        candidate_id=int(first_active["candidate_id"]),
        target_version_id=int(first_active["id"]),
    )
    service._recover_write_after_error(
        stale_journal,
        preset_type="clothing",
        preset_id=preset_id,
        owner_token=stale_owner,
    )

    assert public_path.read_bytes() == new_data
    assert dist_path.read_bytes() == new_data
    assert new_journal.is_file()
    lease = database.get_preset_asset_write_lease("clothing", preset_id)
    assert lease is not None
    assert lease["owner_token"] == new_owner

    assert service._recover_write_journal(
        new_journal,
        expected_owner_token=new_owner,
    ) == "restored"
    assert database.get_preset_asset_write_lease("clothing", preset_id) is None


def test_startup_recovers_journal_when_interrupted_owner_lease_expired(workshop):
    preset = _preset("clothing", restricted=False)
    preset_id = str(preset["id"])
    source = service.import_source(
        "clothing",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )
    first = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "cover"},
    )
    service.adopt_candidate(int(first["id"]), expected_revision=0)
    first_active = database.get_active_preset_asset_version("clothing", preset_id)
    stale_candidate = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "contain", "focus_x": 0.2},
    )
    winning_candidate = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "contain", "focus_x": 0.8},
    )

    class AlwaysOwnedGuard:
        def assert_owned(self) -> None:
            return None

    stale_owner = "interrupted-journal-owner"
    assert database.acquire_preset_asset_write_lease(
        "clothing",
        preset_id,
        "adopt",
        int(first_active["id"]),
        stale_owner,
        candidate_id=int(stale_candidate["id"]),
        ttl_seconds=30,
    ) == "acquired"
    public_path, dist_path, stale_journal = service._sync_files(
        "clothing",
        preset_id,
        b"partial-stale-data",
        journal_event="adopt_candidate",
        owner_token=stale_owner,
        lease_guard=AlwaysOwnedGuard(),
        expected_revision=int(first_active["id"]),
        version_number=2,
        candidate_id=int(stale_candidate["id"]),
    )
    with database.get_connection() as conn:
        conn.execute(
            """
            UPDATE preset_asset_write_leases
            SET expires_at = ?
            WHERE preset_type = ? AND preset_id = ?
            """,
            (time.time() - 1, "clothing", preset_id),
        )

    takeover_owner = "interrupted-takeover-owner"
    assert database.acquire_preset_asset_write_lease(
        "clothing",
        preset_id,
        "adopt",
        int(first_active["id"]),
        takeover_owner,
        candidate_id=int(winning_candidate["id"]),
        ttl_seconds=30,
    ) == "acquired"
    with database.get_connection() as conn:
        conn.execute(
            """
            UPDATE preset_asset_write_leases
            SET expires_at = ?
            WHERE preset_type = ? AND preset_id = ? AND owner_token = ?
            """,
            (time.time() - 1, "clothing", preset_id, takeover_owner),
        )

    active_data = service._version_archive_path(
        "clothing",
        preset_id,
        int(first_active["version"]),
    ).read_bytes()
    recovered = service.recover_pending_write_journals()

    assert recovered[0]["status"] == "restored"
    assert not stale_journal.exists()
    assert public_path.read_bytes() == active_data
    assert dist_path.read_bytes() == active_data
    assert database.get_preset_asset_write_lease("clothing", preset_id) is None


def test_adoption_commit_failure_restores_previous_assets(workshop, monkeypatch):
    project_root, _ = workshop
    preset = _preset("clothing", restricted=False)
    preset_id = str(preset["id"])
    source = service.import_source(
        "clothing",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )
    first = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "cover"},
    )
    adopted = service.adopt_candidate(int(first["id"]), expected_revision=0)
    active = database.get_active_preset_asset_version("clothing", preset_id)
    public_path = (
        project_root
        / "studio"
        / "frontend"
        / "public"
        / "clothing-presets"
        / f"{preset_id}.webp"
    )
    dist_path = (
        project_root
        / "studio"
        / "frontend"
        / "dist"
        / "clothing-presets"
        / f"{preset_id}.webp"
    )
    old_public = public_path.read_bytes()
    old_dist = dist_path.read_bytes()
    second = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "contain", "focus_x": 0.7},
    )

    def fail_commit(*_args, **_kwargs):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(database, "commit_preset_asset_adoption", fail_commit)
    with pytest.raises(RuntimeError, match="simulated commit failure"):
        service.adopt_candidate(
            int(second["id"]),
            expected_revision=int(active["id"]),
        )

    assert public_path.read_bytes() == old_public
    assert dist_path.read_bytes() == old_dist
    assert database.get_active_preset_asset_version("clothing", preset_id)["id"] == adopted["version"]["id"]
    assert database.get_preset_asset_candidate(int(second["id"]))["status"] == "ready"
    assert database.get_preset_asset_write_lease("clothing", preset_id) is None
    assert not list((Path(config.PRESET_ASSET_ROOT) / "journals").glob("*.json"))


def test_interrupted_adoption_recovers_old_files(workshop, monkeypatch):
    project_root, _ = workshop
    preset = _preset("pose", restricted=False)
    preset_id = str(preset["id"])
    source = service.import_source(
        "pose",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )
    candidate = service.create_crop_candidate(
        "pose",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "cover"},
    )

    def interrupt_commit(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(database, "commit_preset_asset_adoption", interrupt_commit)
    with pytest.raises(KeyboardInterrupt):
        service.adopt_candidate(int(candidate["id"]), expected_revision=0)

    journals = list((Path(config.PRESET_ASSET_ROOT) / "journals").glob("*.json"))
    assert len(journals) == 1
    assert database.get_preset_asset_write_lease("pose", preset_id) is not None
    recovered = service.recover_pending_write_journals()
    assert recovered[0]["status"] == "restored"
    public_path = (
        project_root
        / "studio"
        / "frontend"
        / "public"
        / "pose-presets"
        / f"{preset_id}.{preset_registry.PRESET_KIND_BY_KEY['pose'].image_extension}"
    )
    assert not public_path.exists()
    assert database.get_active_preset_asset_version("pose", preset_id) is None
    assert database.get_preset_asset_candidate(int(candidate["id"]))["status"] == "ready"
    assert database.get_preset_asset_write_lease("pose", preset_id) is None


def test_interrupted_adoption_keeps_committed_files(workshop, monkeypatch):
    project_root, _ = workshop
    preset = _preset("pose", restricted=False)
    preset_id = str(preset["id"])
    source = service.import_source(
        "pose",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )
    candidate = service.create_crop_candidate(
        "pose",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "cover"},
    )
    real_commit = database.commit_preset_asset_adoption

    def commit_then_interrupt(*args, **kwargs):
        real_commit(*args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(
        database,
        "commit_preset_asset_adoption",
        commit_then_interrupt,
    )
    with pytest.raises(KeyboardInterrupt):
        service.adopt_candidate(int(candidate["id"]), expected_revision=0)

    public_path = (
        project_root
        / "studio"
        / "frontend"
        / "public"
        / "pose-presets"
        / f"{preset_id}.{preset_registry.PRESET_KIND_BY_KEY['pose'].image_extension}"
    )
    committed_bytes = public_path.read_bytes()
    assert database.get_preset_asset_candidate(int(candidate["id"]))["status"] == "adopted"
    recovered = service.recover_pending_write_journals()
    assert recovered[0]["status"] == "cleaned"
    assert public_path.read_bytes() == committed_bytes
    assert database.get_active_preset_asset_version("pose", preset_id)["version"] == 1


def test_rollback_interruption_restores_current_files(workshop, monkeypatch):
    project_root, _ = workshop
    preset = _preset("clothing", restricted=False)
    preset_id = str(preset["id"])
    source = service.import_source(
        "clothing",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )
    first = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "cover"},
    )
    service.adopt_candidate(int(first["id"]), expected_revision=0)
    current = database.get_active_preset_asset_version("clothing", preset_id)
    public_path = (
        project_root
        / "studio"
        / "frontend"
        / "public"
        / "clothing-presets"
        / f"{preset_id}.webp"
    )
    current_bytes = public_path.read_bytes()
    second = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "contain", "focus_x": 0.7},
    )
    service.adopt_candidate(int(second["id"]), expected_revision=int(current["id"]))
    newest = database.get_active_preset_asset_version("clothing", preset_id)
    current_bytes = public_path.read_bytes()

    def interrupt_commit(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(database, "commit_preset_asset_rollback", interrupt_commit)
    with pytest.raises(KeyboardInterrupt):
        service.rollback_version(
            "clothing",
            preset_id,
            1,
            expected_revision=int(newest["id"]),
        )

    assert database.get_active_preset_asset_version("clothing", preset_id)["id"] == newest["id"]
    recovered = service.recover_pending_write_journals()
    assert recovered[0]["status"] == "restored"
    assert public_path.read_bytes() == current_bytes
    assert database.get_active_preset_asset_version("clothing", preset_id)["id"] == newest["id"]


def test_candidate_mutations_respect_active_write_lease(workshop):
    preset = _preset("pose", restricted=False)
    preset_id = str(preset["id"])
    candidate_id = database.insert_preset_asset_candidate(
        "pose",
        preset_id,
        "ai",
        "ready",
        {},
    )
    owner_token = "test-write-owner"
    assert database.acquire_preset_asset_write_lease(
        "pose",
        preset_id,
        "adopt",
        0,
        owner_token,
        candidate_id=candidate_id,
    ) == "acquired"

    with pytest.raises(service.PresetAssetError) as discard_error:
        service.discard_candidate(candidate_id)
    assert discard_error.value.status_code == 409
    with pytest.raises(service.PresetAssetError) as clear_error:
        service.clear_candidates("pose", preset_id)
    assert clear_error.value.status_code == 409
    assert database.get_preset_asset_candidate(candidate_id)["status"] == "ready"
    assert database.release_preset_asset_write_lease(
        "pose",
        preset_id,
        owner_token,
    )


def test_clear_candidates_discards_unadopted_and_preserves_adopted(workshop):
    preset = _preset("clothing", restricted=False)
    preset_id = str(preset["id"])
    source = service.import_source(
        "clothing",
        preset_id,
        _image_bytes("JPEG", (180, 240)),
        mime_type="image/jpeg",
    )
    adopted = service.create_crop_candidate(
        "clothing",
        preset_id,
        source_id=int(source["id"]),
        crop={"mode": "cover", "focus_x": 0.5, "focus_y": 0.4},
    )
    service.adopt_candidate(int(adopted["id"]), expected_revision=0)
    pending = [
        service.create_crop_candidate(
            "clothing",
            preset_id,
            source_id=int(source["id"]),
            crop={"mode": "contain"},
        )
        for _ in range(2)
    ]

    result = service.clear_candidates("clothing", preset_id)

    assert result == {"ok": True, "cleared_count": 2}
    assert database.get_preset_asset_candidate(int(adopted["id"]))["status"] == "adopted"
    assert {
        database.get_preset_asset_candidate(int(item["id"]))["status"]
        for item in pending
    } == {"discarded"}
    audit = (
        database.get_connection()
        .execute(
            "SELECT detail_json FROM preset_asset_audit WHERE event = ?",
            ("candidates_cleared",),
        )
        .fetchone()
    )
    assert json.loads(audit["detail_json"]) == {"cleared_count": 2}


def test_clear_candidates_rejects_active_generation_without_partial_clear(workshop):
    preset = _preset("pose", restricted=False)
    preset_id = str(preset["id"])
    ready_id = database.insert_preset_asset_candidate(
        "pose",
        preset_id,
        "ai",
        "ready",
        {},
    )
    running_id = database.insert_preset_asset_candidate(
        "pose",
        preset_id,
        "ai",
        "running",
        {},
    )

    with pytest.raises(service.PresetAssetError) as active:
        service.clear_candidates("pose", preset_id)

    assert active.value.status_code == 409
    assert database.get_preset_asset_candidate(ready_id)["status"] == "ready"
    assert database.get_preset_asset_candidate(running_id)["status"] == "running"


def test_restricted_presets_are_filtered_and_blocked(workshop):
    restricted = _preset("pose", restricted=True)
    kind = preset_registry.PRESET_KIND_BY_KEY["pose"]
    catalog = service.catalog(restriction=True)
    pose_items = next(item for item in catalog["items"] if item["kind"] == "pose")["items"]
    assert str(restricted["id"]) not in {str(item["preset_id"]) for item in pose_items}
    with pytest.raises(service.PresetAssetError) as blocked:
        service.ensure_restricted_access("pose", str(restricted["id"]), True)
    assert blocked.value.status_code == 403
    assert kind.supports_thumbnail is True


def test_catalog_query_filters_exact_candidate_status(client, workshop):
    preset = _preset("pose", restricted=False)
    preset_id = str(preset["id"])
    for status in ("ready", "running", "failed", "cancelled"):
        database.insert_preset_asset_candidate(
            "pose",
            preset_id,
            "ai",
            status,
            {},
        )

    response = client.get(
        "/api/preset-assets/catalog/query",
        params={
            "kind": "pose",
            "resource": "with-candidate",
            "candidate_status": "ready",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    target = payload["items"][0]["items"][0]
    assert target["preset_id"] == preset_id
    assert target["candidate_count"] == 4
    assert target["candidate_status_counts"]["ready"] == 1
    assert target["candidate_status_counts"]["running"] == 1
    assert target["candidate_status_counts"]["failed"] == 1
    assert target["candidate_status_counts"]["cancelled"] == 1
    assert target["candidate_status_counts"]["queued"] == 0

    invalid = client.get(
        "/api/preset-assets/catalog/query",
        params={"kind": "pose", "candidate_status": "unknown"},
    )
    assert invalid.status_code == 400


def test_catalog_query_combines_material_candidate_and_task_status(
    client, workshop
):
    preset = _preset("pose", restricted=False)
    preset_id = str(preset["id"])
    service.import_source(
        "pose",
        preset_id,
        _image_bytes("PNG", (96, 144)),
        mime_type="image/png",
    )
    database.insert_preset_asset_candidate(
        "pose",
        preset_id,
        "ai",
        "ready",
        {},
    )
    task_registry.register(
        pipeline.JOB_KIND,
        "catalog-combination",
        status="done",
        total=2,
    )
    database.insert_preset_asset_job_item(
        "catalog-combination",
        0,
        "pose",
        preset_id,
        "done",
        {"mode": "ai"},
    )
    database.insert_preset_asset_job_item(
        "catalog-combination",
        1,
        "pose",
        preset_id,
        "failed",
        {"mode": "ai"},
    )

    response = client.get(
        "/api/preset-assets/catalog/query",
        params={
            "kind": "pose",
            "resource": "with-source",
            "candidate_status": "ready",
            "task_status": "failed",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    target = payload["items"][0]["items"][0]
    assert target["preset_id"] == preset_id
    assert target["source"] is not None
    assert target["candidate_status_counts"]["ready"] == 1
    assert target["task_status_counts"]["done"] == 1
    assert target["task_status_counts"]["failed"] == 1

    mismatch = client.get(
        "/api/preset-assets/catalog/query",
        params={
            "kind": "pose",
            "resource": "with-source",
            "candidate_status": "failed",
            "task_status": "failed",
        },
    )
    assert mismatch.status_code == 200
    assert mismatch.json()["total"] == 0


def test_catalog_task_status_facets_and_pagination(client, workshop):
    first = _preset("pose", restricted=False)
    second = next(
        item
        for item in preset_registry.PRESET_KIND_BY_KEY["pose"].list_loader()
        if str(item["id"]) != str(first["id"])
        and not service.preset_is_restricted(item)
    )
    for job_id, preset in (
        ("catalog-page-a", first),
        ("catalog-page-b", second),
    ):
        database.insert_preset_asset_job_item(
            job_id,
            0,
            "pose",
            str(preset["id"]),
            "queued",
            {"mode": "ai"},
        )

    first_page = client.get(
        "/api/preset-assets/catalog/query",
        params={
            "kind": "pose",
            "task_status": "queued",
            "page": 1,
            "page_size": 1,
        },
    )
    second_page = client.get(
        "/api/preset-assets/catalog/query",
        params={
            "kind": "pose",
            "task_status": "queued",
            "page": 2,
            "page_size": 1,
        },
    )

    assert first_page.status_code == 200
    first_payload = first_page.json()
    second_payload = second_page.json()
    assert first_payload["total"] == 2
    assert first_payload["page"] == 1
    assert len(first_payload["items"][0]["items"]) == 1
    assert second_payload["page"] == 2
    assert len(second_payload["items"][0]["items"]) == 1
    assert (
        first_payload["items"][0]["items"][0]["preset_id"]
        != second_payload["items"][0]["items"][0]["preset_id"]
    )
    assert first_payload["facets"]["task_statuses"] == [
        {"value": "queued", "label": "排队中", "count": 2}
    ]

    invalid = client.get(
        "/api/preset-assets/catalog/query",
        params={"kind": "pose", "task_status": "unknown"},
    )
    assert invalid.status_code == 400


def test_job_list_filters_and_hides_restricted_payloads(
    client, workshop, monkeypatch
):
    allowed = _preset("pose", restricted=False)
    restricted = _preset("pose", restricted=True)

    def register_job(job_id: str, preset_id: str, status: str) -> None:
        task_registry.register(
            pipeline.JOB_KIND,
            job_id,
            status=status,
            total=1,
        )
        database.insert_preset_asset_job_item(
            job_id,
            0,
            "pose",
            preset_id,
            status,
            {
                "mode": "ai",
                "candidate_count": 1,
                "user_positive": f"secret-{job_id}",
            },
        )

    register_job("allowed-done", str(allowed["id"]), "done")
    register_job("allowed-error", str(allowed["id"]), "failed")
    register_job("restricted-done", str(restricted["id"]), "done")
    task_registry.register(
        pipeline.JOB_KIND,
        "mixed-hidden",
        status="running",
        total=2,
    )
    database.insert_preset_asset_job_item(
        "mixed-hidden",
        0,
        "pose",
        str(allowed["id"]),
        "done",
        {"mode": "ai", "user_positive": "secret-mixed-allowed"},
    )
    database.insert_preset_asset_job_item(
        "mixed-hidden",
        1,
        "pose",
        str(restricted["id"]),
        "running",
        {"mode": "ai", "user_positive": "secret-mixed-restricted"},
    )

    listed = client.get(
        "/api/preset-assets/jobs",
        params={"limit": 10},
    )
    assert listed.status_code == 200
    assert {item["job_id"] for item in listed.json()["items"]} == {
        "restricted-done",
        "mixed-hidden",
        "allowed-error",
        "allowed-done",
    }

    monkeypatch.setattr(
        preset_assets_router,
        "content_restriction_enabled",
        lambda: True,
    )
    restricted_list = client.get(
        "/api/preset-assets/jobs",
        params={"limit": 10},
    )
    assert restricted_list.status_code == 200
    assert {item["job_id"] for item in restricted_list.json()["items"]} == {
        "allowed-error",
        "allowed-done",
    }
    assert "secret-restricted-done" not in restricted_list.text
    assert "secret-mixed-allowed" not in restricted_list.text
    assert "secret-mixed-restricted" not in restricted_list.text
    assert "mixed-hidden" not in restricted_list.text

    filtered = client.get(
        "/api/preset-assets/jobs",
        params={"status": "done", "limit": 10},
    )
    assert filtered.status_code == 200
    assert {item["job_id"] for item in filtered.json()["items"]} == {
        "allowed-done"
    }


def test_ai_job_waits_for_external_gpu_and_finishes_with_mock(
    workshop, monkeypatch
):
    preset = _preset("pose", restricted=False)
    preset_id = str(preset["id"])
    release = threading.Event()
    generated_calls: list[dict] = []

    monkeypatch.setattr(
        task_registry,
        "running_tasks",
        lambda: [] if release.is_set() else [{"type": "draw", "job_id": "draw-busy"}],
    )

    def fake_generate(**kwargs):
        generated_calls.append(kwargs)
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "generated.png"
        Image.new("RGB", (832, 1216), (100, 130, 170)).save(path, "PNG")
        return {"saved_path": str(path), "seed": kwargs["seed"]}

    monkeypatch.setattr(comfy_worker, "generate", fake_generate)
    job = pipeline.create_job(
        [
            {
                "preset_type": "pose",
                "preset_id": preset_id,
                "mode": "ai",
                "params": {
                    "model": "mock.safetensors",
                    "candidate_count": 1,
                    "seed_strategy": "fixed",
                    "seed": 55,
                    "crop_mode": "cover",
                },
            }
        ]
    )

    def candidate_status() -> str:
        candidates = database.list_preset_asset_candidates_by_job(job["job_id"])
        return str(candidates[0]["status"]) if candidates else ""

    _wait_until(lambda: candidate_status() == "queued")
    assert generated_calls == []
    release.set()
    _wait_until(lambda: pipeline.job_status(job["job_id"])["status"] == "done")
    candidate = database.list_preset_asset_candidates_by_job(job["job_id"])[0]
    assert candidate["status"] == "ready"
    assert candidate["seed"] == 55
    assert len(generated_calls) == 1


def test_cancel_retry_and_interrupted_recovery(workshop, monkeypatch):
    monkeypatch.setattr(pipeline, "_interrupt_comfy", lambda: None)
    cancelled_id = "cancelled-job"
    task_registry.register(pipeline.JOB_KIND, cancelled_id, status="queued", total=1)
    database.insert_preset_asset_job_item(
        cancelled_id,
        0,
        "pose",
        _preset("pose", restricted=False)["id"],
        "queued",
        {"mode": "ai", "candidate_count": 1},
    )
    cancelled = pipeline.cancel_job(cancelled_id)
    assert cancelled["status"] == "cancel_requested"
    assert database.list_preset_asset_job_items(cancelled_id)[0]["status"] == "cancelled"

    retry_id = "retry-job"
    task_registry.register(pipeline.JOB_KIND, retry_id, status="error", total=1)
    database.insert_preset_asset_job_item(
        retry_id,
        0,
        "pose",
        _preset("pose", restricted=False)["id"],
        "failed",
        {"mode": "ai", "candidate_count": 1},
    )
    started: list[tuple[str, set[int] | None]] = []
    monkeypatch.setattr(
        pipeline,
        "_start_job_thread",
        lambda job_id, only_indexes=None: started.append((job_id, only_indexes)),
    )
    retried = pipeline.retry_failed_job(retry_id)
    assert retried["status"] == "queued"
    assert started == [(retry_id, {0})]
    assert database.list_preset_asset_job_items(retry_id)[0]["status"] == "queued"

    database.save_background_job(
        {
            "job_id": "interrupted-job",
            "kind": pipeline.JOB_KIND,
            "status": "running",
            "total": 1,
            "done": 0,
            "current": "",
            "error": None,
            "stop_requested": False,
            "payload": {},
            "created_at": database.now_iso(),
            "updated_at": database.now_iso(),
            "finished_at": None,
        }
    )
    database.insert_preset_asset_job_item(
        "interrupted-job",
        0,
        "pose",
        _preset("pose", restricted=False)["id"],
        "running",
        {"mode": "ai", "candidate_count": 1},
    )
    assert database.mark_interrupted_preset_asset_jobs() >= 1
    assert database.get_background_job("interrupted-job")["status"] == "interrupted"
    assert database.list_preset_asset_job_items("interrupted-job")[0]["status"] == "interrupted"


def test_create_job_reuses_same_idempotent_request(workshop, monkeypatch):
    preset_id = str(_preset("pose", restricted=False)["id"])
    started: list[tuple[str, set[int] | None]] = []
    monkeypatch.setattr(
        pipeline,
        "_start_job_thread",
        lambda job_id, only_indexes=None: started.append((job_id, only_indexes)),
    )
    items = [
        {
            "preset_type": "pose",
            "preset_id": preset_id,
            "mode": "ai",
            "params": {
                "model": "mock.safetensors",
                "candidate_count": 1,
            },
        }
    ]

    first = pipeline.create_job(items, idempotency_key="stable-request")
    second = pipeline.create_job(items, idempotency_key="stable-request")

    assert second["job_id"] == first["job_id"]
    assert started == [
        (first["job_id"], None),
        (first["job_id"], None),
    ]
    requests = (
        database.get_connection()
        .execute("SELECT * FROM preset_asset_job_requests")
        .fetchall()
    )
    assert len(requests) == 1
    assert requests[0]["job_id"] == first["job_id"]
    assert requests[0]["idempotency_key"] == "stable-request"
    assert len(database.list_preset_asset_job_items(first["job_id"])) == 1


def test_create_job_rejects_reused_key_for_different_request(workshop, monkeypatch):
    preset_id = str(_preset("pose", restricted=False)["id"])
    monkeypatch.setattr(pipeline, "_start_job_thread", lambda *_args, **_kwargs: None)

    def submit(candidate_count: int) -> dict:
        return pipeline.create_job(
            [
                {
                    "preset_type": "pose",
                    "preset_id": preset_id,
                    "mode": "ai",
                    "params": {
                        "model": "mock.safetensors",
                        "candidate_count": candidate_count,
                    },
                }
            ],
            idempotency_key="conflicting-request",
        )

    created = submit(1)
    with pytest.raises(service.PresetAssetError) as conflict:
        submit(2)

    assert conflict.value.status_code == 409
    jobs = database.list_background_jobs(kind=pipeline.JOB_KIND)
    assert [job["job_id"] for job in jobs] == [created["job_id"]]


def test_job_endpoints_forward_idempotency_headers(client, monkeypatch):
    preset_id = str(_preset("pose", restricted=False)["id"])
    monkeypatch.setattr(pipeline, "_start_job_thread", lambda *_args, **_kwargs: None)
    params = {
        "model": "mock.safetensors",
        "candidate_count": 1,
    }

    ai_response = client.post(
        f"/api/preset-assets/presets/pose/{preset_id}/candidates/ai",
        headers={"Idempotency-Key": "header-ai"},
        json={"params": params},
    )
    assert ai_response.status_code == 200
    ai_job_id = ai_response.json()["job_id"]
    repeated = client.post(
        f"/api/preset-assets/presets/pose/{preset_id}/candidates/ai",
        headers={"Idempotency-Key": "header-ai"},
        json={"params": params},
    )
    assert repeated.status_code == 200
    assert repeated.json()["job_id"] == ai_job_id

    batch_response = client.post(
        "/api/preset-assets/jobs",
        headers={"Idempotency-Key": "header-batch"},
        json={
            "items": [
                {
                    "preset_type": "pose",
                    "preset_id": preset_id,
                    "mode": "ai",
                    "params": params,
                }
            ]
        },
    )
    assert batch_response.status_code == 200
    assert batch_response.json()["job_id"] != ai_job_id

    requests = (
        database.get_connection()
        .execute(
            "SELECT idempotency_key FROM preset_asset_job_requests "
            "ORDER BY idempotency_key"
        )
        .fetchall()
    )
    assert [row["idempotency_key"] for row in requests] == [
        "header-ai",
        "header-batch",
    ]

    conflict = client.post(
        f"/api/preset-assets/presets/pose/{preset_id}/candidates/ai",
        headers={"Idempotency-Key": "header-ai"},
        json={"params": {**params, "candidate_count": 2}},
    )
    assert conflict.status_code == 409


def test_attempts_and_retry_backoff_are_recorded(workshop, monkeypatch):
    preset_id = str(_preset("pose", restricted=False)["id"])
    monkeypatch.setattr(pipeline, "_start_job_thread", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_wait_for_gpu_slot", lambda *_args: True)
    monkeypatch.setattr(pipeline, "_release_gpu_slot", lambda: None)

    def fail_generation(**_kwargs):
        raise TimeoutError("generation timed out")

    monkeypatch.setattr(comfy_worker, "generate", fail_generation)
    job = pipeline.create_job(
        [
            {
                "preset_type": "pose",
                "preset_id": preset_id,
                "mode": "ai",
                "params": {
                    "model": "mock.safetensors",
                    "candidate_count": 1,
                },
            }
        ]
    )
    job_id = job["job_id"]

    pipeline._run_job(job_id)
    first = database.list_preset_asset_job_items(job_id)[0]
    assert first["status"] == "failed"
    assert first["attempt_count"] == 1
    assert first["last_error_code"] == "generation_timeout"
    assert first["next_retry_at"]
    assert first["retry_backoff_seconds"] == 30

    database.update_preset_asset_job_item(
        job_id,
        0,
        status="queued",
    )
    pipeline._run_job(job_id)
    second = database.list_preset_asset_job_items(job_id)[0]
    assert second["status"] == "failed"
    assert second["attempt_count"] == 2
    assert second["last_error_code"] == "generation_timeout"
    assert second["next_retry_at"]
    assert second["retry_backoff_seconds"] == 60


def test_non_retryable_parameter_failure_has_no_backoff(workshop, monkeypatch):
    preset_id = str(_preset("pose", restricted=False)["id"])
    monkeypatch.setattr(pipeline, "_start_job_thread", lambda *_args, **_kwargs: None)

    def fail_parameters(*_args, **_kwargs):
        raise service.PresetAssetError("参数错误", status_code=400)

    monkeypatch.setattr(pipeline, "_process_ai_item", fail_parameters)
    job = pipeline.create_job(
        [
            {
                "preset_type": "pose",
                "preset_id": preset_id,
                "mode": "ai",
                "params": {
                    "model": "mock.safetensors",
                    "candidate_count": 1,
                },
            }
        ]
    )

    pipeline._run_job(job["job_id"])

    item = database.list_preset_asset_job_items(job["job_id"])[0]
    assert item["status"] == "failed"
    assert item["attempt_count"] == 1
    assert item["last_error_code"] == "invalid_parameters"
    assert item["next_retry_at"] is None
    assert item["retry_backoff_seconds"] == 0


@pytest.mark.parametrize(
    ("status", "failure_code", "retryable", "user_action"),
    [
        ("failed", "generation_timeout", True, "wait_and_retry"),
        ("failed", "generation_service_unavailable", True, "start_service"),
        ("failed", "gpu_busy", True, "free_gpu"),
        ("failed", "generation_failed", True, "retry"),
        ("failed", "invalid_parameters", False, "fix_parameters"),
        ("failed", "invalid_preset", False, "review_preset"),
        ("failed", "legacy_unknown", True, "retry"),
        ("interrupted", None, True, "retry"),
        ("cancelled", "cancelled", True, "retry"),
        ("done", None, False, "none"),
    ],
)
def test_job_status_exposes_stable_retry_contract(
    workshop,
    status,
    failure_code,
    retryable,
    user_action,
):
    job_id = f"retry-contract-{status}-{failure_code}"
    preset_id = str(_preset("pose", restricted=False)["id"])
    task_registry.register(pipeline.JOB_KIND, job_id, status=status, total=1)
    database.insert_preset_asset_job_item(
        job_id,
        0,
        "pose",
        preset_id,
        status,
        {"mode": "ai", "candidate_count": 1},
    )
    if failure_code:
        database.update_preset_asset_job_item(
            job_id,
            0,
            last_error_code=failure_code,
        )

    item = pipeline.job_status(job_id)["items"][0]

    assert item["retryable"] is retryable
    assert item["user_action"] == user_action


def test_job_status_summarizes_duplicate_preset_items_independently(workshop):
    job_id = "duplicate-preset-summary-job"
    preset_id = str(_preset("pose", restricted=False)["id"])
    task_registry.register(pipeline.JOB_KIND, job_id, status="done", total=3)
    for item_index, status, candidate_count in (
        (0, "done", 2),
        (1, "failed", 1),
    ):
        database.insert_preset_asset_job_item(
            job_id,
            item_index,
            "pose",
            preset_id,
            status,
            {"mode": "ai", "candidate_count": candidate_count},
        )
    ready_id = database.insert_preset_asset_candidate(
        "pose",
        preset_id,
        "ai",
        "ready",
        {
            "candidate_count": 2,
            service.CANDIDATE_JOB_ITEM_INDEX_PARAM: 0,
        },
        job_id=job_id,
    )
    adopted_id = database.insert_preset_asset_candidate(
        "pose",
        preset_id,
        "ai",
        "adopted",
        {
            "candidate_count": 2,
            service.CANDIDATE_JOB_ITEM_INDEX_PARAM: 0,
        },
        job_id=job_id,
    )
    failed_id = database.insert_preset_asset_candidate(
        "pose",
        preset_id,
        "ai",
        "failed",
        {
            "candidate_count": 1,
            service.CANDIDATE_JOB_ITEM_INDEX_PARAM: 1,
        },
        job_id=job_id,
    )
    database.update_preset_asset_job_item(
        job_id,
        0,
        candidate_id=adopted_id,
    )
    database.update_preset_asset_job_item(
        job_id,
        1,
        candidate_id=failed_id,
    )
    version_id = database.insert_preset_asset_version(
        "pose",
        preset_id,
        1,
        ready_id,
        "public/pose.webp",
        "dist/pose.webp",
        "image/webp",
        512,
        768,
        "sha256",
        True,
    )

    status = pipeline.job_status(job_id)
    first, second = status["items"]

    assert first["candidate_count"] == 2
    assert first["ready_count"] == 1
    assert first["adopted_count"] == 1
    assert first["active_count"] == 0
    assert first["failed_count"] == 0
    assert first["cancelled_count"] == 0
    assert second["candidate_count"] == 1
    assert second["ready_count"] == 0
    assert second["adopted_count"] == 0
    assert second["active_count"] == 0
    assert second["failed_count"] == 1
    assert second["cancelled_count"] == 0
    assert first["candidate_summary_reliable"] is True
    assert second["candidate_summary_reliable"] is True
    assert first["candidate_summary_source"] == "job_item"
    assert first["active_version"]["id"] == version_id
    assert "public_path" not in first["active_version"]
    assert "dist_path" not in first["active_version"]
    assert all(
        service.CANDIDATE_JOB_ITEM_INDEX_PARAM not in candidate["params"]
        for candidate in status["candidates"]
    )


def test_job_status_uses_unique_legacy_candidate_anchors(workshop):
    job_id = "legacy-anchor-summary-job"
    preset_id = str(_preset("pose", restricted=False)["id"])
    task_registry.register(pipeline.JOB_KIND, job_id, status="done", total=2)
    for item_index in (0, 1):
        database.insert_preset_asset_job_item(
            job_id,
            item_index,
            "pose",
            preset_id,
            "done",
            {"mode": "ai", "candidate_count": 1},
        )
    candidate_ids = [
        database.insert_preset_asset_candidate(
            "pose",
            preset_id,
            "ai",
            "ready",
            {"candidate_count": 1},
            job_id=job_id,
        )
        for _ in range(2)
    ]
    for item_index, candidate_id in enumerate(candidate_ids):
        database.update_preset_asset_job_item(
            job_id,
            item_index,
            candidate_id=candidate_id,
        )

    status = pipeline.job_status(job_id)

    assert [item["candidate_count"] for item in status["items"]] == [1, 1]
    assert all(
        item["candidate_summary_reliable"] is True
        for item in status["items"]
    )


def test_job_status_flags_ambiguous_legacy_duplicate_candidates(workshop):
    job_id = "legacy-ambiguous-summary-job"
    preset_id = str(_preset("pose", restricted=False)["id"])
    task_registry.register(pipeline.JOB_KIND, job_id, status="done", total=2)
    for item_index in (0, 1):
        database.insert_preset_asset_job_item(
            job_id,
            item_index,
            "pose",
            preset_id,
            "done",
            {"mode": "ai", "candidate_count": 1},
        )
    for candidate_status in ("ready", "failed"):
        database.insert_preset_asset_candidate(
            "pose",
            preset_id,
            "ai",
            candidate_status,
            {"candidate_count": 1},
            job_id=job_id,
        )

    status = pipeline.job_status(job_id)

    assert all(
        item["candidate_summary_reliable"] is False
        for item in status["items"]
    )
    assert all(
        item["candidate_summary_source"] == "legacy_preset_fallback"
        for item in status["items"]
    )


def test_retry_selected_item_rejects_non_retryable_failure_code(
    workshop,
    monkeypatch,
):
    job_id = "selected-item-invalid-parameters-job"
    preset_id = str(_preset("pose", restricted=False)["id"])
    task_registry.register(pipeline.JOB_KIND, job_id, status="error", total=1)
    database.insert_preset_asset_job_item(
        job_id,
        0,
        "pose",
        preset_id,
        "failed",
        {"mode": "ai", "candidate_count": 1},
        error="参数错误",
    )
    database.update_preset_asset_job_item(
        job_id,
        0,
        last_error_code="invalid_parameters",
    )
    started: list[tuple[str, set[int] | None]] = []
    monkeypatch.setattr(
        pipeline,
        "_start_job_thread",
        lambda retry_job_id, only_indexes=None: started.append(
            (retry_job_id, only_indexes)
        ),
    )

    with pytest.raises(service.PresetAssetError) as invalid:
        pipeline.retry_failed_job(job_id, {0})

    assert invalid.value.status_code == 409
    assert started == []
    assert database.get_preset_asset_job_item(job_id, 0)["status"] == "failed"


def test_retry_whole_job_skips_non_retryable_failure_codes(
    workshop,
    monkeypatch,
):
    job_id = "mixed-retryable-failure-job"
    preset_id = str(_preset("pose", restricted=False)["id"])
    task_registry.register(pipeline.JOB_KIND, job_id, status="error", total=2)
    for item_index, failure_code in enumerate(
        ("generation_timeout", "invalid_parameters")
    ):
        database.insert_preset_asset_job_item(
            job_id,
            item_index,
            "pose",
            preset_id,
            "failed",
            {"mode": "ai", "candidate_count": 1},
            error=failure_code,
        )
        database.update_preset_asset_job_item(
            job_id,
            item_index,
            last_error_code=failure_code,
        )
    started: list[tuple[str, set[int] | None]] = []
    monkeypatch.setattr(
        pipeline,
        "_start_job_thread",
        lambda retry_job_id, only_indexes=None: started.append(
            (retry_job_id, only_indexes)
        ),
    )

    retried = pipeline.retry_failed_job(job_id)

    assert retried["status"] == "queued"
    assert started == [(job_id, {0})]
    assert [
        item["status"]
        for item in database.list_preset_asset_job_items(job_id)
    ] == ["queued", "failed"]


def test_restore_pending_jobs_resumes_queued_and_cleans_interrupted_running(
    workshop,
    monkeypatch,
):
    preset_id = str(_preset("pose", restricted=False)["id"])
    started: list[tuple[str, set[int] | None]] = []
    monkeypatch.setattr(
        pipeline,
        "_start_job_thread",
        lambda job_id, only_indexes=None: started.append((job_id, only_indexes)),
    )
    timestamp = database.now_iso()

    queued_job_id = "restore-queued"
    database.save_background_job(
        {
            "job_id": queued_job_id,
            "kind": pipeline.JOB_KIND,
            "status": "queued",
            "total": 1,
            "done": 0,
            "current": "",
            "error": None,
            "stop_requested": False,
            "payload": {},
            "created_at": timestamp,
            "updated_at": timestamp,
            "finished_at": None,
        }
    )
    database.insert_preset_asset_job_item(
        queued_job_id,
        0,
        "pose",
        preset_id,
        "queued",
        {"mode": "ai", "candidate_count": 1},
    )

    interrupted_job_id = "restore-running"
    database.save_background_job(
        {
            "job_id": interrupted_job_id,
            "kind": pipeline.JOB_KIND,
            "status": "running",
            "total": 1,
            "done": 0,
            "current": "",
            "error": None,
            "stop_requested": False,
            "payload": {},
            "created_at": timestamp,
            "updated_at": timestamp,
            "finished_at": None,
        }
    )
    database.insert_preset_asset_job_item(
        interrupted_job_id,
        0,
        "pose",
        preset_id,
        "running",
        {"mode": "ai", "candidate_count": 1},
    )
    candidate_id = database.insert_preset_asset_candidate(
        "pose",
        preset_id,
        "ai",
        "running",
        {},
        job_id=interrupted_job_id,
    )

    task_registry.restore_interrupted()
    assert pipeline.restore_pending_jobs() >= 2

    queued_item = database.list_preset_asset_job_items(queued_job_id)[0]
    assert queued_item["status"] == "queued"
    assert task_registry.get(pipeline.JOB_KIND, queued_job_id)["status"] == "queued"
    assert (queued_job_id, {0}) in started

    interrupted_item = database.list_preset_asset_job_items(
        interrupted_job_id
    )[0]
    assert interrupted_item["status"] == "interrupted"
    assert (
        database.get_preset_asset_candidate(candidate_id)["status"]
        == "interrupted"
    )
    assert task_registry.get(
        pipeline.JOB_KIND, interrupted_job_id
    )["status"] == "interrupted"
    assert all(job_id != interrupted_job_id for job_id, _indexes in started)


def test_retry_rejects_job_with_active_items(workshop, monkeypatch):
    job_id = "active-retry-job"
    preset_id = _preset("pose", restricted=False)["id"]
    task_registry.register(pipeline.JOB_KIND, job_id, status="running", total=2)
    params = {"mode": "ai", "candidate_count": 1}
    database.insert_preset_asset_job_item(
        job_id, 0, "pose", preset_id, "failed", params
    )
    database.insert_preset_asset_job_item(
        job_id, 1, "pose", preset_id, "running", params
    )
    started: list[tuple[str, set[int] | None]] = []
    monkeypatch.setattr(
        pipeline,
        "_start_job_thread",
        lambda retry_job_id, only_indexes=None: started.append(
            (retry_job_id, only_indexes)
        ),
    )

    with pytest.raises(service.PresetAssetError) as active:
        pipeline.retry_failed_job(job_id)

    assert active.value.status_code == 409
    assert started == []
    assert task_registry.get(pipeline.JOB_KIND, job_id)["status"] == "running"
    assert [
        item["status"] for item in database.list_preset_asset_job_items(job_id)
    ] == ["failed", "running"]


def test_retry_selected_item_only_resets_that_item(workshop, monkeypatch):
    job_id = "selected-item-retry-job"
    preset_id = _preset("pose", restricted=False)["id"]
    task_registry.register(pipeline.JOB_KIND, job_id, status="error", total=3)
    params = {"mode": "ai", "candidate_count": 1}
    database.insert_preset_asset_job_item(
        job_id,
        0,
        "pose",
        preset_id,
        "failed",
        params,
        error="first failed",
    )
    database.insert_preset_asset_job_item(
        job_id,
        1,
        "pose",
        preset_id,
        "failed",
        params,
        candidate_id=99,
        error="second failed",
    )
    database.insert_preset_asset_job_item(
        job_id,
        2,
        "pose",
        preset_id,
        "done",
        params,
        candidate_id=100,
    )
    started: list[tuple[str, set[int] | None]] = []
    monkeypatch.setattr(
        pipeline,
        "_start_job_thread",
        lambda retry_job_id, only_indexes=None: started.append(
            (retry_job_id, only_indexes)
        ),
    )

    retried = pipeline.retry_failed_job(job_id, {1})

    assert retried["status"] == "queued"
    assert retried["done"] == 1
    assert started == [(job_id, {1})]
    items = database.list_preset_asset_job_items(job_id)
    assert [item["status"] for item in items] == ["failed", "queued", "done"]
    assert items[0]["error"] == "first failed"
    assert items[0]["candidate_id"] is None
    assert items[1]["error"] is None
    assert items[1]["candidate_id"] is None
    assert items[2]["candidate_id"] == 100


def test_retry_selected_item_rejects_non_recoverable_item(workshop, monkeypatch):
    job_id = "selected-item-invalid-job"
    preset_id = _preset("pose", restricted=False)["id"]
    task_registry.register(pipeline.JOB_KIND, job_id, status="done", total=1)
    database.insert_preset_asset_job_item(
        job_id,
        0,
        "pose",
        preset_id,
        "done",
        {"mode": "ai", "candidate_count": 1},
        candidate_id=123,
    )
    started: list[tuple[str, set[int] | None]] = []
    monkeypatch.setattr(
        pipeline,
        "_start_job_thread",
        lambda retry_job_id, only_indexes=None: started.append(
            (retry_job_id, only_indexes)
        ),
    )

    with pytest.raises(service.PresetAssetError) as invalid:
        pipeline.retry_failed_job(job_id, {0})

    assert invalid.value.status_code == 409
    assert started == []
    item = database.list_preset_asset_job_items(job_id)[0]
    assert item["status"] == "done"
    assert item["candidate_id"] == 123
