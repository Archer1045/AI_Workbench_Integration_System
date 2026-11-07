"""Save both decoded and final-composite outputs for inpaint diagnosis."""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

import requests

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import config
from comfy_worker import build_inpaint_workflow


def main() -> int:
    out_dir = BACKEND_DIR.parent.parent / "记录" / "AI绘画_局部重绘_Debug_2026-10-20"
    out_dir.mkdir(parents=True, exist_ok=True)
    graph, seed = build_inpaint_workflow(
        source_image="inpaint_fix_source.png",
        mask_image="inpaint_fix_mask.png",
        prompt="an empty seaside cottage veranda with a wooden balcony, wicker chair and soft ocean light",
        negative_prompt="lowres",
        masked_prompt="an empty seaside cottage veranda with a wooden balcony, wicker chair and soft ocean light",
        model_name="chosenIrisesMix_v20Anima.safetensors",
        loras=[],
        seed=777,
        steps=1,
        cfg=1.0,
        denoise=0.75,
        grow=12,
        feather=8,
    )
    # 13 = VAEDecode of sampler output; 14 = ImageCompositeMasked; 15 = final SaveImage.
    graph["20"] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["13", 0], "filename_prefix": "studio/inpaint_debug_decoded"},
    }
    client_id = uuid.uuid4().hex
    response = requests.post(
        config.COMFY_URL + "/prompt",
        json={"prompt": graph, "client_id": client_id},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(response.text)
    prompt_id = response.json()["prompt_id"]
    entry = None
    deadline = time.time() + 180
    while time.time() < deadline:
        history = requests.get(f"{config.COMFY_URL}/history/{prompt_id}", timeout=10).json()
        entry = history.get(prompt_id)
        if entry and entry.get("outputs"):
            break
        time.sleep(1)
    if not entry:
        raise TimeoutError(prompt_id)
    saved = []
    for node_id, node_output in (entry.get("outputs") or {}).items():
        for index, image in enumerate(node_output.get("images") or []):
            query = (
                f"filename={image['filename']}"
                f"&subfolder={image.get('subfolder', '')}"
                f"&type={image.get('type', 'output')}"
            )
            data = requests.get(f"{config.COMFY_URL}/view?{query}", timeout=30).content
            path = out_dir / f"node_{node_id}_{index}.png"
            path.write_bytes(data)
            saved.append({"node_id": node_id, "path": str(path), "filename": image["filename"]})
    report = {"prompt_id": prompt_id, "seed": seed, "outputs": saved}
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
