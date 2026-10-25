"""Local inpaint API: upload, job lifecycle, and lineage."""
from __future__ import annotations

import base64
import io
import json
import time

from PIL import Image, ImageDraw

import config
import app  # noqa: F401  # app adds the workspace agent/rag paths before routers import
import comfy_worker
import task_registry
import task_resources
from routers import draw as draw_router


def _png_bytes(size=(128, 96), color=(20, 40, 60)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _mask_b64(size=(128, 96)) -> str:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((32, 24, 96, 72), fill=255)
    buffer = io.BytesIO()
    mask.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _patch_inpaint_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(draw_router, "INPAINT_SOURCE_DIR", tmp_path / "sources")
    monkeypatch.setattr(draw_router, "INPAINT_MASK_DIR", tmp_path / "masks")
    monkeypatch.setattr(draw_router, "AI_PRODUCT_DIR", tmp_path / "AIproduct")
    monkeypatch.setattr(config, "COMFY_INPUT_DIR", tmp_path / "comfy_input")


def test_inpaint_source_upload_and_preview(client, tmp_path, monkeypatch) -> None:
    _patch_inpaint_paths(tmp_path, monkeypatch)
    response = client.post(
        "/api/draw/inpaint/sources",
        files={"file": ("source.png", _png_bytes(), "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source_id"].startswith("src_")
    assert body["working_width"] == 128
    assert body["working_height"] == 96

    preview = client.get(body["preview_url"])
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/png")


def test_inpaint_job_records_lineage(client, tmp_path, monkeypatch) -> None:
    _patch_inpaint_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(draw_router, "_validate_model", lambda model: "test.safetensors")
    monkeypatch.setattr(draw_router, "_validate_lora_compatibility", lambda loras: None)
    monkeypatch.setattr(
        draw_router,
        "generate_inpaint",
        lambda **kwargs: {
            "saved_path": str(tmp_path / "candidate.png"),
            "image_url": "/api/images/candidate.png",
            "seed": kwargs["seed"],
            "elapsed": 1.2,
            "prompt_id": "prompt-1",
        },
    )
    source = client.post(
        "/api/draw/inpaint/sources",
        files={"file": ("source.png", _png_bytes(), "image/png")},
    ).json()
    payload = {
        "source_id": source["source_id"],
        "mask_base64": _mask_b64(),
        "prompt": "a portrait",
        "negative_prompt": "lowres",
        "masked_prompt": "red hat",
        "count": 1,
        "seed": 100,
        "model": "test.safetensors",
        "steps": 18,
        "cfg": 1.0,
        "denoise": 0.75,
        "grow": 12,
        "feather": 8,
    }
    created = client.post("/api/draw/inpaint/jobs", json=payload)
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    try:
        for _ in range(200):
            status = client.get(f"/api/draw/inpaint/jobs/{job_id}").json()
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.05)
        assert status["status"] == "succeeded"
        assert status["progress"] == {"completed": 1, "total": 1}
        assert status["results"][0]["seed"] == 100
        record_id = status["results"][0]["record_id"]

        import database

        record = database.get_draw_image(record_id)
        assert record["edit_mode"] == "inpaint"
        assert record["masked_prompt"] == "red hat"
        assert record["inpaint_denoise"] == 0.75
        assert record["source_image_path"].endswith(".png")
        assert record["mask_image_path"].endswith("_mask.png")
        assert json.loads(record["edit_params_json"])["source_id"] == source["source_id"]
    finally:
        draw_router.INPAINT_JOBS.pop(job_id, None)


def test_inpaint_rejects_mask_with_wrong_size(client, tmp_path, monkeypatch) -> None:
    _patch_inpaint_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(draw_router, "_validate_model", lambda model: "test.safetensors")
    monkeypatch.setattr(draw_router, "_validate_lora_compatibility", lambda loras: None)
    source = client.post(
        "/api/draw/inpaint/sources",
        files={"file": ("source.png", _png_bytes(), "image/png")},
    ).json()
    response = client.post(
        "/api/draw/inpaint/jobs",
        json={
            "source_id": source["source_id"],
            "mask_base64": _mask_b64((64, 64)),
            "prompt": "a portrait",
            "negative_prompt": "lowres",
            "model": "test.safetensors",
        },
    )
    assert response.status_code == 400
    assert "mask 尺寸" in response.json()["detail"]


def test_inpaint_cancel_stops_running_candidate(client, tmp_path, monkeypatch) -> None:
    _patch_inpaint_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(draw_router, "_validate_model", lambda model: "test.safetensors")
    monkeypatch.setattr(draw_router, "_validate_lora_compatibility", lambda loras: None)

    def fake_generate(**kwargs):
        kwargs["cancel_event"].wait(2)
        raise comfy_worker.GenerationCancelled("cancelled")

    monkeypatch.setattr(draw_router, "generate_inpaint", fake_generate)
    source = client.post(
        "/api/draw/inpaint/sources",
        files={"file": ("source.png", _png_bytes(), "image/png")},
    ).json()
    created = client.post(
        "/api/draw/inpaint/jobs",
        json={
            "source_id": source["source_id"],
            "mask_base64": _mask_b64(),
            "prompt": "a portrait",
            "negative_prompt": "lowres",
            "model": "test.safetensors",
            "count": 1,
        },
    ).json()
    job_id = created["job_id"]
    try:
        cancelled = client.post(f"/api/draw/inpaint/jobs/{job_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        for _ in range(100):
            status = client.get(f"/api/draw/inpaint/jobs/{job_id}").json()
            if status["status"] == "cancelled" and status["finished_at"]:
                break
            time.sleep(0.05)
        assert status["status"] == "cancelled"
        assert status["error"]["code"] == "CANCELLED"
    finally:
        draw_router.INPAINT_JOBS.pop(job_id, None)


def test_inpaint_accepts_an_existing_image_record_as_source(client, tmp_path, monkeypatch) -> None:
    _patch_inpaint_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(draw_router, "_validate_model", lambda model: "test.safetensors")
    monkeypatch.setattr(draw_router, "_validate_lora_compatibility", lambda loras: None)
    monkeypatch.setattr(
        draw_router,
        "generate_inpaint",
        lambda **kwargs: {
            "saved_path": str(tmp_path / "candidate.png"),
            "image_url": "/api/images/candidate.png",
            "seed": kwargs["seed"],
            "elapsed": 0.1,
            "prompt_id": "prompt-2",
        },
    )

    import database

    product_dir = tmp_path / "AIproduct"
    product_dir.mkdir()
    source_path = product_dir / "library-source.png"
    source_path.write_bytes(_png_bytes())
    record_id = database.insert_draw_start(
        "library source",
        "",
        "",
        "",
        128,
        96,
        18,
        1.0,
        "test.safetensors",
        lora_anima_turbo=False,
        lora_high_contrast=False,
    )
    database.finish_draw(
        record_id,
        0.1,
        str(source_path),
        "/api/images/library-source.png",
        1,
        "success",
    )

    created = client.post(
        "/api/draw/inpaint/jobs",
        json={
            "source_record_id": record_id,
            "mask_base64": _mask_b64(),
            "prompt": "a portrait",
            "negative_prompt": "lowres",
            "model": "test.safetensors",
            "count": 1,
            "seed": 10,
        },
    )
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    try:
        for _ in range(200):
            status = client.get(f"/api/draw/inpaint/jobs/{job_id}").json()
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.05)
        assert status["status"] == "succeeded"
        result_id = status["results"][0]["record_id"]
        result = database.get_draw_image(result_id)
        assert result["source_record_id"] == record_id
    finally:
        draw_router.INPAINT_JOBS.pop(job_id, None)


def test_inpaint_failure_marks_task_error_and_releases_resources(
    client, tmp_path, monkeypatch
) -> None:
    _patch_inpaint_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(draw_router, "_validate_model", lambda model: "test.safetensors")
    monkeypatch.setattr(draw_router, "_validate_lora_compatibility", lambda loras: None)

    def fail_generate(**kwargs):
        raise RuntimeError("synthetic ComfyUI failure")

    monkeypatch.setattr(draw_router, "generate_inpaint", fail_generate)
    source = client.post(
        "/api/draw/inpaint/sources",
        files={"file": ("source.png", _png_bytes(), "image/png")},
    ).json()
    created = client.post(
        "/api/draw/inpaint/jobs",
        json={
            "source_id": source["source_id"],
            "mask_base64": _mask_b64(),
            "prompt": "a portrait",
            "negative_prompt": "lowres",
            "model": "test.safetensors",
            "count": 1,
        },
    ).json()
    job_id = created["job_id"]
    try:
        for _ in range(200):
            status = client.get(f"/api/draw/inpaint/jobs/{job_id}").json()
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.05)
        assert status["status"] == "failed"
        assert "synthetic ComfyUI failure" in status["error"]["message"]
        assert task_registry.get("draw", job_id)["status"] == "error"
        assert task_resources.list_job_claims(job_id, active_only=True) == []
    finally:
        draw_router.INPAINT_JOBS.pop(job_id, None)
