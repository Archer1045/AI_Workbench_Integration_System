"""Day 1 probe: prove ComfyUI mask compositing preserves pixels outside the mask.

This is intentionally model-free. It creates a synthetic source image and a
circular mask, runs LoadImage -> ImageToMask -> GrowMask -> FeatherMask ->
ImageCompositeMasked -> SaveImage, then compares the output to the source
outside a conservative margin around the mask.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config

DEFAULT_OUT = BACKEND_DIR.parent.parent / "记录" / "AI绘画_局部重绘_Day1_2026-10-20"
REQUIRED_NODES = (
    "LoadImage",
    "ImageToMask",
    "GrowMask",
    "FeatherMask",
    "EmptyImage",
    "ImageCompositeMasked",
    "SaveImage",
    "ImageScale",
    "VAEEncodeForInpaint",
    "KSampler",
    "VAEDecode",
)


def _make_images(size: int, center: int, radius: int, out_dir: Path) -> tuple[Path, Path]:
    y, x = np.mgrid[0:size, 0:size]
    red = (x * 255 // max(1, size - 1)).astype(np.uint8)
    green = (y * 255 // max(1, size - 1)).astype(np.uint8)
    checker = (((x // 16 + y // 16) % 2) * 255).astype(np.uint8)
    noise = np.random.default_rng(20261020).integers(0, 48, (size, size, 1), dtype=np.uint8)
    source = np.stack([red, green, checker], axis=-1).astype(np.int16)
    source = np.clip(source + noise, 0, 255).astype(np.uint8)
    source_path = out_dir / "source.png"
    Image.fromarray(source, mode="RGB").save(source_path)

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse(
        (center - radius, center - radius, center + radius, center + radius),
        fill=255,
    )
    mask_rgb = Image.merge("RGB", (mask, mask, mask))
    mask_path = out_dir / "mask.png"
    mask_rgb.save(mask_path)
    return source_path, mask_path


def _graph(source_name: str, mask_name: str, size: int, grow: int, feather: int) -> dict:
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": source_name}},
        "2": {"class_type": "LoadImage", "inputs": {"image": mask_name}},
        "3": {"class_type": "ImageToMask", "inputs": {"image": ["2", 0], "channel": "red"}},
        "4": {
            "class_type": "GrowMask",
            "inputs": {"mask": ["3", 0], "expand": grow, "tapered_corners": True},
        },
        "5": {
            "class_type": "FeatherMask",
            "inputs": {"mask": ["4", 0], "left": feather, "top": feather, "right": feather, "bottom": feather},
        },
        "6": {
            "class_type": "EmptyImage",
            "inputs": {"width": size, "height": size, "batch_size": 1, "color": 0xFF0000},
        },
        "7": {
            "class_type": "ImageCompositeMasked",
            "inputs": {
                "destination": ["1", 0],
                "source": ["6", 0],
                "x": 0,
                "y": 0,
                "resize_source": False,
                "mask": ["5", 0],
            },
        },
        "8": {
            "class_type": "SaveImage",
            "inputs": {"images": ["7", 0], "filename_prefix": "studio/inpaint_day1"},
        },
    }


def _check_nodes(url: str) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for name in REQUIRED_NODES:
        response = requests.get(f"{url}/object_info/{name}", timeout=10)
        result[name] = response.status_code == 200 and name in response.json()
    return result


def _submit_and_fetch(url: str, graph: dict, out_dir: Path, timeout: int = 120) -> tuple[str, Path]:
    response = requests.post(
        f"{url}/prompt",
        json={"prompt": graph, "client_id": uuid.uuid4().hex},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"ComfyUI rejected the graph: {response.status_code} {response.text}")
    prompt_id = response.json()["prompt_id"]

    deadline = time.time() + timeout
    while time.time() < deadline:
        history = requests.get(f"{url}/history/{prompt_id}", timeout=10).json()
        entry = history.get(prompt_id)
        if entry:
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI execution failed: {json.dumps(status, ensure_ascii=False)}")
            images = []
            for node_output in (entry.get("outputs") or {}).values():
                images.extend(node_output.get("images") or [])
            if images:
                image = images[0]
                query = (
                    f"filename={image['filename']}"
                    f"&subfolder={image.get('subfolder', '')}"
                    f"&type={image.get('type', 'output')}"
                )
                image_response = requests.get(f"{url}/view?{query}", timeout=30)
                image_response.raise_for_status()
                result_path = out_dir / "result.png"
                result_path.write_bytes(image_response.content)
                return prompt_id, result_path
        time.sleep(0.5)
    raise TimeoutError(f"ComfyUI did not finish prompt {prompt_id} within {timeout}s")


def _compare(source_path: Path, result_path: Path, center: int, safe_radius: int) -> dict:
    source = np.asarray(Image.open(source_path).convert("RGB")).astype(np.int16)
    result = np.asarray(Image.open(result_path).convert("RGB")).astype(np.int16)
    if source.shape != result.shape:
        raise AssertionError(f"shape mismatch: {source.shape} vs {result.shape}")

    height, width = source.shape[:2]
    y, x = np.mgrid[0:height, 0:width]
    distance = np.sqrt((x - center) ** 2 + (y - center) ** 2)
    outside = distance > safe_radius
    inside = distance < max(8, safe_radius // 2)
    diff = np.abs(result - source)
    outside_max = int(diff[outside].max()) if outside.any() else 0
    outside_changed = int(np.any(diff[outside] > 0, axis=-1).sum()) if outside.any() else 0
    inside_red = (
        (result[..., 0] > 240)
        & (result[..., 1] < 15)
        & (result[..., 2] < 15)
    )
    inside_red_ratio = float(inside_red[inside].mean()) if inside.any() else 0.0
    return {
        "outside_pixels": int(outside.sum()),
        "outside_changed_pixels": outside_changed,
        "outside_max_channel_diff": outside_max,
        "inside_red_ratio": round(inside_red_ratio, 6),
        "overall_max_channel_diff": int(diff.max()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=config.COMFY_URL)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--radius", type=int, default=96)
    parser.add_argument("--grow", type=int, default=12)
    parser.add_argument("--feather", type=int, default=8)
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    center = args.size // 2
    source_path, mask_path = _make_images(args.size, center, args.radius, out_dir)

    input_dir = Path(config.COMFY_INPUT_DIR)
    input_dir.mkdir(parents=True, exist_ok=True)
    source_name = "inpaint_day1_source.png"
    mask_name = "inpaint_day1_mask.png"
    (input_dir / source_name).write_bytes(source_path.read_bytes())
    (input_dir / mask_name).write_bytes(mask_path.read_bytes())

    graph = _graph(source_name, mask_name, args.size, args.grow, args.feather)
    nodes = _check_nodes(args.url)
    (out_dir / "workflow.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    prompt_id, result_path = _submit_and_fetch(args.url, graph, out_dir)

    safe_radius = args.radius + args.grow + args.feather + 24
    metrics = _compare(source_path, result_path, center, safe_radius)
    passed = (
        metrics["outside_max_channel_diff"] <= 1
        and metrics["inside_red_ratio"] >= 0.99
    )
    report = {
        "comfy_url": args.url,
        "prompt_id": prompt_id,
        "size": args.size,
        "mask_center": center,
        "mask_radius": args.radius,
        "grow": args.grow,
        "feather": args.feather,
        "safe_radius": safe_radius,
        "required_nodes": nodes,
        "nodes_ok": all(nodes.values()),
        **metrics,
        "passed": passed and all(nodes.values()),
        "source": str(source_path),
        "mask": str(mask_path),
        "result": str(result_path),
        "workflow": str(out_dir / "workflow.json"),
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
