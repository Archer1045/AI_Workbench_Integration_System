"""Wan2.1 I2V 视频任务：工作流构建、ComfyUI 提交与成片落库。"""
from __future__ import annotations

import json
import random
import shutil
import time
import uuid
from pathlib import Path

import requests

import config
import database
import task_registry

COMFY_URL = config.COMFY_URL.rstrip("/")
VIDEO_OUTPUT_DIR = config.VIDEO_OUTPUT_DIR
VIDEO_KEYFRAME_DIR = config.VIDEO_KEYFRAME_DIR
COMFY_INPUT_DIR = config.COMFY_INPUT_DIR
COMFY_VIDEO_SUBDIR = config.VIDEO_COMFY_SUBDIR
COMFY_OUTPUT_DIR = config.COMFY_DIR / "output"
VIDEO_EXTS = {".webm", ".mp4", ".mov", ".gif", ".avi"}


def _param(params: dict, key: str, default):
    value = params.get(key)
    return default if value is None or value == "" else value


def _find_nodes(graph: dict, class_type: str) -> list[tuple[str, dict]]:
    return [(node_id, node) for node_id, node in graph.items() if node.get("class_type") == class_type]


def _drop_lora_node(graph: dict, node_id: str) -> dict:
    """移除 LoraLoader 并把下游引用改接到它的源模型/源 CLIP。"""
    node = graph.pop(node_id)
    source_inputs = node.get("inputs", {})
    model_source = source_inputs.get("model")
    clip_source = source_inputs.get("clip")
    for other in graph.values():
        for key, value in list((other.get("inputs") or {}).items()):
            if not isinstance(value, list) or len(value) != 2 or str(value[0]) != node_id:
                continue
            output_index = int(value[1])
            if key == "model" and model_source:
                other["inputs"][key] = list(model_source)
            elif output_index == 1 and clip_source:
                other["inputs"][key] = list(clip_source)
            else:
                other["inputs"][key] = list(model_source) if model_source else value
    return graph


def build_video_workflow(params: dict) -> dict:
    """读取 Wan I2V API 模板并替换模型/关键帧/提示词/参数。"""
    template = Path(config.VIDEO_WORKFLOW_PATH)
    if not template.is_file():
        raise FileNotFoundError(f"视频工作流模板不存在：{template}")
    graph = json.loads(template.read_text(encoding="utf-8"))

    for _, node in _find_nodes(graph, "UNETLoader"):
        node["inputs"]["unet_name"] = str(params.get("model") or config.VIDEO_MODEL)
    for _, node in _find_nodes(graph, "CLIPLoader"):
        node["inputs"]["clip_name"] = str(params.get("clip") or config.VIDEO_CLIP)
    for _, node in _find_nodes(graph, "VAELoader"):
        node["inputs"]["vae_name"] = str(params.get("vae") or config.VIDEO_VAE)
    for _, node in _find_nodes(graph, "CLIPVisionLoader"):
        node["inputs"]["clip_name"] = str(params.get("clip_vision") or config.VIDEO_CLIP_VISION)
    for _, node in _find_nodes(graph, "LoadImage"):
        node["inputs"]["image"] = str(params["image_name"])
    for _, node in _find_nodes(graph, "WanImageToVideo"):
        node["inputs"]["width"] = int(_param(params, "width", config.VIDEO_DEFAULT_WIDTH))
        node["inputs"]["height"] = int(_param(params, "height", config.VIDEO_DEFAULT_HEIGHT))
        node["inputs"]["length"] = int(_param(params, "frames", config.VIDEO_DEFAULT_FRAMES))

    lora_nodes = _find_nodes(graph, "LoraLoader")
    use_lora = bool(params.get("use_lora", True))
    for node_id, node in lora_nodes:
        if use_lora:
            node["inputs"]["lora_name"] = str(params.get("lora") or config.VIDEO_LORA)
            node["inputs"]["strength_model"] = float(
                _param(params, "lora_strength", config.VIDEO_DEFAULT_LORA_STRENGTH)
            )
            node["inputs"]["strength_clip"] = float(
                _param(params, "lora_strength", config.VIDEO_DEFAULT_LORA_STRENGTH)
            )
        else:
            graph = _drop_lora_node(graph, node_id)

    text_nodes = _find_nodes(graph, "CLIPTextEncode")
    positive = str(params.get("positive_prompt") or "").strip()
    negative = str(params.get("negative_prompt") or "").strip()
    if text_nodes:
        text_nodes[0][1]["inputs"]["text"] = positive
    if len(text_nodes) > 1:
        text_nodes[1][1]["inputs"]["text"] = negative
    for _, node in _find_nodes(graph, "KSampler"):
        node["inputs"]["seed"] = int(_param(params, "seed", 0))
        node["inputs"]["steps"] = int(_param(params, "steps", config.VIDEO_DEFAULT_STEPS))
        node["inputs"]["cfg"] = float(_param(params, "cfg", config.VIDEO_DEFAULT_CFG))
        node["inputs"]["denoise"] = float(_param(params, "denoise", config.VIDEO_DEFAULT_DENOISE))
        if params.get("sampler_name"):
            node["inputs"]["sampler_name"] = str(params["sampler_name"])
        if params.get("scheduler"):
            node["inputs"]["scheduler"] = str(params["scheduler"])
    for _, node in _find_nodes(graph, "SaveWEBM"):
        node["inputs"]["filename_prefix"] = str(params.get("filename_prefix") or "workbench_video")
        node["inputs"]["fps"] = int(_param(params, "fps", config.VIDEO_DEFAULT_FPS))
    return graph


def _prepare_comfy_keyframe(keyframe_name: str, job_id: str) -> tuple[str, Path]:
    """把关键帧复制到 ComfyUI input 子目录，返回节点使用的相对路径。"""
    source = Path(keyframe_name)
    if not source.is_absolute():
        source = VIDEO_KEYFRAME_DIR / source.name
    if not source.is_file():
        raise FileNotFoundError(f"关键帧不存在：{source}")
    target_dir = COMFY_INPUT_DIR / COMFY_VIDEO_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{job_id}_{source.name}"
    shutil.copy2(source, target)
    return f"{COMFY_VIDEO_SUBDIR}/{target.name}", target


def _collect_output_files(value) -> list[dict]:
    """递归收集 ComfyUI history 中的 filename 元数据。"""
    files: list[dict] = []
    if isinstance(value, dict):
        if isinstance(value.get("filename"), str):
            files.append(value)
        for child in value.values():
            files.extend(_collect_output_files(child))
    elif isinstance(value, list):
        for child in value:
            files.extend(_collect_output_files(child))
    return files


def _download_or_copy_output(history_entry: dict, target_dir: Path, prefix: str) -> Path:
    """优先按 history 元数据下载，失败时按输出目录前缀兜底。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    candidates = _collect_output_files(history_entry.get("outputs") or {})
    candidates = [
        item
        for item in candidates
        if Path(str(item.get("filename") or "")).suffix.lower() in VIDEO_EXTS
    ]
    if candidates:
        item = candidates[0]
        try:
            response = requests.get(
                COMFY_URL + "/view",
                params={
                    "filename": item["filename"],
                    "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output"),
                },
                timeout=60,
            )
            response.raise_for_status()
            suffix = Path(str(item["filename"])).suffix or ".webm"
            target = target_dir / f"{prefix}{suffix}"
            target.write_bytes(response.content)
            return target
        except Exception:
            pass

    if COMFY_OUTPUT_DIR.is_dir():
        matches = sorted(
            (
                path
                for path in COMFY_OUTPUT_DIR.iterdir()
                if path.is_file()
                and path.suffix.lower() in VIDEO_EXTS
                and path.name.startswith(str(prefix))
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if matches:
            target = target_dir / matches[0].name
            shutil.copy2(matches[0], target)
            return target
    raise FileNotFoundError("ComfyUI 已完成但未找到视频输出文件")


def _interrupt_comfy() -> None:
    try:
        requests.post(COMFY_URL + "/interrupt", timeout=10)
    except Exception:
        pass


def _stop_requested(job_id: str) -> bool:
    job = task_registry.get("video", job_id)
    return bool(job and job.get("stop_requested"))


def request_stop(job_id: str) -> dict:
    """请求停止视频任务：标记 stop_requested 并中断当前 ComfyUI 生成。"""
    task_registry.update("video", job_id, stop_requested=True)
    _interrupt_comfy()
    return {"job_id": job_id, "status": "stopping"}


def run_video_job(job_id: str, params: dict) -> None:
    """后台执行视频任务并更新 video_records/background_jobs。"""
    frames = int(_param(params, "frames", config.VIDEO_DEFAULT_FRAMES))
    seed_value = _param(params, "seed", None)
    seed = int(seed_value if seed_value is not None else random.randint(0, 2**63 - 1))
    prefix = f"video_{job_id[:8]}_{seed}"
    started = time.time()
    comfy_keyframe: Path | None = None
    try:
        task_registry.update("video", job_id, total=frames, done=0, current="准备关键帧与工作流")
        image_name, comfy_keyframe = _prepare_comfy_keyframe(str(params.get("keyframe_name") or ""), job_id)
        params = dict(params)
        params["seed"] = seed
        params["image_name"] = image_name
        params["filename_prefix"] = prefix
        graph = build_video_workflow(params)

        task_registry.update("video", job_id, current="提交 ComfyUI")
        response = requests.post(
            COMFY_URL + "/prompt",
            json={"prompt": graph, "client_id": uuid.uuid4().hex},
            timeout=30,
        )
        response.raise_for_status()
        prompt_id = str((response.json() or {}).get("prompt_id") or "")
        if not prompt_id:
            raise RuntimeError("ComfyUI 未返回 prompt_id")

        task_registry.update("video", job_id, current="生成中（预计每 5 秒刷新）")
        deadline = time.time() + int(
            _param(params, "timeout_seconds", config.VIDEO_TIMEOUT_SECONDS)
        )
        history_entry = None
        while time.time() < deadline:
            if _stop_requested(job_id):
                _interrupt_comfy()
                database.update_video_record_result(job_id, "stopped", error="用户取消")
                task_registry.finish("video", job_id, "stopped", "用户取消")
                return
            history = requests.get(COMFY_URL + f"/history/{prompt_id}", timeout=10).json()
            entry = (history or {}).get(prompt_id)
            if entry:
                status = (entry.get("status") or {})
                if status.get("status_str") == "error":
                    messages = status.get("messages") or entry
                    raise RuntimeError(f"ComfyUI 执行失败：{str(messages)[-500:]}")
                if status.get("completed") or entry.get("outputs"):
                    history_entry = entry
                    break
            time.sleep(5)
        if history_entry is None:
            raise TimeoutError("视频生成超时")

        target = _download_or_copy_output(history_entry, VIDEO_OUTPUT_DIR, prefix)
        duration_seconds = round(time.time() - started, 1)
        database.update_video_record_result(
            job_id,
            "done",
            video_name=target.name,
            duration_seconds=duration_seconds,
        )
        task_registry.update(
            "video",
            job_id,
            total=frames,
            done=frames,
            current=target.name,
        )
        task_registry.finish("video", job_id, "done")
    except Exception as exc:  # noqa: BLE001 - 后台任务需要统一落终态
        database.update_video_record_result(job_id, "error", error=str(exc)[-1000:])
        task_registry.finish("video", job_id, "error", str(exc)[-1000:])
    finally:
        if comfy_keyframe and comfy_keyframe.exists():
            try:
                comfy_keyframe.unlink()
            except OSError:
                pass
