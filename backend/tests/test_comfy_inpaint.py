"""Reference-image inpaint workflow contracts."""
from __future__ import annotations

import comfy_worker


def test_inpaint_workflow_uses_reference_image_and_composite() -> None:
    graph, seed = comfy_worker.build_inpaint_workflow(
        source_image="source.png",
        mask_image="mask.png",
        prompt="a portrait",
        negative_prompt="lowres",
        masked_prompt="red lace dress",
        seed=42,
    )

    assert seed == 42
    assert graph["4"]["class_type"] == "LoadImage"
    assert graph["4"]["inputs"]["image"] == "source.png"
    assert graph["5"]["inputs"]["image"] == "mask.png"
    assert graph["9"]["class_type"] == "VAEEncode"
    assert graph["16"]["class_type"] == "SetLatentNoiseMask"
    assert graph["16"]["inputs"]["mask"] == ["8", 0]
    assert graph["12"]["inputs"]["latent_image"] == ["16", 0]
    assert graph["10"]["inputs"]["text"] == "a portrait, red lace dress"
    assert graph["14"]["class_type"] == "ImageCompositeMasked"
    assert graph["14"]["inputs"]["destination"] == ["4", 0]
    assert graph["14"]["inputs"]["mask"] == ["8", 0]


def test_inpaint_workflow_clamps_denoise_and_mask_parameters() -> None:
    graph, _ = comfy_worker.build_inpaint_workflow(
        source_image="source.png",
        mask_image="mask.png",
        prompt="a portrait",
        negative_prompt="",
        denoise=0.1,
        grow=999,
        feather=-5,
    )

    assert graph["12"]["inputs"]["denoise"] == 0.2
    assert graph["7"]["inputs"]["expand"] == 64
    assert graph["8"]["inputs"]["left"] == 0


def test_inpaint_workflow_applies_lora_to_model_and_clip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(comfy_worker, "LORAS_DIR", tmp_path)
    (tmp_path / "style.safetensors").write_bytes(b"lora")

    graph, _ = comfy_worker.build_inpaint_workflow(
        source_image="source.png",
        mask_image="mask.png",
        prompt="a portrait",
        negative_prompt="",
        loras=["style"],
        lora_strengths={"style.safetensors": {"model": 0.5, "clip": 0.4}},
    )

    lora_nodes = [node for node in graph.values() if node["class_type"] == "LoraLoader"]
    assert len(lora_nodes) == 1
    assert lora_nodes[0]["inputs"]["strength_model"] == 0.5
    assert lora_nodes[0]["inputs"]["strength_clip"] == 0.4
    assert graph["10"]["inputs"]["clip"] == ["17", 1]
    assert graph["12"]["inputs"]["model"] == ["17", 0]
