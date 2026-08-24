"""Build and submit Anima text-to-image workflows to ComfyUI."""
from __future__ import annotations

import random
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

LORAS_DIR = Path(r"D:\AI\ComfyUI\models\loras")
MODELS_DIR = Path(r"D:\AI\ComfyUI\models\diffusion_models")
AI_PRODUCT_DIR = Path(r"D:\workSpace\code\骑手招聘助手\AIproduct")
COMFY_URL = "http://127.0.0.1:8188"
DEFAULT_MODEL = "chosenMixAnima_v10.safetensors"
CLIP_NAME = "qwen_3_06b_base.safetensors"
VAE_NAME = "qwen_image_vae.safetensors"

WLR_RE = re.compile(r"<wlr:([^:>]+)(?::([0-9.]+))?(?::([0-9.]+))?(?::([0-9.]+))?>")


def list_loras() -> list[dict]:
    files: list[dict] = []
    if LORAS_DIR.exists():
        for path in sorted(LORAS_DIR.glob("*.safetensors")):
            files.append({"name": path.name, "size_mb": round(path.stat().st_size / 1024 / 1024, 1)})
    return files


def list_diffusion_models() -> list[dict]:
    """列出 ComfyUI diffusion_models 目录下的可用底模。"""
    files: list[dict] = []
    if MODELS_DIR.exists():
        for path in sorted(MODELS_DIR.glob("*.safetensors")):
            files.append({"name": path.name, "size_mb": round(path.stat().st_size / 1024 / 1024, 1)})
    return files


def _clean_wlr_tags(text: str) -> tuple[str, list[tuple[str, str, str, str]]]:
    tags = WLR_RE.findall(text)
    cleaned = WLR_RE.sub("", text)
    return cleaned, tags


def build_workflow(
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    loras: list[str] | None = None,
    seed: int | None = None,
    model_name: str = DEFAULT_MODEL,
) -> tuple[dict, int]:
    graph: dict = {}
    graph["1"] = {"class_type": "UNETLoader", "inputs": {"unet_name": model_name, "weight_dtype": "default"}}
    graph["2"] = {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP_NAME, "type": "stable_diffusion", "device": "default"}}
    graph["3"] = {"class_type": "VAELoader", "inputs": {"vae_name": VAE_NAME}}

    model_src = "1"
    cleaned, prompt_loras = _clean_wlr_tags(prompt)
    selected: dict[str, dict] = {}
    for name in loras or []:
        fname = name if name.endswith(".safetensors") else name + ".safetensors"
        selected.setdefault(fname, {"strength_model": 0.8, "strength_clip": 0.8})
    for stem, model_w, clip_w, _trigger_w in prompt_loras:
        fname = stem if stem.endswith(".safetensors") else stem + ".safetensors"
        entry = selected.setdefault(fname, {"strength_model": 0.8, "strength_clip": 0.8})
        if model_w:
            entry["strength_model"] = float(model_w)
        if clip_w:
            entry["strength_clip"] = float(clip_w)

    node_id = 4
    for fname, strengths in selected.items():
        if not (LORAS_DIR / fname).exists():
            continue
        graph[str(node_id)] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": [model_src, 0],
                "lora_name": fname,
                "strength_model": strengths["strength_model"],
                "strength_clip": strengths["strength_clip"],
            },
        }
        model_src = str(node_id)
        node_id += 1

    pos_id = str(node_id)
    node_id += 1
    neg_id = str(node_id)
    node_id += 1
    lat_id = str(node_id)
    node_id += 1
    sample_id = str(node_id)
    node_id += 1
    decode_id = str(node_id)
    node_id += 1
    save_id = str(node_id)
    node_id += 1

    graph[pos_id] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": cleaned.strip()}}
    graph[neg_id] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative_prompt.strip()}}
    graph[lat_id] = {"class_type": "EmptyLatentImage", "inputs": {"width": int(width), "height": int(height), "batch_size": 1}}
    if seed is None:
        seed = random.randint(0, 2**63 - 1)
    graph[sample_id] = {
        "class_type": "KSampler",
        "inputs": {
            "model": [model_src, 0],
            "positive": [pos_id, 0],
            "negative": [neg_id, 0],
            "latent_image": [lat_id, 0],
            "seed": seed,
            "steps": int(steps),
            "cfg": float(cfg),
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": 1.0,
        },
    }
    graph[decode_id] = {"class_type": "VAEDecode", "inputs": {"samples": [sample_id, 0], "vae": ["3", 0]}}
    graph[save_id] = {"class_type": "SaveImage", "inputs": {"images": [decode_id, 0], "filename_prefix": "studio/anima"}}
    return graph, seed


def generate(
    prompt: str,
    negative_prompt: str,
    width: int = 1080,
    height: int = 1920,
    steps: int = 18,
    cfg: float = 1.0,
    loras: list[str] | None = None,
    timeout: int = 300,
    model_name: str = DEFAULT_MODEL,
) -> dict:
    graph, seed = build_workflow(prompt, negative_prompt, width, height, steps, cfg, loras, model_name=model_name)
    client_id = uuid.uuid4().hex
    start = time.time()
    response = requests.post(COMFY_URL + "/prompt", json={"prompt": graph, "client_id": client_id}, timeout=30)
    response.raise_for_status()
    prompt_id = response.json()["prompt_id"]

    deadline = time.time() + timeout
    while time.time() < deadline:
        history = requests.get(COMFY_URL + f"/history/{prompt_id}", timeout=10).json()
        if prompt_id in history:
            entry = history[prompt_id]
            if entry.get("status", {}).get("completed") or entry.get("outputs"):
                for node_out in entry.get("outputs", {}).values():
                    images = node_out.get("images", [])
                    if images:
                        image = images[0]
                        query = (
                            f"filename={image['filename']}&subfolder={image.get('subfolder', '')}&type={image.get('type', 'output')}"
                        )
                        comfy_url = f"http://127.0.0.1:8188/view?{query}"
                        saved_path = None
                        image_url = comfy_url
                        try:
                            AI_PRODUCT_DIR.mkdir(parents=True, exist_ok=True)
                            image_response = requests.get(comfy_url, timeout=30)
                            image_response.raise_for_status()
                            filename = f"anima_{datetime.now():%Y%m%d_%H%M%S}_{str(seed)[-8:]}.png"
                            target = AI_PRODUCT_DIR / filename
                            target.write_bytes(image_response.content)
                            saved_path = str(target)
                            image_url = f"/api/images/{filename}"
                        except Exception:
                            pass
                        return {
                            "prompt_id": prompt_id,
                            "image_url": image_url,
                            "comfy_url": comfy_url,
                            "saved_path": saved_path,
                            "seed": seed,
                            "elapsed": round(time.time() - start, 1),
                        }
            if entry.get("status", {}).get("status_str") == "error":
                raise RuntimeError(str(entry.get("status", {}).get("messages", entry)))
        time.sleep(1)
    raise TimeoutError("ComfyUI generation timeout")
