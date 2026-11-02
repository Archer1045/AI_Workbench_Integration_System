from __future__ import annotations

import generation_specs
import config


def test_anima_dimensions_are_snapped_without_changing_current_default() -> None:
    width, height, profile = generation_specs.normalize_size(
        "chosenIrisesMix_v20Anima.safetensors",
        1080,
        1920,
    )
    assert profile.id == "anima"
    assert (width, height) == (1080, 1920)

    width, height, _ = generation_specs.normalize_size(
        "chosenIrisesMix_v20Anima.safetensors",
        1083,
        1917,
        "9:16",
    )
    assert (width, height) == (1080, 1920)


def test_fixed_ratio_uses_the_current_long_edge() -> None:
    width, height, _ = generation_specs.normalize_size(
        "chosenIrisesMix_v20Anima.safetensors",
        1080,
        1920,
        "16:9",
    )
    assert (width, height) == (1920, 1080)


def test_known_but_unsupported_models_are_rejected_for_current_workflow() -> None:
    profile = generation_specs.resolve_profile("flux2-dev.safetensors")
    assert profile.id == "flux2"
    assert profile.workflow_supported is False
    try:
        generation_specs.require_workflow_supported("flux2-dev.safetensors")
    except generation_specs.GenerationSpecError as exc:
        assert "FLUX" in str(exc)
    else:
        raise AssertionError("FLUX must not silently use the Anima workflow")


def test_canvas_presets_obey_model_alignment() -> None:
    profile = generation_specs.resolve_profile(config.DRAW_DEFAULT_MODEL)
    presets = generation_specs.canvas_presets(
        profile,
        min_size=config.DRAW_WIDTH_MIN,
        max_size=config.DRAW_WIDTH_MAX,
    )
    assert {item["id"] for item in presets} == {
        "1:1",
        "4:3",
        "3:4",
        "16:9",
        "9:16",
        "21:9",
        "2:3",
        "3:2",
    }
    for item in presets:
        assert item["width"] % profile.resolution_step == 0
        assert item["height"] % profile.resolution_step == 0


def test_models_api_exposes_capability_metadata(client, monkeypatch) -> None:
    from routers import draw

    monkeypatch.setattr(
        draw,
        "list_diffusion_models",
        lambda: [{"name": config.DRAW_DEFAULT_MODEL, "size_mb": 1.0}],
    )
    response = client.get("/api/models")
    assert response.status_code == 200
    body = response.json()
    assert body["default"] == config.DRAW_DEFAULT_MODEL
    model = body["models"][0]
    assert model["generation_profile"] == "anima"
    assert model["workflow_supported"] is True
    assert model["spec"]["resolution_step"] == 8
    assert len(model["spec"]["canvas_presets"]) == 8


def test_draw_settings_apply_model_specific_size_rules(client) -> None:
    from routers import draw

    settings = draw._parse_draw_settings(
        {
            "width": 1083,
            "height": 1917,
            "aspect_ratio": "16:9",
            "steps": 18,
            "cfg": 1,
        },
        config.DRAW_DEFAULT_MODEL,
    )
    assert settings["width"] == 1920
    assert settings["height"] == 1080
    assert settings["generation_profile"] == "anima"
    assert settings["aspect_ratio"] == "16:9"
