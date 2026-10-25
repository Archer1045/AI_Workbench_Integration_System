"""Build and submit Anima text-to-image workflows to ComfyUI."""
from __future__ import annotations

import json
import random
import re
import struct
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

import config

LORAS_DIR = config.LORAS_DIR
MODELS_DIR = config.MODELS_DIR
AI_PRODUCT_DIR = config.AI_PRODUCT_DIR
COMFY_URL = config.COMFY_URL
DEFAULT_MODEL = config.DRAW_DEFAULT_MODEL
CLIP_NAME = config.CLIP_NAME
VAE_NAME = config.VAE_NAME

WLR_RE = re.compile(r"<wlr:([^:>]+)(?::([0-9.]+))?(?::([0-9.]+))?(?::([0-9.]+))?>")


class GenerationCancelled(RuntimeError):
    """Raised when an inpaint job is cancelled while ComfyUI is running."""


def _read_safetensors_header(path: Path) -> tuple[dict, list[str]]:
    """只读取 safetensors 头部，避免把整个权重载入内存。"""
    try:
        with path.open("rb") as handle:
            length = struct.unpack("<Q", handle.read(8))[0]
            header = json.loads(handle.read(length).decode("utf-8", errors="replace"))
        metadata = header.get("__metadata__") or {}
        keys = [key for key in header if key != "__metadata__"]
        return metadata, keys
    except Exception:
        return {}, []


def classify_lora_purpose(
    name: str,
    metadata: dict | None = None,
    keys: list[str] | None = None,
) -> tuple[str, bool, str]:
    """识别 LoRA 的用途/架构，并判断能否用于 Anima/Qwen 绘画链路。"""
    lowered = name.lower()
    video_markers = ("wan", "wan2", "wan2.1", "video", "_e14_", "i2v", "t2v")
    if any(marker in lowered for marker in video_markers) or name == config.VIDEO_LORA:
        return (
            "video",
            False,
            "Wan/视频架构 LoRA 不能直接用于 Anima/Qwen 绘画，需放到视频 LoRA 链路",
        )
    meta = metadata or {}
    architecture = str(
        meta.get("modelspec.architecture")
        or meta.get("ss_base_model_version")
        or meta.get("ss_network_module")
        or ""
    ).lower()
    if "wan" in architecture or "video" in architecture:
        return ("video", False, "检测到 Wan/视频架构元数据，不能用于 Anima/Qwen 绘画")
    if "anima" in architecture:
        return ("drawing", True, "")
    keys = keys or []
    anima_sample = [key for key in keys if "k_proj.lora_a.weight" in key.lower()]
    video_sample = [key for key in keys if ".cross_attn.k.lora_a.weight" in key.lower()]
    if video_sample and not anima_sample:
        return ("video", False, "头部张量结构与 Wan/视频 LoRA 一致，不能用于 Anima/Qwen 绘画")
    return ("drawing", True, "")


def list_loras() -> list[dict]:
    files: list[dict] = []
    if LORAS_DIR.exists():
        for path in sorted(LORAS_DIR.glob("*.safetensors")):
            stat = path.stat()
            metadata, keys = _read_safetensors_header(path)
            purpose, compatible, reason = classify_lora_purpose(path.name, metadata, keys)
            files.append(
                {
                    "name": path.name,
                    "size_mb": round(stat.st_size / 1024 / 1024, 1),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
                    "purpose": purpose,
                    "compatible": compatible,
                    "incompatible_reason": reason or None,
                }
            )
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
    lora_strength_model: float = config.DRAW_DEFAULT_LORA_STRENGTH_MODEL,
    lora_strength_clip: float = config.DRAW_DEFAULT_LORA_STRENGTH_CLIP,
    lora_strengths: dict | None = None,
    masked_prompt: str | None = None,
    mask_image: str | None = None,
    inpaint_denoise: float = 0.72,
) -> tuple[dict, int]:
    graph: dict = {}
    graph["1"] = {"class_type": "UNETLoader", "inputs": {"unet_name": model_name, "weight_dtype": "default"}}
    graph["2"] = {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP_NAME, "type": "stable_diffusion", "device": "default"}}
    graph["3"] = {"class_type": "VAELoader", "inputs": {"vae_name": VAE_NAME}}

    model_src = "1"
    cleaned, prompt_loras = _clean_wlr_tags(prompt)
    selected: dict[str, dict] = {}

    def lora_strength(name: str, key: str, fallback: float) -> float:
        if lora_strengths and name in lora_strengths and key in lora_strengths[name]:
            try:
                return float(lora_strengths[name][key])
            except (TypeError, ValueError):
                pass
        return fallback

    for name in loras or []:
        fname = name if name.endswith(".safetensors") else name + ".safetensors"
        selected.setdefault(
            fname,
            {
                "strength_model": lora_strength(fname, "model", lora_strength_model),
                "strength_clip": lora_strength(fname, "clip", lora_strength_clip),
            },
        )
    for stem, model_w, clip_w, _trigger_w in prompt_loras:
        fname = stem if stem.endswith(".safetensors") else stem + ".safetensors"
        entry = selected.setdefault(
            fname,
            {
                "strength_model": lora_strength(fname, "model", lora_strength_model),
                "strength_clip": lora_strength(fname, "clip", lora_strength_clip),
            },
        )
        if model_w:
            entry["strength_model"] = float(model_w)
        if clip_w:
            entry["strength_clip"] = float(clip_w)

    node_id = 4
    for fname, strengths in selected.items():
        if not (LORAS_DIR / fname).exists():
            continue
        graph[str(node_id)] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": [model_src, 0],
                "clip": ["2", 0],
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

    graph[pos_id] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["2", 0], "text": cleaned.strip()},
    }
    graph[neg_id] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["2", 0], "text": negative_prompt.strip()},
    }
    graph[lat_id] = {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": int(width), "height": int(height), "batch_size": 1},
    }
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
    if not masked_prompt or not mask_image:
        decode_id = str(node_id)
        node_id += 1
        save_id = str(node_id)
        graph[decode_id] = {
            "class_type": "VAEDecode",
            "inputs": {"samples": [sample_id, 0], "vae": ["3", 0]},
        }
        graph[save_id] = {
            "class_type": "SaveImage",
            "inputs": {
                "images": [decode_id, 0],
                "filename_prefix": "studio/anima",
            },
        }
        return graph, seed

    base_decode_id = str(node_id)
    node_id += 1
    load_mask_id = str(node_id)
    node_id += 1
    image_to_mask_id = str(node_id)
    node_id += 1
    inpaint_latent_id = str(node_id)
    node_id += 1
    masked_pos_id = str(node_id)
    node_id += 1
    inpaint_sample_id = str(node_id)
    node_id += 1
    final_decode_id = str(node_id)
    node_id += 1
    save_id = str(node_id)

    cleaned_masked, _ = _clean_wlr_tags(str(masked_prompt))
    graph[base_decode_id] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": [sample_id, 0], "vae": ["3", 0]},
    }
    graph[load_mask_id] = {
        "class_type": "LoadImage",
        "inputs": {"image": mask_image},
    }
    graph[image_to_mask_id] = {
        "class_type": "ImageToMask",
        "inputs": {"image": [load_mask_id, 0], "channel": "red"},
    }
    graph[inpaint_latent_id] = {
        "class_type": "VAEEncodeForInpaint",
        "inputs": {
            "pixels": [base_decode_id, 0],
            "vae": ["3", 0],
            "mask": [image_to_mask_id, 0],
            "grow_mask_by": 12,
        },
    }
    graph[masked_pos_id] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["2", 0], "text": cleaned_masked.strip()},
    }
    graph[inpaint_sample_id] = {
        "class_type": "KSampler",
        "inputs": {
            "model": [model_src, 0],
            "positive": [masked_pos_id, 0],
            "negative": [neg_id, 0],
            "latent_image": [inpaint_latent_id, 0],
            "seed": min(2**63 - 1, int(seed) + 1),
            "steps": int(steps),
            "cfg": float(cfg),
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": max(0.0, min(1.0, float(inpaint_denoise))),
        },
    }
    graph[final_decode_id] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": [inpaint_sample_id, 0], "vae": ["3", 0]},
    }
    graph[save_id] = {
        "class_type": "SaveImage",
        "inputs": {
            "images": [final_decode_id, 0],
            "filename_prefix": "studio/anima",
        },
    }
    return graph, seed


def build_inpaint_workflow(
    *,
    source_image: str,
    mask_image: str,
    prompt: str,
    negative_prompt: str,
    masked_prompt: str | None = None,
    model_name: str = DEFAULT_MODEL,
    loras: list[str] | None = None,
    seed: int | None = None,
    steps: int = config.DRAW_DEFAULT_STEPS,
    cfg: float = config.DRAW_DEFAULT_CFG,
    denoise: float = 0.75,
    grow: int = 12,
    feather: int = 8,
    lora_strength_model: float = config.DRAW_DEFAULT_LORA_STRENGTH_MODEL,
    lora_strength_clip: float = config.DRAW_DEFAULT_LORA_STRENGTH_CLIP,
    lora_strengths: dict | None = None,
) -> tuple[dict, int]:
    """Build a reference-image inpaint graph; source pixels stay outside the mask."""
    graph: dict = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": model_name, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP_NAME, "type": "stable_diffusion", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE_NAME}},
        "4": {"class_type": "LoadImage", "inputs": {"image": source_image}},
        "5": {"class_type": "LoadImage", "inputs": {"image": mask_image}},
        "6": {"class_type": "ImageToMask", "inputs": {"image": ["5", 0], "channel": "red"}},
        "7": {
            "class_type": "GrowMask",
            "inputs": {"mask": ["6", 0], "expand": max(0, min(64, int(grow))), "tapered_corners": True},
        },
        "8": {
            "class_type": "FeatherMask",
            "inputs": {
                "mask": ["7", 0],
                "left": max(0, min(64, int(feather))),
                "top": max(0, min(64, int(feather))),
                "right": max(0, min(64, int(feather))),
                "bottom": max(0, min(64, int(feather))),
            },
        },
        # 用 VAEEncode + SetLatentNoiseMask，而不是 VAEEncodeForInpaint：
        # 后者会先把 mask 内像素改成 0.5 灰，当前 Anima 链路下会保留灰块。
        "9": {"class_type": "VAEEncode", "inputs": {"pixels": ["4", 0], "vae": ["3", 0]}},
        "16": {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["9", 0], "mask": ["8", 0]}},
    }

    cleaned_prompt, prompt_loras = _clean_wlr_tags(str(prompt or ""))
    cleaned_masked, masked_loras = _clean_wlr_tags(str(masked_prompt or prompt or ""))
    cleaned_negative, _ = _clean_wlr_tags(str(negative_prompt or ""))
    positive_text = cleaned_prompt.strip()
    local_text = cleaned_masked.strip()
    if local_text and local_text != positive_text:
        positive_text = f"{positive_text}, {local_text}".strip(", ")
    selected: dict[str, dict] = {}

    def lora_strength(name: str, key: str, fallback: float) -> float:
        if lora_strengths and name in lora_strengths and key in lora_strengths[name]:
            try:
                return float(lora_strengths[name][key])
            except (TypeError, ValueError):
                pass
        return fallback

    def add_lora(name: str, model_w: str = "", clip_w: str = "") -> None:
        fname = name if name.endswith(".safetensors") else name + ".safetensors"
        entry = selected.setdefault(
            fname,
            {
                "strength_model": lora_strength(fname, "model", lora_strength_model),
                "strength_clip": lora_strength(fname, "clip", lora_strength_clip),
            },
        )
        if model_w:
            entry["strength_model"] = float(model_w)
        if clip_w:
            entry["strength_clip"] = float(clip_w)

    for name in loras or []:
        add_lora(str(name))
    for stem, model_w, clip_w, _trigger_w in [*prompt_loras, *masked_loras]:
        add_lora(stem, model_w, clip_w)

    model_src = "1"
    clip_src = "2"
    clip_output = 0
    node_id = 17
    for fname, strengths in selected.items():
        if not (LORAS_DIR / fname).exists():
            continue
        graph[str(node_id)] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": [model_src, 0],
                "clip": [clip_src, clip_output],
                "lora_name": fname,
                "strength_model": strengths["strength_model"],
                "strength_clip": strengths["strength_clip"],
            },
        }
        model_src = str(node_id)
        clip_src = str(node_id)
        clip_output = 1
        node_id += 1

    graph["10"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": [clip_src, clip_output], "text": positive_text},
    }
    graph["11"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": [clip_src, clip_output], "text": cleaned_negative.strip()},
    }
    if seed is None:
        seed = random.randint(0, 2**63 - 1)
    graph["12"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": [model_src, 0],
            "positive": ["10", 0],
            "negative": ["11", 0],
            "latent_image": ["16", 0],
            "seed": int(seed),
            "steps": max(1, min(60, int(steps))),
            "cfg": float(cfg),
            "sampler_name": "euler",
            "scheduler": "simple",
            "denoise": max(0.2, min(1.0, float(denoise))),
        },
    }
    graph["13"] = {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}}
    graph["14"] = {
        "class_type": "ImageCompositeMasked",
        "inputs": {
            "destination": ["4", 0],
            "source": ["13", 0],
            "x": 0,
            "y": 0,
            "resize_source": False,
            "mask": ["8", 0],
        },
    }
    graph["15"] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["14", 0], "filename_prefix": "studio/inpaint"},
    }
    return graph, int(seed)


def _submit_graph(
    graph: dict,
    *,
    seed: int,
    output_dir: str | None,
    timeout: int,
    filename_prefix: str,
    cancel_event: threading.Event | None = None,
) -> dict:
    if cancel_event is not None and cancel_event.is_set():
        raise GenerationCancelled("generation cancelled")
    client_id = uuid.uuid4().hex
    start = time.time()
    response = requests.post(
        COMFY_URL + "/prompt",
        json={"prompt": graph, "client_id": client_id},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"ComfyUI /prompt {response.status_code}: {response.text[:2000]}")
    prompt_id = response.json()["prompt_id"]

    deadline = time.time() + timeout
    while time.time() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            try:
                requests.post(COMFY_URL + "/interrupt", timeout=5)
            except Exception:
                pass
            raise GenerationCancelled(f"generation cancelled: {prompt_id}")
        history = requests.get(COMFY_URL + f"/history/{prompt_id}", timeout=10).json()
        entry = history.get(prompt_id)
        if not entry:
            time.sleep(1)
            continue
        status = entry.get("status") or {}
        if status.get("status_str") == "error":
            raise RuntimeError(str(status.get("messages") or status))
        images: list[dict] = []
        for node_out in (entry.get("outputs") or {}).values():
            images.extend(node_out.get("images") or [])
        if images:
            image = images[0]
            query = (
                f"filename={image['filename']}"
                f"&subfolder={image.get('subfolder', '')}"
                f"&type={image.get('type', 'output')}"
            )
            comfy_url = f"{COMFY_URL}/view?{query}"
            image_response = requests.get(comfy_url, timeout=30)
            image_response.raise_for_status()
            filename = f"{filename_prefix}_{datetime.now():%Y%m%d_%H%M%S}_{str(seed)[-8:]}.png"
            target_dir = Path(output_dir) if output_dir else AI_PRODUCT_DIR
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / filename
            target.write_bytes(image_response.content)
            image_url = (
                f"/api/test-images/{filename}"
                if output_dir and Path(output_dir).resolve() != AI_PRODUCT_DIR.resolve()
                else f"/api/images/{filename}"
            )
            return {
                "prompt_id": prompt_id,
                "image_url": image_url,
                "comfy_url": comfy_url,
                "saved_path": str(target),
                "seed": seed,
                "elapsed": round(time.time() - start, 1),
            }
        time.sleep(1)
    raise TimeoutError(f"ComfyUI generation timeout: {prompt_id}")


def generate_inpaint(
    *,
    source_image: str,
    mask_image: str,
    prompt: str,
    negative_prompt: str,
    masked_prompt: str | None = None,
    model_name: str = DEFAULT_MODEL,
    loras: list[str] | None = None,
    seed: int | None = None,
    steps: int = config.DRAW_DEFAULT_STEPS,
    cfg: float = config.DRAW_DEFAULT_CFG,
    denoise: float = 0.75,
    grow: int = 12,
    feather: int = 8,
    lora_strength_model: float = config.DRAW_DEFAULT_LORA_STRENGTH_MODEL,
    lora_strength_clip: float = config.DRAW_DEFAULT_LORA_STRENGTH_CLIP,
    lora_strengths: dict | None = None,
    output_dir: str | None = None,
    timeout: int | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Generate one inpaint candidate from a reference image and mask."""
    graph, seed = build_inpaint_workflow(
        source_image=source_image,
        mask_image=mask_image,
        prompt=prompt,
        negative_prompt=negative_prompt,
        masked_prompt=masked_prompt,
        model_name=model_name,
        loras=loras,
        seed=seed,
        steps=steps,
        cfg=cfg,
        denoise=denoise,
        grow=grow,
        feather=feather,
        lora_strength_model=lora_strength_model,
        lora_strength_clip=lora_strength_clip,
        lora_strengths=lora_strengths,
    )
    return _submit_graph(
        graph,
        seed=seed,
        output_dir=output_dir,
        timeout=timeout or config.COMFY_GENERATE_TIMEOUT,
        filename_prefix="inpaint",
        cancel_event=cancel_event,
    )


def generate(
    prompt: str,
    negative_prompt: str,
    width: int = config.DRAW_DEFAULT_WIDTH,
    height: int = config.DRAW_DEFAULT_HEIGHT,
    steps: int = config.DRAW_DEFAULT_STEPS,
    cfg: float = config.DRAW_DEFAULT_CFG,
    loras: list[str] | None = None,
    timeout: int | None = None,
    model_name: str = DEFAULT_MODEL,
    lora_strength_model: float = config.DRAW_DEFAULT_LORA_STRENGTH_MODEL,
    lora_strength_clip: float = config.DRAW_DEFAULT_LORA_STRENGTH_CLIP,
    seed: int | None = None,
    lora_strengths: dict | None = None,
    output_dir: str | None = None,
    masked_prompt: str | None = None,
    mask_image: str | None = None,
    inpaint_denoise: float = 0.72,
) -> dict:
    if timeout is None:
        timeout = config.COMFY_GENERATE_TIMEOUT
    graph, seed = build_workflow(
        prompt,
        negative_prompt,
        width,
        height,
        steps,
        cfg,
        loras,
        model_name=model_name,
        lora_strength_model=lora_strength_model,
        lora_strength_clip=lora_strength_clip,
        seed=seed,
        lora_strengths=lora_strengths,
        masked_prompt=masked_prompt,
        mask_image=mask_image,
        inpaint_denoise=inpaint_denoise,
    )
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
                        comfy_url = f"{COMFY_URL}/view?{query}"
                        saved_path = None
                        image_url = comfy_url
                        try:
                            image_response = requests.get(comfy_url, timeout=30)
                            image_response.raise_for_status()
                            filename = f"anima_{datetime.now():%Y%m%d_%H%M%S}_{str(seed)[-8:]}.png"
                            target_dir = Path(output_dir) if output_dir else AI_PRODUCT_DIR
                            target_dir.mkdir(parents=True, exist_ok=True)
                            target = target_dir / filename
                            target.write_bytes(image_response.content)
                            saved_path = str(target)
                            image_url = f"/api/test-images/{filename}" if output_dir else f"/api/images/{filename}"
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
