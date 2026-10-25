"""LoRA 训练辅助：数据集扫描、打开目录、批量打标。"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import struct
import subprocess
import threading
import time
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import requests
from fastapi import APIRouter, Body, HTTPException, Query, Response

import config
import database
import task_state
import task_registry
import task_resources
from comfy_worker import generate

router = APIRouter()

DATASET_DIR = config.DATASET_DIR
TAG_BACKUP_DIR = config.TAG_BACKUP_DIR
LOG_DIR = config.LOG_DIR
WORK_DIR = LOG_DIR / "caption_work"
KOYA_PY = config.KOYA_PY
WD14_SCRIPT = config.WD14_SCRIPT
WD14_MODEL_DIR = config.WD14_MODEL_DIR
WD14_DEFAULT_REPO = config.WD14_DEFAULT_REPO
OLLAMA_BASE = config.OLLAMA_BASE
VLM_MODEL = config.VLM_MODEL
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
def _env_seconds(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


# 训练日志正常情况下每几秒就会写入一行。超过这个时间没有新内容即视为可疑。
TRAIN_STALL_SECONDS = _env_seconds("TRAIN_STALL_SECONDS", 300, minimum=60)
# 0 表示只标记卡死、不自动停手；设置成更大的秒数后才会自动停止并保留检查点。
TRAIN_STALL_ABORT_SECONDS = _env_seconds("TRAIN_STALL_ABORT_SECONDS", 0)
TRAIN_WATCHDOG_INTERVAL_SECONDS = _env_seconds("TRAIN_WATCHDOG_INTERVAL_SECONDS", 15, minimum=5)


def _train_sidecar_path(job_id: str) -> Path:
    return LOG_DIR / f"train_{job_id}.command.json"


def _read_train_sidecar(job_id: str) -> dict | None:
    path = _train_sidecar_path(job_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_train_sidecar(
    job_id: str,
    *,
    cmd: list[str],
    output_name: str,
    auto_convert: bool,
    cwd: str,
    resumed_from: str = "",
    steps_offset: int = 0,
) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _train_sidecar_path(job_id).write_text(
        json.dumps(
            {
                "cmd": cmd,
                "output_name": output_name,
                "auto_convert": auto_convert,
                "cwd": cwd,
                "resumed_from": resumed_from,
                "steps_offset": steps_offset,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _state_progress(state_dir: Path) -> tuple[int, int] | None:
    """Return (epoch, step) from a kohya state directory."""
    path = state_dir / "train_state.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("current_epoch") or 0), int(data.get("current_step") or 0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _state_step(state_dir: Path) -> int | None:
    progress = _state_progress(state_dir)
    return progress[1] if progress else None


def _latest_resume_state(output_name: str) -> Path | None:
    """Return the complete state with the highest epoch, then step.

    kohya resets ``current_step`` when a run is resumed from an epoch-boundary
    state, so ranking by step alone can pick an older epoch after one resume.
    """
    candidates: list[tuple[int, int, float, Path]] = []
    candidates_paths = list(OUTPUT_DIR.glob(f"{output_name}-state"))
    candidates_paths += list(OUTPUT_DIR.glob(f"{output_name}-[0-9]*-state"))
    for state_dir in candidates_paths:
        if not state_dir.is_dir():
            continue
        if not (state_dir / "model.safetensors").exists():
            continue
        if not (state_dir / "optimizer.bin").exists():
            continue
        progress = _state_progress(state_dir)
        if progress is None:
            continue
        epoch, step = progress
        candidates.append((epoch, step, state_dir.stat().st_mtime, state_dir))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1], item[2]))[3]


def _resume_command(command: list[str], state_dir: Path) -> list[str]:
    """Keep the original command and replace resume/worker flags deterministically."""
    cleaned: list[str] = []
    index = 0
    while index < len(command):
        value = command[index]
        if value in {"--resume", "--max_data_loader_n_workers"}:
            index += 2
            continue
        if value == "--persistent_data_loader_workers":
            index += 1
            continue
        cleaned.append(value)
        index += 1
    cleaned += [
        "--resume",
        str(state_dir),
        "--max_data_loader_n_workers",
        "0",
    ]
    return cleaned
OUTPUT_DIR = config.OUTPUT_DIR
LORAS_DIR = config.LORAS_DIR
MODELS_DIR = config.MODELS_DIR
TRAIN_SCRIPT = config.TRAIN_SCRIPT
CONVERT_SCRIPT = config.CONVERT_SCRIPT
SCAN_SCRIPT = config.SCAN_SCRIPT
ACCELERATE_EXE = config.ACCELERATE_EXE
QWEN3_PATH = config.QWEN3_PATH
VAE_PATH = config.VAE_PATH
TRAIN_DATASET_CONFIG = config.TRAIN_DATASET_CONFIG
AI_PRODUCT_DIR = config.AI_PRODUCT_DIR
EXCLUDED_DIR = config.EXCLUDED_DIR
AI_IMPORT_MARKER = config.AI_IMPORT_MARKER
MERGE_SCRIPT = config.MERGE_SCRIPT
TRAIN_OPTIMIZERS = {"AdamW8bit", "AdamW", "Lion", "Prodigy"}
TRAIN_LR_SCHEDULERS = {"constant", "constant_with_warmup", "cosine", "cosine_with_restarts", "linear"}
TRAIN_MIXED_PRECISIONS = {"bf16", "fp16", "no"}


def _plain_decimal(value: float | int) -> str:
    text = format(Decimal(str(value)), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _dataset_config_text(
    *,
    resolution: int,
    batch_size: int,
    repeats: int,
    shuffle_caption: bool,
    keep_tokens: int,
    bucket_min_reso: int,
    bucket_max_reso: int,
    bucket_reso_steps: int,
    image_dir: Path,
) -> str:
    """生成 dataset_config.toml 内容。

    注意：这里的每个值都必须来自调用方传入的参数——2026-10-11 之前 bucket/keep_tokens/
    shuffle_caption 被写成字面量，导致面板上的对应开关静默失效（见 backlog 与本文件测试）。
    """
    return f"""[general]
shuffle_caption = {"true" if shuffle_caption else "false"}
keep_tokens = {keep_tokens}

[[datasets]]
resolution = {resolution}
batch_size = {batch_size}
enable_bucket = true
min_bucket_reso = {bucket_min_reso}
max_bucket_reso = {bucket_max_reso}
bucket_reso_steps = {bucket_reso_steps}

  [[datasets.subsets]]
  image_dir = "{str(image_dir).replace(chr(92), '/')}"
  caption_extension = ".txt"
  num_repeats = {repeats}
"""


NOISE_MARKERS = (
    "SyntaxWarning",
    "invalid escape sequence",
    "A matching Triton",
    "No module named 'triton'",
    "tensorflow/core/util/port",
    "oneDNN custom operations",
    "TF_ENABLE_ONEDNN_OPTS",
)

CAPTION_JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
TRAIN_JOBS: dict[str, dict] = {}
TRAIN_LOCK = threading.Lock()
REVIEW_JOBS: dict[str, dict] = {}
REVIEW_LOCK = threading.Lock()
MERGE_JOBS: dict[str, dict] = {}
MERGE_LOCK = threading.Lock()
COMPARE_JOBS: dict[str, dict] = {}
COMPARE_LOCK = threading.Lock()


def _image_files() -> list[Path]:
    if not DATASET_DIR.exists():
        return []
    return sorted(
        path
        for path in DATASET_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS
    )


def _is_net_format(path: Path) -> bool:
    """判断底模是否为训练可用的 net. 前缀格式。"""
    try:
        with path.open("rb") as fh:
            header_len = struct.unpack("<Q", fh.read(8))[0]
            header = json.loads(fh.read(header_len))
        return any(key.startswith("net.") for key in header if key != "__metadata__")
    except Exception:
        return False


@router.get("/api/train/dataset")
def dataset_info() -> dict:
    """返回数据集图片数量与缺少标签的文件列表。"""
    items = []
    missing = 0
    for img in _image_files():
        caption = img.with_suffix(".txt")
        has_caption = caption.exists()
        if not has_caption:
            missing += 1
        items.append({"name": img.name, "has_caption": has_caption, "caption_name": caption.name})
    return {
        "image_count": len(items),
        "caption_count": len(items) - missing,
        "missing_count": missing,
        "items": items,
    }


def _caption_files() -> list[Path]:
    """返回数据集根目录下的全部标签文件。"""
    if not DATASET_DIR.exists():
        return []
    return sorted(
        path
        for path in DATASET_DIR.iterdir()
        if path.is_file() and path.suffix.lower() == ".txt"
    )


@router.post("/api/train/dataset/tags/replace")
def replace_dataset_tags(payload: dict = Body(...)) -> dict:
    """批量替换数据集标签：dry_run 只统计不写文件，正式执行前自动备份。"""
    from_tag = str(payload.get("from_tag") or "").strip()
    to_tag = str(payload.get("to_tag") or "").strip()
    dry_run = bool(payload.get("dry_run"))
    if not from_tag:
        raise HTTPException(status_code=400, detail="原标签不能为空")
    if "," in from_tag or "," in to_tag:
        raise HTTPException(status_code=400, detail="标签不能包含逗号")
    if len(from_tag) > 200 or len(to_tag) > 200:
        raise HTTPException(status_code=400, detail="标签长度超出限制")
    if from_tag == to_tag:
        raise HTTPException(status_code=400, detail="原标签与替换标签相同")

    raw = payload.get("filenames") or []
    if raw:
        targets: list[Path] = []
        seen: set[str] = set()
        for item in raw:
            name = Path(str(item)).name
            if name in seen or Path(name).suffix.lower() != ".txt":
                continue
            seen.add(name)
            path = DATASET_DIR / name
            if not path.is_file():
                raise HTTPException(status_code=404, detail=f"标签文件不存在：{name}")
            targets.append(path)
    else:
        targets = _caption_files()

    if not dry_run:
        busy_tasks = task_state.running_tasks()
        if busy_tasks:
            labels = "、".join(task["label"] for task in busy_tasks)
            raise HTTPException(status_code=409, detail=f"有其他项目正在运行（{labels}），请稍后再进行")

    backup_dir: Path | None = None
    if not dry_run:
        backup_dir = TAG_BACKUP_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    changed: list[dict] = []
    affected_tags = 0
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
        tags = [tag.strip() for tag in text.split(",") if tag.strip()]
        replaced = [to_tag if tag == from_tag else tag for tag in tags]
        replaced_count = sum(1 for old, new in zip(tags, replaced) if old != new)
        if replaced_count == 0:
            continue
        # 替换可能产生重复标签，去重并保持首次出现顺序。
        seen_tags: set[str] = set()
        unique: list[str] = []
        for tag in replaced:
            if not tag or tag in seen_tags:
                continue
            seen_tags.add(tag)
            unique.append(tag)
        if not dry_run and backup_dir is not None:
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_dir / path.name)
            path.write_text(", ".join(unique), encoding="utf-8")
        changed.append({"name": path.name, "count": replaced_count})
        affected_tags += replaced_count

    return {
        "ok": True,
        "dry_run": dry_run,
        "total_files": len(targets),
        "affected_files": len(changed),
        "affected_tags": affected_tags,
        "files": changed,
        "backup_dir": str(backup_dir) if backup_dir and not dry_run else None,
    }


@router.get("/api/train/dataset-check")
def dataset_check() -> dict:
    """调用扫描脚本返回数据集质量体检结果。"""
    if not KOYA_PY.exists() or not SCAN_SCRIPT.exists():
        raise HTTPException(status_code=500, detail="扫描脚本缺失")
    proc = subprocess.run(
        [str(KOYA_PY), str(SCAN_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=f"扫描失败：{proc.stderr[-500:]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="扫描结果解析失败") from exc


@router.post("/api/train/open-dataset")
def open_dataset() -> dict:
    """在资源管理器中打开本地数据集目录。"""
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer.exe", str(DATASET_DIR)])
    return {"ok": True, "path": str(DATASET_DIR)}


def _ollama_available() -> bool:
    try:
        return requests.get(OLLAMA_BASE + "/api/tags", timeout=2).status_code == 200
    except Exception:
        return False


def _vlm_caption(image_path: Path, language: str) -> str:
    """用 qwen2.5vl 生成单张图片的描述或标签。"""
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    if language == "description":
        prompt_text = "请用中文详细描述这张图片的人物、服装、背景、画面构图、光线和整体风格。"
    else:
        prompt_text = "请用英文 Danbooru 风格标签描述这张图片，只输出逗号分隔的英文标签，不要解释。"
    response = requests.post(
        OLLAMA_BASE + "/api/generate",
        json={
            "model": database.get_setting("vlm_model", config.VLM_MODEL) or config.VLM_MODEL,
            "prompt": prompt_text,
            "images": [encoded],
            "stream": False,
            "options": {"num_predict": 500, "num_ctx": 8192},
        },
        timeout=180,
    )
    response.raise_for_status()
    return (response.json().get("response") or "").strip()


def _run_qwen(job_id: str, skip_existing: bool, language: str) -> None:
    job = CAPTION_JOBS[job_id]
    try:
        images = _image_files()
        job["total"] = len(images)
        task_registry.update("caption", job_id, total=len(images))
        for img in images:
            if job.get("cancelled"):
                job["status"] = "stopped"
                job["error"] = "任务已取消"
                return
            caption = img.with_suffix(".txt")
            if skip_existing and caption.exists():
                job["done"] += 1
                continue
            text = _vlm_caption(img, language)
            caption.write_text(text + "\n", encoding="utf-8")
            job["done"] += 1
            job["last_file"] = img.name
            task_registry.update("caption", job_id, done=job["done"], current=img.name)
        job["status"] = "done"
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(exc)
    finally:
        job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        task_registry.finish("caption", job_id, job["status"], job.get("error"))


def _run_wd14(
    job_id: str,
    skip_existing: bool,
    threshold: float,
    batch_size: int,
    remove_underscore: bool,
) -> None:
    job = CAPTION_JOBS[job_id]
    images = _image_files()
    job["total"] = len(images)
    work_dir: Path | None = None
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        target_dir = DATASET_DIR
        if skip_existing:
            work_dir = WORK_DIR / job_id
            work_dir.mkdir(parents=True, exist_ok=True)
            linked = 0
            for img in images:
                if img.with_suffix(".txt").exists():
                    continue
                dst = work_dir / img.name
                try:
                    os.link(img, dst)
                except OSError:
                    shutil.copy2(img, dst)
                linked += 1
            target_dir = work_dir
            job["total"] = linked

        cmd = [
            str(KOYA_PY),
            str(WD14_SCRIPT),
            "--onnx",
            "--repo_id",
            WD14_DEFAULT_REPO,
            "--model_dir",
            str(WD14_MODEL_DIR),
            "--batch_size",
            str(batch_size),
            "--thresh",
            str(threshold),
            "--caption_extension",
            ".txt",
        ]
        if remove_underscore:
            cmd.append("--remove_underscore")
        cmd.append(str(target_dir))

        log_path = LOG_DIR / f"wd14_{job_id}.log"
        job["log_path"] = str(log_path)
        env = os.environ.copy()
        env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                cmd,
                cwd=str(WD14_SCRIPT.parent.parent),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        job["process"] = proc
        proc.wait()

        if job.get("cancelled") or proc.returncode != 0:
            job["status"] = "stopped" if job.get("cancelled") else "error"
            job["error"] = "任务已取消" if job.get("cancelled") else f"WD14 退出码 {proc.returncode}"
            job["log"] = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
            task_registry.finish("caption", job_id, job["status"], job["error"])
            return

        if work_dir is not None:
            for txt in work_dir.glob("*.txt"):
                shutil.copy2(txt, DATASET_DIR / txt.name)
            shutil.rmtree(work_dir, ignore_errors=True)
        job["status"] = "done"
        job["done"] = job["total"]
        job["log"] = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
        task_registry.finish("caption", job_id, "done", None)
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(exc)
        task_registry.finish("caption", job_id, "error", str(exc))
    finally:
        job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")


@router.post("/api/train/caption")
def start_caption(payload: dict = Body(...)) -> dict:
    """启动批量打标任务：wd14（默认）或 qwen2.5vl。"""
    mode = str(payload.get("mode") or "wd14").lower()
    if mode not in ("wd14", "qwen"):
        raise HTTPException(status_code=400, detail="mode 必须是 wd14 或 qwen")
    with JOBS_LOCK:
        if any(job["status"] == "running" for job in CAPTION_JOBS.values()):
            raise HTTPException(status_code=409, detail="已有打标任务在运行")
    other_tasks = [task for task in task_state.running_tasks() if task["type"] != "caption"]
    if other_tasks:
        labels = "、".join(task["label"] for task in other_tasks)
        raise HTTPException(status_code=409, detail=f"有其他项目正在运行（{labels}），请稍后再进行")
    if mode == "qwen" and not _ollama_available():
        raise HTTPException(status_code=503, detail="Ollama 未运行，无法使用 qwen2.5vl 模式")
    if mode == "wd14" and not (KOYA_PY.exists() and WD14_SCRIPT.exists()):
        raise HTTPException(status_code=500, detail="Kohya_SS 环境缺失")

    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "mode": mode,
        "status": "running",
        "total": 0,
        "done": 0,
        "last_file": "",
        "log": "",
        "error": None,
        "cancelled": False,
        "process": None,
        "log_path": None,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None,
    }
    CAPTION_JOBS[job_id] = job
    task_registry.register("caption", job_id, resources=task_resources.for_kind("caption"))
    skip_existing = bool(payload.get("skip_existing", True))
    if mode == "wd14":
        try:
            threshold = float(
                payload.get("threshold", config.TRAIN_DEFAULT_CAPTION_THRESHOLD)
            )
            caption_batch_size = int(
                payload.get("batch_size", config.TRAIN_DEFAULT_CAPTION_BATCH_SIZE)
            )
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="打标阈值或 Batch 格式不正确") from None
        if not config.TRAIN_CAPTION_THRESHOLD_MIN <= threshold <= config.TRAIN_CAPTION_THRESHOLD_MAX:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"打标阈值必须在 {config.TRAIN_CAPTION_THRESHOLD_MIN:g}-"
                    f"{config.TRAIN_CAPTION_THRESHOLD_MAX:g} 之间"
                ),
            )
        if not config.TRAIN_CAPTION_BATCH_MIN <= caption_batch_size <= config.TRAIN_CAPTION_BATCH_MAX:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"打标 Batch 必须在 {config.TRAIN_CAPTION_BATCH_MIN}-"
                    f"{config.TRAIN_CAPTION_BATCH_MAX} 之间"
                ),
            )
        threading.Thread(
            target=_run_wd14,
            args=(
                job_id,
                skip_existing,
                threshold,
                caption_batch_size,
                bool(payload.get("remove_underscore", True)),
            ),
            daemon=True,
        ).start()
    else:
        language = "description" if payload.get("language") == "description" else "tags"
        threading.Thread(target=_run_qwen, args=(job_id, skip_existing, language), daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@router.get("/api/train/caption/{job_id}")
def caption_status(job_id: str) -> dict:
    """查询打标任务进度，WD14 模式附带日志尾部。"""
    job = CAPTION_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    public = {key: value for key, value in job.items() if key != "process"}
    if job.get("log_path"):
        try:
            log_path = Path(job["log_path"])
            if log_path.exists():
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                clean = [line for line in lines if not any(marker in line for marker in NOISE_MARKERS)]
                public["log"] = "\n".join(clean)[-4000:]
        except Exception:
            pass
    return public


@router.post("/api/train/caption/{job_id}/stop")
def stop_caption(job_id: str) -> dict:
    """停止正在运行的打标任务。"""
    job = CAPTION_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    job["cancelled"] = True
    proc = job.get("process")
    if proc and proc.poll() is None:
        proc.terminate()
    return {"ok": True}


def _finalize_train_process(job: dict) -> None:
    """同步训练进程终态并落库，自动转换完成后才结束注册表任务。"""
    proc = job.get("process")
    if proc is None or proc.poll() is None or job.get("registry_finished"):
        return
    if job.get("cancelled"):
        job["status"] = "stopped"
        job["error"] = "任务已取消"
    elif proc.returncode == 0:
        job["status"] = "done"
        job["error"] = None
    else:
        job["status"] = "error"
        job["error"] = f"训练退出码 {proc.returncode}"
    if job["status"] == "done" and job.get("auto_convert") and not job.get("converting"):
        job["converting"] = True
        _auto_convert_outputs(job)
    job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    job["registry_finished"] = True
    job_id = str(job.get("job_id") or "")
    if job_id:
        task_registry.finish("train", job_id, job["status"], job.get("error"))
    try:
        database.save_train_job(job)
    except Exception:
        pass


def _watch_train_process(job_id: str) -> None:
    """等待训练子进程退出，不依赖前端轮询也能落终态。"""
    job = TRAIN_JOBS.get(job_id)
    if not job:
        return
    proc = job.get("process")
    if proc is not None:
        proc.wait()
    _finalize_train_process(job)


def _log_age_seconds(log_path: object) -> float | None:
    if not log_path:
        return None
    try:
        path = Path(str(log_path))
        if not path.exists():
            return None
        return round(max(0.0, time.time() - path.stat().st_mtime), 1)
    except OSError:
        return None


def _public_train_job(job: dict) -> dict:
    """返回训练任务公开字段，并顺带同步进程结束状态与日志尾部。"""
    proc = job.get("process")
    if proc is not None and proc.poll() is not None and not job.get("watch_started"):
        _finalize_train_process(job)
    public = {key: value for key, value in job.items() if key != "process"}
    created = job.get("created_at")
    finished = job.get("finished_at")
    if created and finished:
        try:
            fmt = "%Y-%m-%d %H:%M:%S"
            public["duration_seconds"] = round(
                (datetime.strptime(finished, fmt) - datetime.strptime(created, fmt)).total_seconds(),
                1,
            )
        except Exception:
            pass
    log_path = job.get("log_path")
    if log_path:
        try:
            path = Path(log_path)
            if path.exists():
                stat = path.stat()
                public["log_updated_at"] = (
                    datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")
                )
                public["log_age_seconds"] = round(max(0.0, time.time() - stat.st_mtime), 1)
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in reversed(lines):
                    if "steps:" in line:
                        match = re.findall(r"(\d+)/(\d+)", line)
                        if match:
                            public["steps_done"], public["steps_total"] = (int(value) for value in match[-1])
                            break
                loss_by_step: dict[int, float] = {}
                for line in lines:
                    if "avr_loss=" not in line:
                        continue
                    step_match = re.search(r"(\d+)/(\d+)", line)
                    loss_match = re.search(r"avr_loss=([0-9.eE+-]+)", line)
                    if not step_match or not loss_match:
                        continue
                    try:
                        loss_by_step[int(step_match.group(1))] = float(loss_match.group(1))
                    except ValueError:
                        continue
                if loss_by_step:
                    items = [{"step": step, "loss": loss} for step, loss in sorted(loss_by_step.items())]
                    if len(items) > 200:
                        ratio = len(items) / 200
                        items = [items[int(index * ratio)] for index in range(200)]
                    public["loss_history"] = items
                    public["latest_loss"] = items[-1]["loss"]
                    best = min(items, key=lambda item: item["loss"])
                    public["min_loss"] = best["loss"]
                    public["best_step"] = best["step"]
                clean = [line for line in lines if not any(marker in line for marker in NOISE_MARKERS)]
                public["log"] = "\n".join(clean)[-6000:]
        except Exception:
            pass
    age = public.get("log_age_seconds")
    public["stalled"] = bool(
        public.get("status") == "running"
        and not public.get("converting")
        and (
            job.get("stalled")
            or (isinstance(age, (int, float)) and age >= TRAIN_STALL_SECONDS)
        )
    )
    if public["stalled"]:
        public["stall_reason"] = job.get("stall_reason") or "训练日志长时间没有更新"
    else:
        public.pop("stall_reason", None)
    job_id = str(job.get("job_id") or "")
    sidecar = _read_train_sidecar(job_id) if job_id else None
    # 续训后 kohya 的步数会从 0 重新计数；把续训前的进度加回来再展示。
    steps_offset = int(job.get("steps_offset") or (sidecar or {}).get("steps_offset") or 0)
    if steps_offset:
        public["steps_offset"] = steps_offset
        if "steps_done" in public:
            done = int(public["steps_done"]) + steps_offset
            total = int(public.get("steps_total") or 0)
            public["steps_done"] = min(done, total) if total else done
    output_name = str(job.get("output_name") or "")
    resume_state = _latest_resume_state(output_name) if output_name else None
    public["resume_available"] = bool(
        resume_state
        and sidecar
        and (
            public.get("status") in {"error", "stopped"}
            or public["stalled"]
        )
    )
    public["resume_state"] = str(resume_state) if resume_state else ""
    for key in ("steps_done", "steps_total", "latest_loss", "min_loss", "best_step"):
        if key in public:
            job[key] = public[key]
    if job.get("job_id"):
        try:
            database.save_train_job(job)
        except Exception:
            pass
    return public


def _abort_stalled_train(job: dict, age: float) -> None:
    """Stop a hung run only when the operator opted into a hard timeout."""
    job_id = str(job.get("job_id") or "")
    error = f"训练日志超过 {int(age // 60)} 分钟没有更新，已自动停止；可从最近检查点续训"
    job["cancelled"] = True
    job["status"] = "error"
    job["error"] = error
    job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # 先置位，避免进程退出线程与看门狗重复落终态。
    job["registry_finished"] = True
    proc = job.get("process")
    if proc is not None and proc.poll() is None:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
            )
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    try:
        task_registry.finish("train", job_id, "error", error)
    except Exception:
        pass
    try:
        database.save_train_job(job)
    except Exception:
        pass


def _check_train_stall(job_id: str) -> bool:
    """Evaluate one job once; returns whether it is currently considered stalled."""
    job = TRAIN_JOBS.get(job_id)
    if not job or job.get("status") != "running":
        return False
    proc = job.get("process")
    if proc is not None and proc.poll() is not None:
        return False
    age = _log_age_seconds(job.get("log_path"))
    if age is None:
        return False
    stalled = age >= TRAIN_STALL_SECONDS
    reason = f"训练日志已 {int(age // 60)} 分钟没有更新" if stalled else None
    if bool(job.get("stalled")) != stalled or (stalled and job.get("stall_reason") != reason):
        job["stalled"] = stalled
        job["stall_reason"] = reason
        if stalled:
            job["stalled_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            job.pop("stalled_at", None)
        try:
            database.save_train_job(job)
        except Exception:
            pass
    if stalled and TRAIN_STALL_ABORT_SECONDS and age >= TRAIN_STALL_ABORT_SECONDS:
        _abort_stalled_train(job, age)
    return stalled


def _train_watchdog_loop(job_id: str) -> None:
    """Mark long-silent runs without depending on UI polling."""
    while True:
        time.sleep(TRAIN_WATCHDOG_INTERVAL_SECONDS)
        job = TRAIN_JOBS.get(job_id)
        if not job or job.get("status") != "running":
            return
        try:
            _check_train_stall(job_id)
        except Exception:
            pass
        if job.get("registry_finished"):
            return


def _start_train_watchdog(job_id: str) -> None:
    threading.Thread(
        target=_train_watchdog_loop,
        args=(job_id,),
        daemon=True,
        name=f"train-watchdog-{job_id[:8]}",
    ).start()


def _load_log_job(job_id: str) -> dict | None:
    """从日志文件重建已结束的训练任务（后端重启后仍可查看）。"""
    log_path = LOG_DIR / f"train_{job_id}.log"
    if not log_path.exists():
        return None
    return {
        "job_id": job_id,
        "output_name": _infer_output_name(),
        "status": "done",
        "log_path": str(log_path),
        "process": None,
        "error": None,
        "cancelled": False,
        "auto_convert": False,
        "converting": False,
        "convert_error": None,
        "created_at": "",
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(log_path.stat().st_mtime)),
    }


def _infer_output_name() -> str:
    """从输出目录推断最近的训练产物名称。"""
    candidates = [path for path in OUTPUT_DIR.glob("*.safetensors") if not path.name.endswith("_comfy.safetensors")]
    if not candidates:
        return ""
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    return re.sub(r"-\d+$", "", latest.stem)


def _output_name_conflicts(output_name: str) -> list[str]:
    """列出输出目录中会被该名称覆盖的既有产物。

    同一名称族包括 `{name}.safetensors`、`{name}-000001.safetensors` 及它们的
    `_comfy` 转换件，但不包括 `{name}2` 这类仅前缀相同的其他 LoRA。
    """
    name = output_name.strip()
    if not name or not OUTPUT_DIR.exists():
        return []
    exact = re.compile(rf"{re.escape(name)}(?:-\d+)?$")
    conflicts: list[str] = []
    for path in OUTPUT_DIR.glob("*.safetensors"):
        stem = path.name[: -len(".safetensors")]
        if stem.endswith("_comfy"):
            stem = stem[: -len("_comfy")]
        if exact.fullmatch(stem):
            conflicts.append(path.name)
    return sorted(conflicts)


def _suggest_output_name(output_name: str) -> str:
    """追加日期后缀生成不冲突的名称，必要时再追加序号。"""
    name = output_name.strip()
    if not name:
        return ""
    base = f"{name}_{time.strftime('%Y%m%d')}"
    candidate = base
    index = 2
    while _output_name_conflicts(candidate):
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def _convert_lora_for_comfy(src: Path) -> Path:
    """把 sd-scripts 格式 LoRA 转换为 ComfyUI 格式（必要时）。"""
    if src.name.endswith("_comfy.safetensors"):
        return src
    out = src.with_name(src.stem + "_comfy.safetensors")
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        subprocess.run(
            [str(KOYA_PY), str(CONVERT_SCRIPT), str(src), str(out)],
            cwd=str(TRAIN_SCRIPT.parent),
            capture_output=True,
            timeout=600,
            check=True,
        )
    return out


def _auto_convert_outputs(job: dict) -> None:
    """训练成功后把产物自动转换为 ComfyUI 格式。"""
    output_name = str(job.get("output_name") or "")
    try:
        candidates = [
            path
            for path in OUTPUT_DIR.glob("*.safetensors")
            if not path.name.endswith("_comfy.safetensors")
        ]
        if output_name:
            candidates = [path for path in candidates if path.name.startswith(output_name)]
        for path in sorted(candidates, key=lambda item: item.stat().st_mtime):
            _convert_lora_for_comfy(path)
    except Exception as exc:  # noqa: BLE001
        job["convert_error"] = str(exc)
    finally:
        job["converting"] = False


@router.get("/api/train/training")
def latest_training() -> dict:
    """返回最近一次训练任务状态。"""
    if not TRAIN_JOBS:
        persisted = database.list_train_jobs(limit=1)
        if persisted:
            job = persisted[0]
            log_path = LOG_DIR / f"train_{job['job_id']}.log"
            if log_path.exists():
                job["log_path"] = str(log_path)
            return _public_train_job(job)
        logs = sorted(LOG_DIR.glob("train_*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not logs:
            return {}
        job_id = logs[0].stem.split("_", 1)[1]
        job = _load_log_job(job_id)
        return _public_train_job(job) if job else {}
    job = max(TRAIN_JOBS.values(), key=lambda item: item.get("created_at") or "")
    return _public_train_job(job)


@router.get("/api/train/history")
def training_history(
    limit: int = Query(
        config.QUERY_TRAIN_HISTORY_LIMIT_DEFAULT,
        ge=config.QUERY_PAGE_MIN,
        le=config.QUERY_TRAIN_HISTORY_LIMIT_MAX,
    ),
) -> dict:
    """返回训练历史：完整参数 + 日志恢复的 Loss 曲线。"""
    rows = database.list_train_jobs(limit=limit)
    jobs: list[dict] = []
    for row in rows:
        if not row.get("log_path"):
            log_path = LOG_DIR / f"train_{row.get('job_id')}.log"
            if log_path.exists():
                row["log_path"] = str(log_path)
        public = _public_train_job(row)
        if public.get("dit"):
            public["dit"] = Path(str(public["dit"])).name
        jobs.append(public)
    return {"jobs": jobs}


@router.get("/api/train/output-name-check")
def check_output_name(output_name: str = Query("", max_length=200)) -> dict:
    """预检查训练产物名称是否会在输出目录覆盖既有文件。"""
    name = output_name.strip()
    if name and Path(name).name != name:
        raise HTTPException(status_code=400, detail="LoRA 名称不合法")
    conflicts = _output_name_conflicts(name)
    return {
        "output_name": name,
        "conflicts": conflicts,
        "suggested_name": _suggest_output_name(name) if conflicts else "",
    }


@router.post("/api/train/start")
def start_training(payload: dict = Body(...)) -> dict:
    """按界面配置启动 Anima LoRA 训练。"""
    with TRAIN_LOCK:
        if any(job["status"] == "running" for job in TRAIN_JOBS.values()):
            raise HTTPException(status_code=409, detail="已有训练任务在运行")
    other_tasks = [task for task in task_state.running_tasks() if task["type"] != "train"]
    if other_tasks:
        labels = "、".join(task["label"] for task in other_tasks)
        raise HTTPException(status_code=409, detail=f"有其他项目正在运行（{labels}），请稍后再进行")
    manual_confirmed = bool(payload.get("manual_confirmed", False))
    if AI_IMPORT_MARKER.exists():
        try:
            marker = json.loads(AI_IMPORT_MARKER.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            marker = {}
        if not marker.get("manual_confirmed_at"):
            if not manual_confirmed:
                raise HTTPException(
                    status_code=400,
                    detail="AI_IMPORT_REVIEW_REQUIRED: 数据集包含 AI 绘画产物，请先完成人工审核确认",
                )
            marker["manual_confirmed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            AI_IMPORT_MARKER.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_dit = str(payload.get("dit") or "").strip()
    output_name = str(payload.get("output_name") or "").strip()
    if not raw_dit:
        raise HTTPException(status_code=400, detail="请选择底模")
    dit_candidate = Path(raw_dit)
    dit_path = dit_candidate if dit_candidate.exists() else MODELS_DIR / dit_candidate.name
    if not dit_path.exists():
        raise HTTPException(status_code=400, detail="底模路径不存在")
    if not _is_net_format(dit_path):
        raise HTTPException(
            status_code=400,
            detail="该底模不是 net. 前缀格式，无法直接训练；请选择带 _net 后缀的转换版或 miaomiaoHarem_anima16.safetensors",
        )
    if not output_name or Path(output_name).name != output_name:
        raise HTTPException(status_code=400, detail="LoRA 名称不合法")
    conflicts = _output_name_conflicts(output_name)
    overwrite_output = bool(payload.get("overwrite_output", False))
    if conflicts and not overwrite_output:
        raise HTTPException(
            status_code=409,
            detail=(
                "OUTPUT_NAME_CONFLICT: 输出目录已有同名产物，继续训练会覆盖它们："
                + "、".join(conflicts)
            ),
        )
    if not TRAIN_SCRIPT.exists() or not ACCELERATE_EXE.exists():
        raise HTTPException(status_code=500, detail="Kohya_SS 训练环境缺失")
    if not QWEN3_PATH.exists() or not VAE_PATH.exists():
        raise HTTPException(status_code=500, detail="Qwen3 或 VAE 文件缺失")
    if not _image_files():
        raise HTTPException(status_code=400, detail="数据集没有图片")

    try:
        resolution = int(payload.get("resolution", config.TRAIN_DEFAULT_RESOLUTION))
        repeats = int(payload.get("repeats", config.TRAIN_DEFAULT_REPEATS))
        batch_size = int(payload.get("batch_size", config.TRAIN_DEFAULT_BATCH_SIZE))
        network_dim = int(payload.get("network_dim", config.TRAIN_DEFAULT_NETWORK_DIM))
        network_alpha = int(payload.get("network_alpha", config.TRAIN_DEFAULT_NETWORK_ALPHA))
        learning_rate = float(
            payload.get("learning_rate", config.TRAIN_DEFAULT_LEARNING_RATE)
        )
        epochs = int(payload.get("epochs", config.TRAIN_DEFAULT_EPOCHS))
        save_every = int(payload.get("save_every", config.TRAIN_DEFAULT_SAVE_EVERY))
        max_steps = int(payload.get("max_steps", config.TRAIN_DEFAULT_MAX_STEPS))
        optimizer_type = str(payload.get("optimizer_type") or "AdamW8bit")
        lr_scheduler = str(payload.get("lr_scheduler") or "cosine")
        mixed_precision = str(payload.get("mixed_precision") or "bf16")
        gradient_accumulation = int(payload.get("gradient_accumulation", 1))
        warmup_steps = int(payload.get("warmup_steps", 100))
        discrete_flow_shift = float(payload.get("discrete_flow_shift", 1.0))
        gradient_checkpointing = bool(payload.get("gradient_checkpointing", True))
        cache_latents = bool(payload.get("cache_latents", True))
        cache_latents_to_disk = bool(payload.get("cache_latents_to_disk", True))
        save_state = bool(payload.get("save_state", True))
        shuffle_caption = bool(payload.get("shuffle_caption", False))
        keep_tokens = int(payload.get("keep_tokens", 1))
        bucket_min_reso = int(payload.get("bucket_min_reso", 512))
        bucket_max_reso = int(payload.get("bucket_max_reso", 1536))
        bucket_reso_steps = int(payload.get("bucket_reso_steps", 64))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="训练参数格式不正确") from None

    checks = (
        ("分辨率", resolution, config.TRAIN_RESOLUTION_MIN, config.TRAIN_RESOLUTION_MAX),
        ("重复次数", repeats, config.TRAIN_REPEATS_MIN, config.TRAIN_REPEATS_MAX),
        ("训练 Batch", batch_size, config.TRAIN_BATCH_SIZE_MIN, config.TRAIN_BATCH_SIZE_MAX),
        ("network_dim", network_dim, config.TRAIN_NETWORK_DIM_MIN, config.TRAIN_NETWORK_DIM_MAX),
        (
            "network_alpha",
            network_alpha,
            config.TRAIN_NETWORK_ALPHA_MIN,
            config.TRAIN_NETWORK_ALPHA_MAX,
        ),
        (
            "学习率",
            learning_rate,
            config.TRAIN_LEARNING_RATE_MIN,
            config.TRAIN_LEARNING_RATE_MAX,
        ),
        ("训练轮数", epochs, config.TRAIN_EPOCHS_MIN, config.TRAIN_EPOCHS_MAX),
        ("保存间隔", save_every, config.TRAIN_SAVE_EVERY_MIN, config.TRAIN_SAVE_EVERY_MAX),
        ("最大步数", max_steps, config.TRAIN_MAX_STEPS_MIN, config.TRAIN_MAX_STEPS_MAX),
    )
    for label, value, minimum, maximum in checks:
        if value < minimum or value > maximum:
            raise HTTPException(
                status_code=400,
                detail=f"{label}必须在 {_plain_decimal(minimum)}-{_plain_decimal(maximum)} 之间",
            )
    if optimizer_type not in TRAIN_OPTIMIZERS:
        raise HTTPException(status_code=400, detail="优化器参数不受支持")
    if lr_scheduler not in TRAIN_LR_SCHEDULERS:
        raise HTTPException(status_code=400, detail="学习率调度器参数不受支持")
    if mixed_precision not in TRAIN_MIXED_PRECISIONS:
        raise HTTPException(status_code=400, detail="混合精度参数不受支持")
    if not 1 <= gradient_accumulation <= 64:
        raise HTTPException(status_code=400, detail="梯度累积必须在 1-64 之间")
    if not 0 <= warmup_steps <= 100000:
        raise HTTPException(status_code=400, detail="Warmup Steps 必须在 0-100000 之间")
    if not 0.1 <= discrete_flow_shift <= 10:
        raise HTTPException(status_code=400, detail="Discrete Flow Shift 必须在 0.1-10 之间")
    if not 0 <= keep_tokens <= 100:
        raise HTTPException(status_code=400, detail="Keep Tokens 必须在 0-100 之间")
    if not 256 <= bucket_min_reso <= bucket_max_reso <= 4096:
        raise HTTPException(status_code=400, detail="Bucket 分辨率范围无效")
    if not 8 <= bucket_reso_steps <= 256:
        raise HTTPException(status_code=400, detail="Bucket 步长必须在 8-256 之间")
    if cache_latents_to_disk and not cache_latents:
        raise HTTPException(status_code=400, detail="缓存到磁盘前必须先启用 Latents 缓存")

    TRAIN_DATASET_CONFIG.write_text(
        _dataset_config_text(
            resolution=resolution,
            batch_size=batch_size,
            repeats=repeats,
            shuffle_caption=shuffle_caption,
            keep_tokens=keep_tokens,
            bucket_min_reso=bucket_min_reso,
            bucket_max_reso=bucket_max_reso,
            bucket_reso_steps=bucket_reso_steps,
            image_dir=DATASET_DIR,
        ),
        encoding="utf-8",
    )
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    log_path = LOG_DIR / f"train_{job_id}.log"
    cmd = [
        str(ACCELERATE_EXE),
        "launch",
        "--num_cpu_threads_per_process",
        "1",
        str(TRAIN_SCRIPT),
        "--pretrained_model_name_or_path",
        str(dit_path),
        "--qwen3",
        str(QWEN3_PATH),
        "--vae",
        str(VAE_PATH),
        "--dataset_config",
        str(TRAIN_DATASET_CONFIG),
        "--output_dir",
        str(OUTPUT_DIR),
        "--output_name",
        output_name,
        "--save_model_as",
        "safetensors",
        "--network_module",
        "networks.lora_anima",
        "--network_dim",
        str(network_dim),
        "--network_alpha",
        str(network_alpha),
        "--learning_rate",
        _plain_decimal(learning_rate),
        "--optimizer_type",
        optimizer_type,
        "--lr_scheduler",
        lr_scheduler,
        "--timestep_sampling",
        "sigmoid",
        "--discrete_flow_shift",
        _plain_decimal(discrete_flow_shift),
        "--max_train_epochs",
        str(epochs),
        "--save_every_n_epochs",
        str(save_every),
        "--mixed_precision",
        mixed_precision,
        "--qwen_image_vae_2d",
        "--vae_chunk_size",
        "64",
        "--vae_disable_cache",
    ]
    if warmup_steps > 0:
        cmd += ["--lr_warmup_steps", str(warmup_steps)]
    if gradient_accumulation > 1:
        cmd += ["--gradient_accumulation_steps", str(gradient_accumulation)]
    if gradient_checkpointing:
        cmd.append("--gradient_checkpointing")
    if cache_latents:
        cmd.append("--cache_latents")
    if cache_latents_to_disk:
        cmd.append("--cache_latents_to_disk")
    if save_state:
        # 保存训练状态（含优化器动量与 LR 进度）：出问题时可凭 *-state 目录精确续训，最多损失一轮。
        # 只保留最近 2 份，避免每轮都留一份状态目录把磁盘堆满。
        cmd += ["--save_state", "--save_last_n_epochs_state", "2"]
    if max_steps > 0:
        cmd += ["--max_train_steps", str(max_steps)]
    # Windows 上 dataloader worker 在 epoch 边界重建时可能因 torch shm.dll
    # 初始化失败（WinError 1114）而让主进程永久等待。0 worker 在当前数据量下
    # 速度几乎无损失（实测约 3.5s/step），稳定性优先。
    cmd += ["--max_data_loader_n_workers", "0"]
    _write_train_sidecar(
        job_id,
        cmd=cmd,
        output_name=output_name,
        auto_convert=bool(payload.get("auto_convert", False)),
        cwd=str(TRAIN_SCRIPT.parent),
    )

    env = os.environ.copy()
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # Windows 版 xformers 没有 triton，显式关闭可避免每个子进程都打印一次导入堆栈。
    env.setdefault("XFORMERS_FORCE_DISABLE_TRITON", "1")
    with open(log_path, "w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            cmd,
            cwd=str(TRAIN_SCRIPT.parent),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    TRAIN_JOBS[job_id] = {
        "job_id": job_id,
        "output_name": output_name,
        "overwrite_output": overwrite_output,
        "status": "running",
        "log_path": str(log_path),
        "process": proc,
        "error": None,
        "cancelled": False,
        "auto_convert": bool(payload.get("auto_convert", False)),
        "converting": False,
        "convert_error": None,
        "watch_started": True,
        "registry_finished": False,
        "dit": str(dit_path),
        "resolution": resolution,
        "repeats": repeats,
        "batch_size": batch_size,
        "network_dim": network_dim,
        "network_alpha": network_alpha,
        "learning_rate": learning_rate,
        "epochs": epochs,
        "save_every": save_every,
        "max_steps": max_steps,

        "optimizer_type": optimizer_type,

        "lr_scheduler": lr_scheduler,

        "mixed_precision": mixed_precision,

        "gradient_accumulation": gradient_accumulation,

        "warmup_steps": warmup_steps,

        "discrete_flow_shift": discrete_flow_shift,

        "gradient_checkpointing": gradient_checkpointing,

        "cache_latents": cache_latents,

        "cache_latents_to_disk": cache_latents_to_disk,

        "save_state": save_state,

        "shuffle_caption": shuffle_caption,

        "keep_tokens": keep_tokens,

        "bucket_min_reso": bucket_min_reso,

        "bucket_max_reso": bucket_max_reso,

        "bucket_reso_steps": bucket_reso_steps,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None,
    }
    database.save_train_job(TRAIN_JOBS[job_id])
    task_registry.register("train", job_id, resources=task_resources.for_kind("train"))
    threading.Thread(
        target=_watch_train_process,
        args=(job_id,),
        daemon=True,
        name=f"train-watch-{job_id[:8]}",
    ).start()
    _start_train_watchdog(job_id)
    return {"job_id": job_id, "status": "running"}


@router.get("/api/train/training/{job_id}")
def training_status(job_id: str) -> dict:
    """查询指定训练任务状态。"""
    job = TRAIN_JOBS.get(job_id)
    if not job:
        job = database.get_train_job(job_id)
        if job:
            log_path = LOG_DIR / f"train_{job_id}.log"
            if log_path.exists():
                job["log_path"] = str(log_path)
            return _public_train_job(job)
        job = _load_log_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return _public_train_job(job)


@router.post("/api/train/training/{job_id}/resume")
def resume_training(job_id: str) -> dict:
    """Stop a stalled run and restart it from its latest complete state."""
    job = TRAIN_JOBS.get(job_id) or database.get_train_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    output_name = str(job.get("output_name") or "")
    sidecar = _read_train_sidecar(job_id)
    if not sidecar or not sidecar.get("cmd"):
        raise HTTPException(
            status_code=400,
            detail="该任务没有保存续训命令；从下一次训练起会自动保存，旧任务请手动续训。",
        )
    if not output_name:
        output_name = str(sidecar.get("output_name") or "")
    state = _latest_resume_state(output_name) if output_name else None
    if state is None:
        raise HTTPException(status_code=400, detail="没有找到完整的 *-state 检查点，无法续训")
    other_running = [
        item for key, item in TRAIN_JOBS.items()
        if key != job_id and item.get("status") == "running"
    ]
    if other_running:
        raise HTTPException(status_code=409, detail="还有另一个训练任务在运行，先停止它再续训")

    try:
        steps_offset = int(_public_train_job(job).get("steps_done") or 0)
    except Exception:
        steps_offset = 0

    old_proc = job.get("process")
    if old_proc is not None and old_proc.poll() is None:
        job["cancelled"] = True
        try:
            subprocess.run(
                ["taskkill", "/PID", str(old_proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
            )
        except Exception:
            old_proc.terminate()
        try:
            old_proc.wait(timeout=15)
        except Exception:
            old_proc.kill()
        job["status"] = "stopped"
        job["error"] = "为续训停止卡死进程"
        job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        job["registry_finished"] = True
        try:
            task_registry.finish("train", job_id, "stopped", job["error"])
        except Exception:
            pass
        try:
            database.save_train_job(job)
        except Exception:
            pass

    new_id = uuid.uuid4().hex
    log_path = LOG_DIR / f"train_{new_id}.log"
    new_cmd = _resume_command(list(sidecar.get("cmd") or []), state)
    if len(new_cmd) < 2:
        raise HTTPException(status_code=400, detail="续训命令为空")
    _write_train_sidecar(
        new_id,
        cmd=new_cmd,
        output_name=output_name,
        auto_convert=bool(sidecar.get("auto_convert", False)),
        cwd=str(sidecar.get("cwd") or TRAIN_SCRIPT.parent),
        resumed_from=str(state),
        steps_offset=steps_offset,
    )
    env = os.environ.copy()
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("XFORMERS_FORCE_DISABLE_TRITON", "1")
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                new_cmd,
                cwd=str(sidecar.get("cwd") or TRAIN_SCRIPT.parent),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"续训进程启动失败：{exc}") from exc

    new_job = {
        "job_id": new_id,
        "output_name": output_name,
        "overwrite_output": True,
        "status": "running",
        "log_path": str(log_path),
        "process": proc,
        "error": None,
        "cancelled": False,
        "auto_convert": bool(sidecar.get("auto_convert", False)),
        "converting": False,
        "convert_error": None,
        "watch_started": True,
        "registry_finished": False,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None,
        "resumed_from": str(state),
        "steps_offset": steps_offset,
    }
    TRAIN_JOBS[new_id] = new_job
    try:
        task_registry.register("train", new_id, resources=task_resources.for_kind("train"))
    except Exception as exc:
        proc.kill()
        TRAIN_JOBS.pop(new_id, None)
        raise HTTPException(status_code=409, detail=f"续训资源冲突：{exc}") from exc
    database.save_train_job(new_job)
    threading.Thread(
        target=_watch_train_process,
        args=(new_id,),
        daemon=True,
        name=f"train-watch-{new_id[:8]}",
    ).start()
    _start_train_watchdog(new_id)
    return {
        "job_id": new_id,
        "status": "running",
        "resume_state": str(state),
    }


@router.post("/api/train/training/stop")
def stop_training(payload: dict = Body(...)) -> dict:
    """停止训练进程及其子进程。"""
    job_id = str(payload.get("job_id") or "")
    job = TRAIN_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    job["cancelled"] = True
    proc = job.get("process")
    if proc and proc.poll() is None:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            proc.terminate()
    return {"ok": True}


@router.get("/api/train/outputs")
def training_outputs() -> dict:
    """列出训练输出目录中的 LoRA 产物。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(OUTPUT_DIR.glob("*.safetensors"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "size_mb": round(stat.st_size / 1024 / 1024, 1),
                "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
            }
        )
    return {"items": items}


@router.delete("/api/train/outputs/{filename}")
def delete_training_output(filename: str) -> dict:
    """删除输出目录中的指定训练产物。"""
    if not filename or Path(filename).name != filename or not filename.endswith(".safetensors"):
        raise HTTPException(status_code=400, detail="文件名不合法")
    path = OUTPUT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="训练产物不存在")
    path.unlink(missing_ok=True)
    return {"ok": True}


@router.post("/api/train/copy-lora")
def copy_lora(payload: dict = Body(...)) -> dict:
    """把训练产物转换为 ComfyUI 格式后复制到 LoRA 目录。"""
    filename = str(payload.get("filename") or "")
    if not filename or Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="文件名不合法")
    src = OUTPUT_DIR / filename
    if not src.exists():
        raise HTTPException(status_code=404, detail="训练产物不存在")
    src = _convert_lora_for_comfy(src)
    LORAS_DIR.mkdir(parents=True, exist_ok=True)
    dest = LORAS_DIR / src.name
    shutil.copy2(src, dest)
    return {"ok": True, "path": str(dest), "filename": src.name}


@router.post("/api/train/convert-lora")
def convert_lora(payload: dict = Body(...)) -> dict:
    """把指定训练产物转换为 ComfyUI 格式。"""
    filename = str(payload.get("filename") or "")
    if not filename or Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="文件名不合法")
    src = OUTPUT_DIR / filename
    if not src.exists():
        raise HTTPException(status_code=404, detail="训练产物不存在")
    converted = _convert_lora_for_comfy(src)
    return {"ok": True, "filename": converted.name, "path": str(converted)}


def _review_image(path: Path) -> dict:
    """用 qwen2.5vl 判断单张图片是否明显崩坏。"""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    prompt_text = (
        "请判断这张图片是否存在明显崩坏（如畸形手指、面部崩坏、多余肢体、重影、模糊、明显伪影）。"
        '只输出 JSON：{"ok": true/false, "issues": ["问题1", "问题2"]}，无明显问题则 issues 为空数组。'
    )
    response = requests.post(
        OLLAMA_BASE + "/api/generate",
        json={
            "model": database.get_setting("vlm_model", config.VLM_MODEL) or config.VLM_MODEL,
            "prompt": prompt_text,
            "images": [encoded],
            "stream": False,
            "options": {"num_predict": 120, "num_ctx": 8192},
        },
        timeout=180,
    )
    response.raise_for_status()
    text = (response.json().get("response") or "").strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:].strip()
    data = json.loads(text)
    issues = [str(item) for item in (data.get("issues") or [])]
    return {"ok": bool(data.get("ok", True)), "issues": issues}


def _run_review(job_id: str, filenames: list[str]) -> None:
    job = REVIEW_JOBS[job_id]
    try:
        images = [
            path
            for path in sorted(DATASET_DIR.iterdir())
            if path.is_file() and path.suffix.lower() in IMAGE_EXTS and (not filenames or path.name in filenames)
        ]
        job["total"] = len(images)
        task_registry.update("review", job_id, total=len(images))
        for path in images:
            try:
                result = _review_image(path)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "issues": [f"审查失败：{exc}"]}
            job["results"].append({"filename": path.name, **result})
            job["done"] += 1
            task_registry.update("review", job_id, done=job["done"], current=path.name)
        job["status"] = "done"
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(exc)
    finally:
        job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        task_registry.finish("review", job_id, job["status"], job.get("error"))


def _write_import_marker(files: list[str], confirmed: bool = False) -> None:
    marker: dict = {}
    if AI_IMPORT_MARKER.exists():
        try:
            marker = json.loads(AI_IMPORT_MARKER.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            marker = {}
    marker["files"] = files
    if confirmed:
        marker["manual_confirmed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    else:
        marker.pop("manual_confirmed_at", None)
    AI_IMPORT_MARKER.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")


@router.post("/api/train/dataset/review")
def start_dataset_review(payload: dict = Body(...)) -> dict:
    """启动 AI 审查：批量判断训练图片是否明显崩坏。"""
    raw = payload.get("filenames") or []
    filenames = [str(name) for name in raw if Path(str(name)).name == str(name)]
    with REVIEW_LOCK:
        if any(job["status"] == "running" for job in REVIEW_JOBS.values()):
            raise HTTPException(status_code=409, detail="已有审查任务在运行")
    other_tasks = [task for task in task_state.running_tasks() if task["type"] != "review"]
    if other_tasks:
        labels = "、".join(task["label"] for task in other_tasks)
        raise HTTPException(status_code=409, detail=f"有其他项目正在运行（{labels}），请稍后再进行")
    job_id = uuid.uuid4().hex
    REVIEW_JOBS[job_id] = {
        "job_id": job_id,
        "status": "running",
        "total": 0,
        "done": 0,
        "results": [],
        "error": None,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None,
    }
    task_registry.register("review", job_id, resources=task_resources.for_kind("review"))
    threading.Thread(target=_run_review, args=(job_id, filenames), daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@router.get("/api/train/dataset/review/{job_id}")
def dataset_review_status(job_id: str) -> dict:
    """查询 AI 审查进度与结果。"""
    job = REVIEW_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {key: value for key, value in job.items() if key != "process"}


@router.post("/api/train/dataset/exclude")
def exclude_dataset_image(payload: dict = Body(...)) -> dict:
    """把指定图片移出数据集（不删除，放入 excluded）。"""
    filename = str(payload.get("filename") or "")
    if not filename or Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="文件名不合法")
    src = DATASET_DIR / filename
    if not src.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    EXCLUDED_DIR.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(EXCLUDED_DIR / filename))
    return {"ok": True}


@router.post("/api/train/dataset/restore")
def restore_dataset_image(payload: dict = Body(...)) -> dict:
    """把 excluded 中的图片恢复回数据集。"""
    filename = str(payload.get("filename") or "")
    if not filename or Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="文件名不合法")
    src = EXCLUDED_DIR / filename
    if not src.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    shutil.move(str(src), str(DATASET_DIR / filename))
    return {"ok": True}


@router.get("/api/train/dataset/image/{filename}")
def get_dataset_image(filename: str) -> Response:
    """提供训练数据集图片访问（仅限数据集目录内文件）。"""
    safe_name = Path(filename).name
    path = DATASET_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="image not found")
    return Response(path.read_bytes(), media_type="image/png")


@router.post("/api/train/dataset/exclude-many")
def exclude_dataset_images(payload: dict = Body(...)) -> dict:
    """批量把指定图片移出数据集到 excluded。"""
    raw = payload.get("filenames") or []
    if not raw:
        raise HTTPException(status_code=400, detail="请选择要移出的图片")
    EXCLUDED_DIR.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = Path(str(item)).name
        if name in seen or not name:
            continue
        seen.add(name)
        src = DATASET_DIR / name
        if not src.exists():
            skipped.append(name)
            continue
        shutil.move(str(src), str(EXCLUDED_DIR / name))
        moved.append(name)
    return {"ok": True, "moved": moved, "skipped": skipped}


@router.post("/api/train/dataset/delete")
def delete_dataset_image(payload: dict = Body(...)) -> dict:
    """永久删除数据集中的图片及同名标签文件。"""
    filename = str(payload.get("filename") or "")
    if not filename or Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="文件名不合法")
    image = DATASET_DIR / filename
    if not image.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    image.unlink(missing_ok=True)
    caption = image.with_suffix(".txt")
    caption.unlink(missing_ok=True)
    return {"ok": True}


SIGNATURE_KEYWORDS = ("signature", "watermark", "artist name", "artist logo", "logo", "text", "brand")


@router.get("/api/train/dataset/signature-scan")
def signature_scan() -> dict:
    """扫描数据集标签中可能包含签名/水印/文字 Logo 的图片。"""
    items: list[dict] = []
    for caption_path in sorted(DATASET_DIR.glob("*.txt")):
        try:
            text = caption_path.read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            continue
        matched = [keyword for keyword in SIGNATURE_KEYWORDS if keyword in text]
        if not matched:
            continue
        image_name = next(
            (path.name for ext in IMAGE_EXTS if (caption_path.with_suffix(ext)).exists()),
            caption_path.stem + ".png",
        )
        items.append({"filename": image_name, "caption_name": caption_path.name, "matched": matched})
    return {"items": items}


@router.post("/api/train/dataset/import-images")
def import_library_images(payload: dict = Body(...)) -> dict:
    """把 AI 绘画图片库中的图片复制进训练数据集并记录来源标记。"""
    raw = payload.get("filenames") or []
    if not raw:
        raise HTTPException(status_code=400, detail="请选择要导入的图片")
    imported: list[str] = []
    skipped: list[str] = []
    for item in raw:
        name = Path(str(item)).name
        if not name:
            continue
        src = AI_PRODUCT_DIR / name
        if not src.exists() or not src.is_file():
            skipped.append(name)
            continue
        dst = DATASET_DIR / name
        if dst.exists():
            skipped.append(name)
            continue
        shutil.copy2(src, dst)
        imported.append(name)
    if imported:
        marker_files: list[str] = []
        if AI_IMPORT_MARKER.exists():
            try:
                marker_files = list(json.loads(AI_IMPORT_MARKER.read_text(encoding="utf-8")).get("files") or [])
            except (json.JSONDecodeError, OSError):
                marker_files = []
        for name in imported:
            if name not in marker_files:
                marker_files.append(name)
        _write_import_marker(marker_files)
    return {"ok": True, "imported": imported, "skipped": skipped}


def _run_merge(job_id: str, source_a: Path, source_b: Path, output: Path, ratio_a: float, ratio_b: float) -> None:
    job = MERGE_JOBS[job_id]
    try:
        proc = subprocess.run(
            [
                str(KOYA_PY),
                str(MERGE_SCRIPT),
                str(source_a),
                str(source_b),
                str(output),
                "--ratio-turbo",
                str(ratio_a),
                "--ratio-style",
                str(ratio_b),
                "--save-precision",
                "bf16",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-500:] or "合并失败")
        job["status"] = "done"
        job["output_file"] = output.name
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(exc)
    finally:
        job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        task_registry.update("merge", job_id, done=1)
        task_registry.finish("merge", job_id, job["status"], job.get("error"))


@router.post("/api/train/merge-lora")
def start_lora_merge(payload: dict = Body(...)) -> dict:
    """一键合并两个 LoRA（异步），产物直接写入 ComfyUI LoRA 目录。"""
    source_a = str(payload.get("source_a") or "").strip()
    source_b = str(payload.get("source_b") or "").strip()
    output_name = str(payload.get("output_name") or "").strip()
    if not source_a or not source_b or not output_name:
        raise HTTPException(status_code=400, detail="源文件与输出名不能为空")
    if source_a == source_b:
        raise HTTPException(status_code=400, detail="源文件不能相同")
    if Path(source_a).name != source_a or Path(source_b).name != source_b or Path(output_name).name != output_name:
        raise HTTPException(status_code=400, detail="文件名不合法")
    if not output_name.endswith(".safetensors"):
        output_name += ".safetensors"
    path_a = LORAS_DIR / source_a
    path_b = LORAS_DIR / source_b
    out_path = LORAS_DIR / output_name
    if not path_a.exists() or not path_b.exists():
        raise HTTPException(status_code=404, detail="源 LoRA 文件不存在")
    if out_path.exists() and not bool(payload.get("overwrite", False)):
        raise HTTPException(status_code=409, detail="输出文件已存在，请更换名称或允许覆盖")
    with MERGE_LOCK:
        if any(job["status"] == "running" for job in MERGE_JOBS.values()):
            raise HTTPException(status_code=409, detail="已有合并任务在运行")
    other_tasks = [task for task in task_state.running_tasks() if task["type"] != "merge"]
    if other_tasks:
        labels = "、".join(task["label"] for task in other_tasks)
        raise HTTPException(status_code=409, detail=f"有其他项目正在运行（{labels}），请稍后再进行")
    try:
        ratio_a = float(payload.get("ratio_a", config.TRAIN_MERGE_RATIO_DEFAULT))
        ratio_b = float(payload.get("ratio_b", config.TRAIN_MERGE_RATIO_DEFAULT))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="合并比例格式不正确") from None
    for label, ratio in (("比例 A", ratio_a), ("比例 B", ratio_b)):
        if not config.TRAIN_MERGE_RATIO_MIN <= ratio <= config.TRAIN_MERGE_RATIO_MAX:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{label}必须在 {config.TRAIN_MERGE_RATIO_MIN:g}-"
                    f"{config.TRAIN_MERGE_RATIO_MAX:g} 之间"
                ),
            )
    job_id = uuid.uuid4().hex
    MERGE_JOBS[job_id] = {
        "job_id": job_id,
        "status": "running",
        "output_file": None,
        "error": None,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None,
    }
    task_registry.register(
        "merge",
        job_id,
        payload={
            "source_a": source_a,
            "source_b": source_b,
            "output_name": output_name,
        },
        resources=task_resources.for_kind("merge"),
    )
    threading.Thread(
        target=_run_merge,
        args=(
            job_id,
            path_a,
            path_b,
            out_path,
            ratio_a,
            ratio_b,
        ),
        daemon=True,
    ).start()
    return {"job_id": job_id, "status": "running"}


@router.get("/api/train/merge/{job_id}")
def merge_status(job_id: str) -> dict:
    """查询 LoRA 合并任务状态。"""
    job = MERGE_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return dict(job)


def _run_compare(job_id: str) -> None:
    job = COMPARE_JOBS[job_id]
    try:
        for name in job["loras"]:
            if job.get("stop_requested"):
                job["status"] = "stopped"
                return
            try:
                combo = [c for c in job.get("combo_loras") or [] if c != name]
                if job.get("skip_turbo_duplicate", True) and "turbo" in name.lower():
                    combo = [c for c in combo if "turbo" not in c.lower()]
                loras = combo + [name]
                strengths: dict[str, dict[str, float]] = {}
                for combo_name in combo:
                    strengths[combo_name] = job.get("combo_strengths", {}).get(
                        combo_name,
                        {
                            "model": config.DRAW_DEFAULT_LORA_STRENGTH_MODEL,
                            "clip": config.DRAW_DEFAULT_LORA_STRENGTH_CLIP,
                        },
                    )
                strengths[name] = {
                    "model": config.DRAW_DEFAULT_LORA_STRENGTH_MODEL,
                    "clip": config.DRAW_DEFAULT_LORA_STRENGTH_CLIP,
                }
                result = generate(
                    prompt=job["prompt"],
                    negative_prompt=job["negative_prompt"],
                    width=job["width"],
                    height=job["height"],
                    steps=job["steps"],
                    cfg=job["cfg"],
                    loras=loras,
                    lora_strengths=strengths,
                    seed=job.get("seed"),
                    timeout=300,
                    output_dir=str(config.COMPARE_OUTPUT_DIR),
                )
                job["results"].append(
                    {
                        "name": name,
                        "combo": combo,
                        "image_url": result.get("image_url"),
                        "saved_path": result.get("saved_path"),
                        "seed": result.get("seed"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                job["results"].append({"name": name, "error": str(exc)})
            job["done"] += 1
        if job["status"] != "stopped":
            job["status"] = "done"
    except Exception as exc:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(exc)
    finally:
        job["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        task_registry.finish("compare", job_id, job["status"], job.get("error"))


@router.post("/api/train/compare-generate")
def start_compare_generate(payload: dict = Body(...)) -> dict:
    """一键对比出图：固定参数串行生成每个训练产物的测试图。"""
    prompt = str(payload.get("prompt") or "").strip()
    raw_loras = payload.get("loras") or []
    loras = [str(name) for name in raw_loras if Path(str(name)).name == str(name)]
    if not prompt:
        raise HTTPException(status_code=400, detail="测试提示词不能为空")
    if not loras:
        raise HTTPException(status_code=400, detail="请选择要对比的 LoRA")
    missing = [name for name in loras if not (LORAS_DIR / name).exists()]
    if missing:
        raise HTTPException(status_code=404, detail=f"以下 LoRA 不存在：{', '.join(missing)}")
    raw_combo = payload.get("combo_loras") or []
    combo_loras = [str(name) for name in raw_combo if Path(str(name)).name == str(name)]
    missing_combo = [name for name in combo_loras if not (LORAS_DIR / name).exists()]
    if missing_combo:
        raise HTTPException(status_code=404, detail=f"以下固定搭配 LoRA 不存在：{', '.join(missing_combo)}")
    combo_strengths: dict[str, dict[str, float]] = {}
    raw_strengths = payload.get("combo_strengths") or {}
    if isinstance(raw_strengths, dict):
        for key, value in raw_strengths.items():
            combo_name = Path(str(key)).name
            if combo_name not in combo_loras:
                continue
            try:
                combo_strengths[combo_name] = {
                    "model": float(
                        (value or {}).get("model", config.DRAW_DEFAULT_LORA_STRENGTH_MODEL)
                    ),
                    "clip": float(
                        (value or {}).get("clip", config.DRAW_DEFAULT_LORA_STRENGTH_CLIP)
                    ),
                }
            except (TypeError, ValueError):
                combo_strengths[combo_name] = {
                    "model": config.DRAW_DEFAULT_LORA_STRENGTH_MODEL,
                    "clip": config.DRAW_DEFAULT_LORA_STRENGTH_CLIP,
                }
    for combo_name in combo_loras:
        combo_strengths.setdefault(
            combo_name,
            {
                "model": config.DRAW_DEFAULT_LORA_STRENGTH_MODEL,
                "clip": config.DRAW_DEFAULT_LORA_STRENGTH_CLIP,
            },
        )
    other_tasks = [task for task in task_state.running_tasks() if task["type"] != "compare"]
    if other_tasks:
        labels = "、".join(task["label"] for task in other_tasks)
        raise HTTPException(status_code=409, detail=f"有其他项目正在运行（{labels}），请稍后再进行")
    with COMPARE_LOCK:
        if any(job["status"] == "running" for job in COMPARE_JOBS.values()):
            raise HTTPException(status_code=409, detail="已有对比出图任务在运行")
    try:
        steps = int(payload.get("steps", config.COMPARE_DEFAULT_STEPS))
        width = int(payload.get("width", config.COMPARE_DEFAULT_WIDTH))
        height = int(payload.get("height", config.COMPARE_DEFAULT_HEIGHT))
        cfg = float(payload.get("cfg", config.COMPARE_DEFAULT_CFG))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="尺寸/步数/CFG 格式不正确")
    if not config.COMPARE_WIDTH_MIN <= width <= config.COMPARE_WIDTH_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"宽度必须在 {config.COMPARE_WIDTH_MIN}-{config.COMPARE_WIDTH_MAX} 之间",
        )
    if not config.COMPARE_HEIGHT_MIN <= height <= config.COMPARE_HEIGHT_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"高度必须在 {config.COMPARE_HEIGHT_MIN}-{config.COMPARE_HEIGHT_MAX} 之间",
        )
    if not config.COMPARE_STEPS_MIN <= steps <= config.COMPARE_STEPS_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"步数必须在 {config.COMPARE_STEPS_MIN}-{config.COMPARE_STEPS_MAX} 之间",
        )
    if not config.COMPARE_CFG_MIN <= cfg <= config.COMPARE_CFG_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"CFG 必须在 {config.COMPARE_CFG_MIN:g}-{config.COMPARE_CFG_MAX:g} 之间",
        )
    job_id = uuid.uuid4().hex
    COMPARE_JOBS[job_id] = {
        "job_id": job_id,
        "status": "running",
        "prompt": prompt,
        "negative_prompt": str(payload.get("negative_prompt") or ""),
        "width": width,
        "height": height,
        "steps": steps,
        "cfg": cfg,
        "seed": payload.get("seed"),
        "loras": loras,
        "combo_loras": combo_loras,
        "combo_strengths": combo_strengths,
        "skip_turbo_duplicate": bool(payload.get("skip_turbo_duplicate", True)),
        "total": len(loras),
        "done": 0,
        "results": [],
        "error": None,
        "stop_requested": False,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None,
    }
    task_registry.register("compare", job_id, total=len(loras), resources=task_resources.for_kind("compare"))
    threading.Thread(target=_run_compare, args=(job_id,), daemon=True).start()
    return {"job_id": job_id, "status": "running"}


@router.get("/api/train/compare/{job_id}")
def compare_status(job_id: str) -> dict:
    """查询一键对比出图任务进度。"""
    job = COMPARE_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        key: value
        for key, value in job.items()
        if key not in ("loras", "combo_loras", "combo_strengths", "prompt", "negative_prompt")
    }


@router.post("/api/train/compare/{job_id}/stop")
def stop_compare(job_id: str) -> dict:
    """停止一键对比出图任务。"""
    job = COMPARE_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    job["stop_requested"] = True
    return {"ok": True}
