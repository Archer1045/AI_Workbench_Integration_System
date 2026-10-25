"""AI 绘画接口：模型/LoRA 列表、图片访问、单张与批量绘画。"""
from __future__ import annotations

import base64
import io
import json
import random
import re
import requests
import subprocess
import threading
import time
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from PIL import Image, ImageOps, UnidentifiedImageError

import content_filter
import config
import database
import prompt_document
import task_state
import task_registry
import task_resources
from comfy_worker import (
    DEFAULT_MODEL,
    LORAS_DIR,
    _read_safetensors_header,
    classify_lora_purpose,
    generate,
    generate_inpaint,
    list_diffusion_models,
    list_loras,
)
from routers.chat import translate_text
from routers.settings_router import content_restriction_enabled, visual_review_enabled

router = APIRouter()

AI_PRODUCT_DIR = config.AI_PRODUCT_DIR
OLLAMA_BASE = config.OLLAMA_BASE
VLM_MODEL = config.VLM_MODEL
VLM_COUNT_MODEL = config.VLM_COUNT_MODEL
DE_MOSAIC_TAGS = "mosaic_censored, bar_censor, text_censor, censored, censor, censor_bar, blur_censor, pixelated, mosaic, censorship"
GROUP_NEGATIVE_TAGS = (
    "mirror",
    "reflection",
    "glass",
    "transparent body",
    "ghost",
    "duplicate",
    "extra person",
    "crowd",
    "split screen",
    "comic panel",
    "collage",
    "multiple views",
    "extra limbs",
    "fused bodies",
)
GROUP_COUNT_MIN = config.DRAW_GROUP_COUNT_MIN
MAX_GROUP_COUNT = config.DRAW_MAX_GROUP_COUNT
MAX_TOTAL_COUNT = config.DRAW_MAX_TOTAL_COUNT
MAX_GENERATE_RETRIES = 2
MAX_PEOPLE_GUARD_RETRIES = 1
MAX_GROUP_CANDIDATES = 3
PEOPLE_GUARD_MIN_COUNT = 2
VLM_COUNT_CONFIDENCE_KEY = "count_confident"
COUNTER_IMAGE_MAX_SIDE = 1280
COUNTER_IMAGE_JPEG_QUALITY = 92
GROUP_POSE_MARKERS = (
    "threesome",
    "group sex",
    "orgy",
    "gangbang",
    "double penetration",
    "double vaginal",
    "spitroast",
    "train-style",
    "multiple people",
)
PROTECT_THRESHOLD = 50

INPAINT_SOURCE_DIR = AI_PRODUCT_DIR / "inpaint" / "sources"
INPAINT_MASK_DIR = AI_PRODUCT_DIR / "inpaint" / "masks"
INPAINT_JOBS: dict[str, dict] = {}
INPAINT_LOCK = threading.Lock()
INPAINT_MAX_SOURCE_BYTES = 20 * 1024 * 1024
INPAINT_MAX_SIDE = 4096
INPAINT_MIN_SIDE = 64
INPAINT_MAX_MASK_BASE64 = 30 * 1024 * 1024
INPAINT_SOURCE_RE = re.compile(r"^src_[0-9a-f]{32}$")

# 批量绘画任务缓存（内存）
BATCH_JOBS: dict[str, dict] = {}
BATCH_LOCK = threading.Lock()
ACTIVE_BATCH_LOCK = threading.Lock()
ACTIVE_BATCH_ID: str | None = None


def _validate_lora_compatibility(loras: list) -> None:
    """拦截 Wan/视频架构 LoRA，避免 Anima/Qwen 绘画链路加载报错。"""
    bad: list[str] = []
    for raw_name in loras:
        name = str(raw_name or "")
        fname = name if name.endswith(".safetensors") else name + ".safetensors"
        path = LORAS_DIR / fname
        if not path.exists():
            continue
        metadata, keys = _read_safetensors_header(path)
        _, compatible, reason = classify_lora_purpose(fname, metadata, keys)
        if not compatible:
            bad.append(f"{name}（{reason}）")
    if bad:
        raise HTTPException(
            status_code=422,
            detail=f"以下 LoRA 不能用于当前绘画链路：{'；'.join(bad)}",
        )


def _prepare_prompts(prompt: str, negative_prompt: str) -> tuple[str, str]:
    """自动加入 uncensored 和无遮挡标签，并执行内容限制检查。"""
    prompt = prompt.strip()
    if "uncensored" not in prompt.lower():
        prompt = f"{prompt}, uncensored"
    if not all(tag in negative_prompt.lower() for tag in ("mosaic_censored", "bar_censor", "censored")):
        negative_prompt = f"{negative_prompt}, {DE_MOSAIC_TAGS}".strip(", ")
    if _is_group_pose_prompt(prompt):
        lowered_negative = negative_prompt.lower()
        missing_tags = [tag for tag in GROUP_NEGATIVE_TAGS if tag not in lowered_negative]
        if missing_tags:
            negative_prompt = f"{negative_prompt}, {', '.join(missing_tags)}".strip(", ")
    if content_filter.is_always_blocked(prompt) or content_filter.is_always_blocked(negative_prompt):
        raise HTTPException(status_code=403, detail="该内容被禁止生成")
    if content_restriction_enabled() and (
        content_filter.is_nsfw(prompt) or content_filter.is_nsfw(negative_prompt)
    ):
        raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")
    return prompt, negative_prompt


def _classify_error(exc: Exception) -> str:
    """把生成异常归类为 timeout/connection/oom/model/unknown。"""
    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "connection" in text or "refused" in text or "socket" in text:
        return "connection"
    if "out of memory" in text or "cuda out of memory" in text or "oom" in text:
        return "oom"
    if "not found" in text or "missing" in text or "unknown" in text:
        return "model"
    return "unknown"


def _generate_with_error_retries(
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    model: str,
    loras: list[str],
    seed: int | None,
    lora_strength_model: float,
    lora_strength_clip: float,
    lora_strengths: dict | None,
) -> dict:
    """生成单张候选图，只对生成异常做有限重试。"""
    last_error: Exception | None = None
    for attempt in range(MAX_GENERATE_RETRIES + 1):
        try:
            return generate(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                steps=steps,
                cfg=cfg,
                loras=loras,
                model_name=model,
                seed=seed,
                lora_strength_model=lora_strength_model,
                lora_strength_clip=lora_strength_clip,
                lora_strengths=lora_strengths,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < MAX_GENERATE_RETRIES:
                time.sleep(2 * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError("图片生成未返回结果")


def _new_retry_seed(current_seed: int | None) -> int:
    """人数守门重试时换一个与当前候选不同的 seed。"""
    for _ in range(10):
        seed = random.randint(0, 2**63 - 1)
        if seed != current_seed:
            return seed
    if current_seed is None:
        return random.randint(0, 2**63 - 1)
    return current_seed + 1 if current_seed < 2**63 - 1 else 0


def _strengthen_people_prompt(prompt: str, expected: int) -> str:
    """为人数或群交姿势不符的重试候选补充明确构图约束。"""
    suffix = (
        f"exactly {expected} separate people in one wide shot, "
        f"{expected} fully visible distinct bodies, "
        "single continuous scene, every character has exactly one head, two arms, and two legs, "
        "clear separated silhouettes, opaque bodies, "
        "preserve every specified character position, contact point, and action exactly as written, "
        "do not change the pose or roles, do not merge bodies, "
        "no extra people, no missing people, no duplicated characters, no duplicate limbs"
    )
    return f"{prompt.rstrip(' ,')}, {suffix}"


def _people_count_mismatch(review: dict | None, expected: int | None) -> bool:
    """判断视觉复核结果是否属于可重试的人数不符。"""
    if expected is None or expected < PEOPLE_GUARD_MIN_COUNT or not review:
        return False
    if review.get("ok") is not False:
        return False
    count = review.get("character_count")
    return isinstance(count, int) and count != expected


def _is_group_pose_prompt(prompt: str) -> bool:
    """判断提示词是否属于需要姿势/动作守门的 3P/群交构图。"""
    lowered = prompt.lower()
    expected = _expected_count(prompt)
    return expected is not None and expected >= 3 and any(
        marker in lowered for marker in GROUP_POSE_MARKERS
    )


def _group_pose_mismatch(review: dict | None, prompt: str) -> bool:
    """判断视觉复核结果是否明确报告群交姿势或动作不符。"""
    if not _is_group_pose_prompt(prompt) or not review:
        return False
    if review.get("ok") is not False:
        return False
    return any(
        review.get(key) is False
        for key in ("pose_ok", "action_ok", "composition_ok", "anatomy_ok", "single_scene")
    )


def _multiple_same_mismatch(review: dict | None) -> bool:
    """多人图只要检测到重复/克隆角色，就换 seed 重试。"""
    return bool(review and review.get("ok") is False and review.get("multiple_same") is True)


def _guard_failure_reason(
    review: dict | None,
    expected: int | None,
    prompt: str,
) -> str:
    """返回当前候选未通过守门的原因；通过时返回空字符串。"""
    if _people_count_mismatch(review, expected):
        reason = review.get("reason") if review else ""
        return str(reason or "character_count")
    if _multiple_same_mismatch(review):
        reason = review.get("reason") if review else ""
        return str(reason or "multiple_same")
    if _group_pose_mismatch(review, prompt):
        reason = review.get("reason") if review else ""
        return str(reason or "group_pose_mismatch")
    if review and review.get("ok") is False:
        reason = review.get("reason") or review.get("message")
        return str(reason or "visual_review_failed")
    return ""


def _discard_rejected_image(result: dict) -> None:
    """移除未通过人数守门的本地候选图，避免无记录孤儿文件。"""
    saved_path = result.get("saved_path")
    if not saved_path:
        return
    try:
        Path(saved_path).unlink(missing_ok=True)
    except OSError:
        pass


def _review_quality_score(review: dict | None) -> int:
    """读取视觉复核的质量分；缺失或非法时返回中性值。"""
    if not review:
        return 50
    raw = review.get("quality_score")
    if isinstance(raw, bool):
        return 50
    if isinstance(raw, (int, float)):
        return max(0, min(100, int(raw)))
    if isinstance(raw, str):
        match = re.search(r"\d+", raw)
        if match:
            return max(0, min(100, int(match.group(0))))
    return 50


def _group_candidate_score(
    review: dict | None,
    expected: int | None,
    prompt: str,
) -> int:
    """给群交候选排序；硬通过优先，随后比较质量分和各守门项。"""
    if not review:
        return -100000
    if review.get("skipped"):
        return -90000

    score = 0
    if review.get("ok") is True:
        score += 100000

    count = review.get("character_count")
    if expected is not None:
        if isinstance(count, int) and count == expected:
            score += 20000
        elif isinstance(count, int):
            score -= 30000

    expected_female, expected_male = _expected_gender_counts(prompt)
    female_count = review.get("female_count")
    male_count = review.get("male_count")
    if expected_female is not None:
        if isinstance(female_count, int) and female_count == expected_female:
            score += 12000
        elif isinstance(female_count, int):
            score -= 18000
    if expected_male is not None:
        if isinstance(male_count, int) and male_count == expected_male:
            score += 12000
        elif isinstance(male_count, int):
            score -= 18000

    multiple_same = review.get("multiple_same")
    if multiple_same is False:
        score += 12000
    elif multiple_same is True:
        score -= 24000

    if _is_group_pose_prompt(prompt):
        for key in (
            "pose_ok",
            "action_ok",
            "composition_ok",
            "anatomy_ok",
            "single_scene",
        ):
            value = review.get(key)
            if value is True:
                score += 8000
            elif value is False:
                score -= 16000

    consensus = review.get("count_consensus")
    if consensus is True:
        score += 5000
    elif consensus is False:
        score -= 2000

    if review.get("review_status") == "auto_passed":
        score += 3000
    reason = str(review.get("reason") or "")
    if reason in {
        "detail_review_error",
        "counter_review_error",
        "crop_review_error",
        "invalid_review",
        "review_error",
    }:
        score -= 25000
    return score * 1000 + _review_quality_score(review)


def _pick_best_group_candidate(
    candidates: list[dict],
    expected: int | None,
    prompt: str,
) -> dict:
    """按质量排序选择群交候选；同分时优先保留较早生成且 seed 更稳定的候选。"""
    return max(
        candidates,
        key=lambda item: (
            _group_candidate_score(item.get("review"), expected, prompt),
            -int(item.get("attempt") or 0),
        ),
    )


def _generate_with_people_guard(
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    model: str,
    loras: list[str],
    seed: int | None,
    lora_strength_model: float,
    lora_strength_clip: float,
    lora_strengths: dict | None,
) -> tuple[dict, dict | None, dict | None]:
    """生成图片，并在多人提示词人数不符时换 seed 和增强提示重试。"""
    expected = _expected_count(prompt)
    result = _generate_with_error_retries(
        prompt,
        negative_prompt,
        width,
        height,
        steps,
        cfg,
        model,
        loras,
        seed,
        lora_strength_model,
        lora_strength_clip,
        lora_strengths,
    )
    review = _maybe_visual_review(result.get("saved_path"), prompt)
    if expected is None or expected < PEOPLE_GUARD_MIN_COUNT:
        return result, review, None

    guard = {
        "expected_count": expected,
        "attempts": 1,
        "retries": 0,
        "passed": None,
        "strengthened": False,
        "reason": "",
        "pose_ok": None,
        "action_ok": None,
        "composition_ok": None,
    }
    current_seed = seed
    failure_reason = _guard_failure_reason(review, expected, prompt)
    if review and review.get("skipped"):
        guard["passed"] = False
        guard["reason"] = "review_skipped"
        return result, review, guard

    if _is_group_pose_prompt(prompt) and review is not None:
        candidates = [
            {
                "attempt": 1,
                "result": result,
                "review": review,
                "seed": seed,
            }
        ]
        current_seed = result.get("seed", seed)
        retry_prompt = _strengthen_people_prompt(prompt, expected)
        for attempt in range(2, MAX_GROUP_CANDIDATES + 1):
            candidate_seed = _new_retry_seed(current_seed)
            try:
                candidate_result = _generate_with_error_retries(
                    retry_prompt,
                    negative_prompt,
                    width,
                    height,
                    steps,
                    cfg,
                    model,
                    loras,
                    candidate_seed,
                    lora_strength_model,
                    lora_strength_clip,
                    lora_strengths,
                )
            except Exception as exc:  # noqa: BLE001
                guard.setdefault("candidate_errors", []).append(
                    {"attempt": attempt, "error": str(exc)[:200]}
                )
                break
            candidate_review = _maybe_visual_review(
                candidate_result.get("saved_path"),
                prompt,
            )
            candidates.append(
                {
                    "attempt": attempt,
                    "result": candidate_result,
                    "review": candidate_review,
                    "seed": candidate_seed,
                }
            )
            current_seed = candidate_result.get("seed", candidate_seed)

        best = _pick_best_group_candidate(candidates, expected, prompt)
        for candidate in candidates:
            if candidate is not best:
                _discard_rejected_image(candidate["result"])

        result = best["result"]
        review = best["review"]
        selected_attempt = int(best["attempt"])
        failure_reason = _guard_failure_reason(review, expected, prompt)
        guard.update(
            attempts=len(candidates),
            retries=max(0, len(candidates) - 1),
            strengthened=selected_attempt > 1,
            passed=review.get("ok") is True if review else False,
            reason="" if guard["passed"] else failure_reason,
            candidate_count=len(candidates),
            selected_attempt=selected_attempt,
            quality_score=_review_quality_score(review),
        )
        if review:
            for key in (
                "pose_ok",
                "action_ok",
                "composition_ok",
                "anatomy_ok",
                "single_scene",
                "count_consensus",
                "counter_character_count",
                "crop_counts",
                "crop_sum",
                "review_status",
            ):
                if key in review:
                    guard[key] = review.get(key)
        return result, review, guard

    while failure_reason and guard["retries"] < MAX_PEOPLE_GUARD_RETRIES:
        guard["retries"] += 1
        guard["attempts"] += 1
        guard["strengthened"] = True
        guard["reason"] = failure_reason
        current_seed = _new_retry_seed(current_seed)
        retry_prompt = _strengthen_people_prompt(prompt, expected)
        previous_result = result
        try:
            result = _generate_with_error_retries(
                retry_prompt,
                negative_prompt,
                width,
                height,
                steps,
                cfg,
                model,
                loras,
                current_seed,
                lora_strength_model,
                lora_strength_clip,
                lora_strengths,
            )
        except Exception as exc:  # noqa: BLE001
            guard["passed"] = False
            guard["retry_error"] = str(exc)
            return previous_result, review, guard
        _discard_rejected_image(previous_result)
        review = _maybe_visual_review(result.get("saved_path"), prompt)
        failure_reason = _guard_failure_reason(review, expected, prompt)

    if review and isinstance(review.get("ok"), bool):
        guard["passed"] = review.get("ok") is True and not failure_reason
        guard["reason"] = "" if guard["passed"] else failure_reason
    if review:
        for key in (
            "pose_ok",
            "action_ok",
            "composition_ok",
            "count_consensus",
            "counter_character_count",
            "crop_counts",
            "crop_sum",
            "review_status",
        ):
            if key in review:
                guard[key] = review.get(key)
    return result, review, guard


def _generate_and_record(
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    model: str,
    loras: list[str],
    seed: int | None,
    batch_id: str | None,
    group_index: int | None,
    image_index: int,
    lora_strength_model: float = config.DRAW_DEFAULT_LORA_STRENGTH_MODEL,
    lora_strength_clip: float = config.DRAW_DEFAULT_LORA_STRENGTH_CLIP,
    lora_strengths: dict | None = None,
    prompt_document_json: str = "{}",
) -> dict:
    """生成一张满足人数守门的图，并写入一条数据库记录。"""
    prompt, negative_prompt = _prepare_prompts(prompt, negative_prompt)
    record_id = database.insert_draw_start(
        prompt,
        translate_text(prompt),
        negative_prompt,
        translate_text(negative_prompt),
        width,
        height,
        steps,
        cfg,
        model,
        loras=loras,
        batch_id=batch_id,
        group_index=group_index,
        lora_anima_turbo=any("anima-turbo" in str(name) for name in loras),
        lora_high_contrast=any("high-contrast" in str(name) for name in loras),
        prompt_document_json=prompt_document_json,
    )
    started = time.time()
    try:
        result, review, guard = _generate_with_people_guard(
            prompt,
            negative_prompt,
            width,
            height,
            steps,
            cfg,
            model,
            loras,
            seed,
            lora_strength_model,
            lora_strength_clip,
            lora_strengths,
        )
        duration = round(time.time() - started, 2)
        database.finish_draw(
            record_id,
            duration,
            result.get("saved_path"),
            result.get("image_url"),
            result.get("seed"),
            "success",
        )
        output = {
            **result,
            "record_id": record_id,
            "batch_id": batch_id,
            "group_index": group_index,
            "image_index": image_index,
        }
        if review is not None:
            output["review"] = review
        if guard is not None:
            output["guard"] = guard
        return output
    except Exception as exc:  # noqa: BLE001
        database.finish_draw(
            record_id,
            round(time.time() - started, 2),
            None,
            None,
            None,
            "error",
            str(exc),
        )
        raise


def _run_batch(job_id: str, groups: list[dict], generation_config: dict) -> None:
    """后台线程逐组生成图片并更新进度。"""
    results: list[dict] = []
    done = 0
    error: str | None = None
    try:
        for group_index, group in enumerate(groups):
            for image_index in range(group["count"]):
                if BATCH_JOBS[job_id].get("stop_requested"):
                    break
                result = _generate_and_record(
                    group["prompt"],
                    group.get("negative_prompt", generation_config["negative_prompt"]),
                    generation_config["width"],
                    generation_config["height"],
                    generation_config["steps"],
                    generation_config["cfg"],
                    generation_config["model"],
                    generation_config["loras"],
                    generation_config.get("seed"),
                    job_id,
                    group_index,
                    image_index,
                    generation_config.get(
                        "lora_strength_model",
                        config.DRAW_DEFAULT_LORA_STRENGTH_MODEL,
                    ),
                    generation_config.get(
                        "lora_strength_clip",
                        config.DRAW_DEFAULT_LORA_STRENGTH_CLIP,
                    ),
                    generation_config.get("lora_strengths"),
                    prompt_document_json=group.get("prompt_document_json", "{}"),
                )
                results.append(result)
                done += 1
                with BATCH_LOCK:
                    BATCH_JOBS[job_id]["done"] = done
                    BATCH_JOBS[job_id]["current_group"] = group_index
                    BATCH_JOBS[job_id]["results"] = results
            else:
                continue
            break
    except Exception as exc:  # noqa: BLE001
        error = f"[{_classify_error(exc)}] {exc}"
    global ACTIVE_BATCH_ID
    with BATCH_LOCK:
            if BATCH_JOBS[job_id].get("stop_requested"):
                BATCH_JOBS[job_id]["status"] = "stopped"
                BATCH_JOBS[job_id]["error"] = "已手动停止"
            else:
                BATCH_JOBS[job_id]["status"] = "error" if error else "done"
                BATCH_JOBS[job_id]["error"] = error
            BATCH_JOBS[job_id]["finished_at"] = database.now_iso()
            BATCH_JOBS[job_id]["done"] = done
            BATCH_JOBS[job_id]["results"] = results
            _persist_job(BATCH_JOBS[job_id])
            task_registry.finish("draw", job_id, BATCH_JOBS[job_id]["status"], BATCH_JOBS[job_id].get("error"))
    with ACTIVE_BATCH_LOCK:
        if ACTIVE_BATCH_ID == job_id:
            ACTIVE_BATCH_ID = None


def _persist_job(job: dict) -> None:
    try:
        database.save_batch_job(job)
    except Exception:
        pass


def _validate_model(model: str) -> str:
    """校验底模名称，返回可用模型名。"""
    model = str(model or DEFAULT_MODEL)
    available = {item["name"] for item in list_diffusion_models()}
    if model not in available:
        raise HTTPException(status_code=400, detail="未知的底模")
    return model


def _parse_steps(payload: dict) -> int:
    """解析并校验步数，空值/非法值直接返回 400。"""
    raw = payload.get("steps")
    if raw is None or str(raw).strip() == "":
        raise HTTPException(status_code=400, detail="步数不能为空")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="步数格式不正确")
    if value < config.DRAW_STEPS_MIN or value > config.DRAW_STEPS_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"步数必须在 {config.DRAW_STEPS_MIN}-{config.DRAW_STEPS_MAX} 之间",
        )
    return value


def _parse_int_param(
    payload: dict,
    key: str,
    default: int,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(payload.get(key, default))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{label}格式不正确") from None
    if value < minimum or value > maximum:
        raise HTTPException(
            status_code=400,
            detail=f"{label}必须在 {minimum}-{maximum} 之间",
        )
    return value


def _parse_float_param(
    payload: dict,
    key: str,
    default: float,
    label: str,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(payload.get(key, default))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{label}格式不正确") from None
    if value < minimum or value > maximum:
        raise HTTPException(
            status_code=400,
            detail=f"{label}必须在 {minimum:g}-{maximum:g} 之间",
        )
    return value


def _parse_lora_strengths(raw: object) -> dict[str, dict[str, float]]:
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="LoRA 强度格式不正确")
    result: dict[str, dict[str, float]] = {}
    for raw_name, raw_strengths in raw.items():
        if not isinstance(raw_strengths, dict):
            raise HTTPException(status_code=400, detail="LoRA 强度格式不正确")
        strengths: dict[str, float] = {}
        for key in ("model", "clip"):
            raw_value = raw_strengths.get(key)
            if raw_value in (None, ""):
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="LoRA 强度格式不正确") from None
            if value < config.DRAW_LORA_STRENGTH_MIN or value > config.DRAW_LORA_STRENGTH_MAX:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"LoRA 强度必须在 {config.DRAW_LORA_STRENGTH_MIN:g}-"
                        f"{config.DRAW_LORA_STRENGTH_MAX:g} 之间"
                    ),
                )
            strengths[key] = value
        if strengths:
            result[str(raw_name)] = strengths
    return result


def _parse_draw_settings(payload: dict) -> dict:
    return {
        "width": _parse_int_param(
            payload,
            "width",
            config.DRAW_DEFAULT_WIDTH,
            "宽度",
            config.DRAW_WIDTH_MIN,
            config.DRAW_WIDTH_MAX,
        ),
        "height": _parse_int_param(
            payload,
            "height",
            config.DRAW_DEFAULT_HEIGHT,
            "高度",
            config.DRAW_HEIGHT_MIN,
            config.DRAW_HEIGHT_MAX,
        ),
        "steps": _parse_steps(payload),
        "cfg": _parse_float_param(
            payload,
            "cfg",
            config.DRAW_DEFAULT_CFG,
            "CFG",
            config.DRAW_CFG_MIN,
            config.DRAW_CFG_MAX,
        ),
        "lora_strength_model": _parse_float_param(
            payload,
            "lora_strength_model",
            config.DRAW_DEFAULT_LORA_STRENGTH_MODEL,
            "LoRA 模型强度",
            config.DRAW_LORA_STRENGTH_MIN,
            config.DRAW_LORA_STRENGTH_MAX,
        ),
        "lora_strength_clip": _parse_float_param(
            payload,
            "lora_strength_clip",
            config.DRAW_DEFAULT_LORA_STRENGTH_CLIP,
            "LoRA CLIP 强度",
            config.DRAW_LORA_STRENGTH_MIN,
            config.DRAW_LORA_STRENGTH_MAX,
        ),
        "lora_strengths": _parse_lora_strengths(payload.get("lora_strengths")),
    }


def _resolve_draw_document(
    prompt: str,
    raw_document: object,
    fallback_negative: str,
) -> tuple[str, str, str]:
    """Resolve a draw prompt document on the backend and return its saved snapshot."""
    if raw_document not in (None, ""):
        if isinstance(raw_document, str):
            try:
                raw_document = json.loads(raw_document)
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"结构化提示词不是有效 JSON：{exc}",
                ) from exc
        if not isinstance(raw_document, dict):
            raise HTTPException(status_code=400, detail="结构化提示词必须是 JSON 对象")
        try:
            resolved = prompt_document.resolve_document(
                raw_document,
                restriction_enabled=content_restriction_enabled(),
            )
        except prompt_document.PromptDocumentError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        if resolved.get("blocked") or resolved.get("errors"):
            detail = "；".join(resolved.get("errors") or ["结构化提示词校验未通过"])
            raise HTTPException(status_code=422, detail=detail)
        final_prompt = str(resolved.get("prompt") or "").strip()
        final_negative = str(resolved.get("negative_prompt") or "").strip()
        if not final_prompt:
            raise HTTPException(status_code=400, detail="结构化提示词解析结果为空")
        snapshot = json.dumps(
            resolved.get("resolved_document") or raw_document,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return final_prompt, final_negative, snapshot

    final_prompt = prompt.strip()
    if not final_prompt:
        raise HTTPException(status_code=400, detail="提示词不能为空")
    final_negative = str(fallback_negative or "")
    document = prompt_document.legacy_document(final_prompt, final_negative)
    snapshot = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    return final_prompt, final_negative, snapshot


def _expected_count(prompt: str) -> int | None:
    """从提示词中解析期望角色数：优先按性别汇总，再识别 people 数量词。"""
    lowered = prompt.lower().replace(" ", "")
    girl = 0
    boy = 0
    for match in re.finditer(r"(\d+)(girls?|boys?|women?|men?)", lowered):
        value = int(match.group(1))
        if match.group(2).startswith(("girl", "woman")):
            girl = max(girl, value)
        else:
            boy = max(boy, value)
    total = girl + boy
    if total > 0:
        return total
    if "solo" in lowered:
        return 1
    lowered_text = prompt.lower()
    word_numbers = {
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    match = re.search(
        r"(?:exactly\s+)?(\d+|[a-z]+)\s+(?:separate\s+)?"
        r"(?:people|women|men|characters)",
        lowered_text,
    )
    if match:
        raw = match.group(1)
        value = int(raw) if raw.isdigit() else word_numbers.get(raw)
        if value:
            return value
    if "threesome" in lowered_text:
        return 3
    if "foursome" in lowered_text:
        return 4
    if "twosome" in lowered_text:
        return 2
    return None


def _expected_gender_counts(prompt: str) -> tuple[int | None, int | None]:
    """从提示词解析明确的女性/男性数量，无法确认的一侧返回 None。"""
    lowered = prompt.lower()
    female = 0
    male = 0
    female_seen = False
    male_seen = False
    for raw in re.findall(r"(\d+)\s*(?:girls?|women?|females?)", lowered):
        female = max(female, int(raw))
        female_seen = True
    for raw in re.findall(
        r"(\d+)\s*(?:[a-z-]+\s+){0,2}(?:boys?|men|males?)",
        lowered,
    ):
        male = max(male, int(raw))
        male_seen = True
    return (
        female if female_seen else None,
        male if male_seen else None,
    )


def _extract_json_object(text: str) -> dict:
    """从 VLM 输出中提取 JSON 对象，兼容代码围栏和前后说明。"""
    cleaned = text.strip().strip("`")
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def _json_bool(data: dict, key: str, default: bool | None = None) -> bool | None:
    """宽松解析 VLM JSON 中的布尔字段。"""
    value = data.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "correct", "match", "matches", "1", "是", "正确"}:
            return True
        if lowered in {"false", "no", "wrong", "mismatch", "0", "否", "错误"}:
            return False
    return default


def _review_counts(data: dict) -> tuple[int | None, int | None]:
    """返回逐头清单人数和模型自报总数；清单缺失或损坏时人数为 None。"""
    heads = data.get("heads")
    raw_count = data.get("character_count")
    reported_count: int | None = None
    if isinstance(raw_count, (int, float)) and not isinstance(raw_count, bool):
        reported_count = int(raw_count)
    elif isinstance(raw_count, str) and raw_count.strip().isdigit():
        reported_count = int(raw_count.strip())

    if not isinstance(heads, list):
        return None, reported_count
    if any(not isinstance(head, dict) for head in heads):
        return None, reported_count
    return len(heads), reported_count


def _review_gender_counts(data: dict) -> tuple[int, int, int]:
    """统计逐头清单中的女性、男性和未知性别数量。"""
    heads = data.get("heads")
    if not isinstance(heads, list):
        return 0, 0, 0
    female = 0
    male = 0
    unknown = 0
    for head in heads:
        if not isinstance(head, dict):
            continue
        gender = str(head.get("gender") or "").strip().lower()
        if gender in {"female", "woman", "girl", "f", "女", "女性"}:
            female += 1
        elif gender in {"male", "man", "boy", "m", "男", "男性"}:
            male += 1
        else:
            unknown += 1
    return female, male, unknown


def _head_census_valid(data: dict, require_gender: bool) -> bool:
    """检查逐头清单是否包含可用于复核的坐标、可见度和性别字段。"""
    heads = data.get("heads")
    if not isinstance(heads, list) or not heads:
        return False
    valid_genders = {
        "female",
        "woman",
        "girl",
        "f",
        "女",
        "女性",
        "male",
        "man",
        "boy",
        "m",
        "男",
        "男性",
    }
    valid_visibility = {"full", "partial", "完整", "部分"}
    for head in heads:
        if not isinstance(head, dict):
            return False
        for key in ("x", "y"):
            value = head.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False
        visibility = str(head.get("visibility") or "").strip().lower()
        if visibility not in valid_visibility:
            return False
        if require_gender:
            gender = str(head.get("gender") or "").strip().lower()
            if gender not in valid_genders:
                return False
    return True


def _counter_head_census_valid(data: dict) -> bool:
    """校验计数模型的逐头清单，兼容模型返回的枚举占位文本。"""
    heads = data.get("heads")
    if not isinstance(heads, list) or not heads:
        return False
    valid_genders = {
        "female",
        "woman",
        "girl",
        "f",
        "女",
        "女性",
        "male",
        "man",
        "boy",
        "m",
        "男",
        "男性",
        "unknown",
        "male/female/unknown",
    }
    valid_visibility = {
        "full",
        "partial",
        "完整",
        "部分",
        "unknown",
        "full/partial",
    }
    for head in heads:
        if not isinstance(head, dict):
            return False
        for key in ("x", "y"):
            value = head.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False
        gender = str(head.get("gender") or "").strip().lower()
        visibility = str(head.get("visibility") or "").strip().lower()
        if gender not in valid_genders or visibility not in valid_visibility:
            return False
    return True


def _call_ollama_json(
    model: str,
    prompt_text: str,
    encoded_images: list[str],
    num_predict: int,
    timeout: int = 120,
) -> dict:
    """调用 Ollama 视觉模型并解析单个 JSON 对象。"""
    response = requests.post(
        OLLAMA_BASE + "/api/generate",
        json={
            "model": model,
            "prompt": prompt_text,
            "images": encoded_images,
            "stream": False,
            "format": "json",
            "options": {
                "num_predict": num_predict,
                "num_ctx": 8192,
                "temperature": 0.1,
                "top_p": 0.9,
            },
        },
        timeout=timeout,
    )
    response.raise_for_status()
    text = response.json().get("response") or ""
    return _extract_json_object(text)


def _encode_counter_image_object(image) -> str:
    """将计数模型输入缩到稳定尺寸并编码为 JPEG。"""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - 依赖安装失败时失败关闭
        raise RuntimeError("缺少 Pillow，无法执行多人图独立计数") from exc

    prepared = image.convert("RGB")
    if max(prepared.size) > COUNTER_IMAGE_MAX_SIDE:
        prepared.thumbnail(
            (COUNTER_IMAGE_MAX_SIDE, COUNTER_IMAGE_MAX_SIDE),
            Image.Resampling.LANCZOS,
        )
    buffer = io.BytesIO()
    prepared.save(
        buffer,
        format="JPEG",
        quality=COUNTER_IMAGE_JPEG_QUALITY,
        optimize=True,
    )
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _encode_counter_image(path: Path) -> str:
    """编码整图计数输入；无法解码的测试或异常数据安全回退原图。"""
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:  # pragma: no cover - 依赖安装失败时失败关闭
        raise RuntimeError("缺少 Pillow，无法执行多人图独立计数") from exc

    try:
        with Image.open(path) as source:
            return _encode_counter_image_object(source)
    except UnidentifiedImageError:
        return base64.b64encode(path.read_bytes()).decode("ascii")


def _encode_region_images(path: Path) -> dict[str, str]:
    """把整图按中线拆成左右两个不重叠半区，供独立计数复核。"""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - 依赖安装失败时失败关闭
        raise RuntimeError("缺少 Pillow，无法执行多人图局部复核") from exc

    with Image.open(path) as source:
        image = source.convert("RGB")
        width, height = image.size
        if width < 2:
            raise ValueError("图片宽度不足，无法执行左右半区复核")
        split = width // 2
        regions = {
            "left": image.crop((0, 0, split, height)),
            "right": image.crop((split, 0, width, height)),
        }
        encoded: dict[str, str] = {}
        for name, region in regions.items():
            encoded[name] = _encode_counter_image_object(region)
        return encoded


def _counter_prompt(scope: str) -> str:
    """生成不带期望人数提示的独立头数清点提示词。"""
    if scope == "full":
        scope_text = (
            "检查完整图片。逐个列出每个具有独立头部的人物；背景人物、被遮挡人物、"
            "画面边缘只露出头部或部分身体的人物也必须计数，同一个人不能重复列出。"
        )
    else:
        side = "左半区" if scope == "left" else "右半区"
        scope_text = (
            f"这是一张完整图片的{side}。只统计头部中心位于本半区内的人物；"
            "头部中心不在本半区但部分身体进入画面的人物不要计数。"
            "仍然要列出本半区内被遮挡或画面边缘的人物，同一个人不能重复列出。"
        )
    return (
        f"{scope_text}"
        "不要根据常见构图推断人数，只依据当前图片中可辨认的独立头部。"
        "若存在无法确认是否属于同一人的区域，uncertain=true。"
        "gender 和 visibility 必须填写判断结果，不能照抄字段选项。"
        "只输出 JSON："
        '{"heads": [{"x": 数字, "y": 数字, "gender": "male/female/unknown", '
        '"visibility": "full/partial"}], "character_count": 数字, '
        '"count_confident": true/false, "uncertain": true/false}。'
    )


def _independent_count_once(
    model: str,
    encoded_image: str,
    scope: str,
) -> tuple[int | None, str, dict]:
    """调用独立模型清点一次，并对结构异常做一次重试。"""
    last_data: dict = {}
    for attempt in range(2):
        try:
            data = _call_ollama_json(
                model,
                _counter_prompt(scope),
                [encoded_image],
                num_predict=220 if scope == "full" else 180,
            )
        except Exception:
            if attempt == 0:
                continue
            raise

        last_data = data
        count, reported_count = _review_counts(data)
        confident = _json_bool(data, VLM_COUNT_CONFIDENCE_KEY, None)
        uncertain = _json_bool(data, "uncertain", None)
        if count is None or reported_count is None or reported_count != count:
            error = "invalid_payload"
        elif confident is not True:
            error = "not_confident"
        elif uncertain is not False:
            error = "uncertain"
            return count, error, data
        elif not _counter_head_census_valid(data) and count > 0:
            error = "invalid_heads"
        else:
            return count, "", data

        if attempt == 1:
            return count, error, last_data
    return None, "invalid_payload", last_data


def _independent_count(
    model: str,
    encoded_image: str,
    scope: str,
    *,
    allow_uncertain: bool = False,
) -> tuple[int | None, str, dict]:
    """三次独立清点取多数，避免单次 VLM 漏计或幻觉直接放行。"""
    samples: list[tuple[int, dict]] = []
    last_data: dict = {}
    last_error = "invalid_payload"
    last_exception: Exception | None = None
    for _ in range(5):
        if len(samples) >= 3:
            break
        try:
            count, error, data = _independent_count_once(
                model,
                encoded_image,
                scope,
            )
        except Exception as exc:  # noqa: BLE001
            last_exception = exc
            last_error = "request_error"
            continue
        if data:
            last_data = data
        if error and not (
            allow_uncertain and error == "uncertain" and count is not None
        ):
            last_error = error
            continue
        if count is not None:
            samples.append((count, data))

    if len(samples) < 3:
        if last_exception is not None and not samples:
            raise last_exception
        return None, last_error, last_data

    frequencies: dict[int, int] = {}
    for count, _ in samples:
        frequencies[count] = frequencies.get(count, 0) + 1
    count, frequency = max(frequencies.items(), key=lambda item: item[1])
    if frequency < 2:
        return None, "inconsistent_count", last_data
    representative = next(data for sample_count, data in samples if sample_count == count)
    return count, "", representative


def _review_image(path: Path, expected: int | None, prompt: str) -> dict:
    """复核生成图，并用独立计数模型和局部图片做失败关闭式共识校验。"""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    counter_encoded = _encode_counter_image(path)
    group_review = _is_group_pose_prompt(prompt)
    detail_model = (
        database.get_setting("vlm_model", config.VLM_MODEL) or config.VLM_MODEL
    )
    if group_review:
        prompt_text = (
            "请逐项判断图片是否准确对应下面的期望构图，重点检查人物总数、"
            "每个角色的位置和姿势、具体动作、插入或接触关系、身体是否分离。"
            "必须先逐个列出每个具有独立头部的人物；背景人物、被遮挡人物、"
            "画面边缘只露出头部或部分身体的人物也必须计数，不能漏掉；"
            "同一个人不能重复列出。character_count 必须等于 heads 数组长度。"
            "必须严格核对提示词要求的女性和男性数量；若某个期望角色没有头部、"
            "只剩身体碎片或被替换成其他性别，必须判定为错误。"
            "整张图必须是一个连续场景；若出现分栏、拼贴或多视角，single_scene=false。"
            "每个人必须有一个头、两条手臂和两条腿；若有克隆、透明身体、重复肢体或融合肢体，"
            "multiple_same 或 anatomy_matches 必须判为错误。"
            f"期望构图：{prompt[:1800]}\n"
            "只输出 JSON："
            '{"heads": [{"x": 数字, "y": 数字, "gender": "male/female", '
            '"visibility": "full/partial"}], "character_count": 数字, '
            '"multiple_same": true/false, '
            '"pose_matches": true/false, "action_matches": true/false, '
            '"composition_matches": true/false, "anatomy_matches": true/false, '
            '"single_scene": true/false, "quality_score": 0到100的整数, '
            '"wrong_reason": "简短原因"}。'
        )
        num_predict = 360
    else:
        prompt_text = (
            "请逐个人物检查图片。先逐个列出每个具有独立头部的人物，包括背景人物、"
            "被遮挡人物和画面边缘部分可见的人物；同一个人不能重复列出。"
            "character_count 必须等于 heads 数组长度。"
            "再判断是否出现多个相同/克隆角色。"
            "只输出 JSON："
            '{"heads": [{"x": 数字, "y": 数字, "gender": "male/female", '
            '"visibility": "full/partial"}], "character_count": 数字, '
            '"multiple_same": true/false}。'
        )
        num_predict = 180
    try:
        data = _call_ollama_json(
            detail_model,
            prompt_text,
            [encoded],
            num_predict=num_predict,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "character_count": None,
            "reported_character_count": None,
            "expected_count": expected,
            "multiple_same": None,
            "pose_ok": None,
            "action_ok": None,
            "composition_ok": None,
            "anatomy_ok": None,
            "single_scene": None,
            "count_consensus": False,
            "count_models": {"detail": detail_model, "counter": VLM_COUNT_MODEL},
            "counter_character_count": None,
            "crop_counts": {},
            "crop_sum": None,
            "review_status": "manual_review",
            "reason": "detail_review_error",
            "message": f"详细视觉复核失败：{str(exc)[:160]}",
            "wrong_reason": str(exc)[:200],
        }

    count, reported_count = _review_counts(data)
    female_count, male_count, unknown_gender_count = _review_gender_counts(data)
    has_gender_heads = female_count + male_count + unknown_gender_count > 0
    expected_female, expected_male = _expected_gender_counts(prompt)
    multiple = _json_bool(data, "multiple_same", None)
    pose_ok = _json_bool(data, "pose_matches", None) if group_review else None
    action_ok = _json_bool(data, "action_matches", None) if group_review else None
    composition_ok = (
        _json_bool(data, "composition_matches", None) if group_review else None
    )
    anatomy_ok = _json_bool(data, "anatomy_matches", None) if group_review else None
    single_scene = _json_bool(data, "single_scene", None) if group_review else None
    wrong_reason = str(data.get("wrong_reason") or "").strip()[:200]
    quality_score = _review_quality_score(data)
    ok = True
    message = ""
    reason = ""
    group_fields = (pose_ok, action_ok, composition_ok, anatomy_ok, single_scene)
    if count is None:
        ok = False
        reason = "invalid_review"
        message = "视觉复核未返回有效的逐人头部清单"
    elif reported_count is None or reported_count != count:
        ok = False
        reason = "invalid_review"
        message = "视觉复核自报人数与逐人头部清单不一致"
    elif not _head_census_valid(data, require_gender=group_review):
        ok = False
        reason = "invalid_review"
        message = "视觉复核的头部坐标、可见度或性别字段不完整"
    elif count <= 0:
        ok = False
        reason = "invalid_review"
        message = "视觉复核未识别到有效人物"
    elif multiple is None:
        ok = False
        reason = "invalid_review"
        message = "视觉复核未明确判断是否存在重复角色"
    elif group_review and any(value is None for value in group_fields):
        ok = False
        reason = "invalid_review"
        message = "视觉复核未完整返回姿势、动作、构图、解剖或单场景结论"
    elif expected is not None and count != expected:
        ok = False
        reason = "character_count"
        message = f"提示词期望 {expected} 个角色，图片检测到 {count} 个"
    elif has_gender_heads and expected_female is not None and female_count != expected_female:
        ok = False
        reason = "gender_count"
        message = f"提示词期望 {expected_female} 个女性，图片只检测到 {female_count} 个"
    elif has_gender_heads and expected_male is not None and male_count != expected_male:
        ok = False
        reason = "gender_count"
        message = f"提示词期望 {expected_male} 个男性，图片检测到 {male_count} 个"
    elif multiple is not False:
        ok = False
        reason = "multiple_same"
        message = "图片检测到多个相同角色"
    elif group_review and single_scene is not True:
        ok = False
        reason = "multiple_scenes"
        message = f"图片不是单一连续场景：{wrong_reason or '检测到分栏、拼贴或多视角'}"
    elif group_review and anatomy_ok is not True:
        ok = False
        reason = "anatomy_error"
        message = f"人物解剖结构错误：{wrong_reason or '检测到重复肢体或融合身体'}"
    elif group_review and composition_ok is not True:
        ok = False
        reason = "group_composition"
        message = f"群交构图与提示词不符：{wrong_reason or '角色数量或空间关系错误'}"
    elif group_review and pose_ok is not True:
        ok = False
        reason = "group_pose"
        message = f"群交姿势与提示词不符：{wrong_reason or '角色位置或接触关系错误'}"
    elif group_review and action_ok is not True:
        ok = False
        reason = "group_action"
        message = f"群交动作与提示词不符：{wrong_reason or '动作关系错误'}"

    result = {
        "ok": ok,
        "character_count": count,
        "reported_character_count": reported_count,
        "expected_count": expected,
        "female_count": female_count,
        "male_count": male_count,
        "unknown_gender_count": unknown_gender_count,
        "expected_female_count": expected_female,
        "expected_male_count": expected_male,
        "multiple_same": multiple,
        "pose_ok": pose_ok,
        "action_ok": action_ok,
        "composition_ok": composition_ok,
        "anatomy_ok": anatomy_ok,
        "single_scene": single_scene,
        "quality_score": quality_score,
        "count_consensus": (
            False
            if expected is not None and expected >= PEOPLE_GUARD_MIN_COUNT
            else None
        ),
        "count_models": {"detail": detail_model, "counter": VLM_COUNT_MODEL},
        "counter_character_count": None,
        "crop_counts": {},
        "crop_sum": None,
        "crop_errors": {},
        "review_status": "auto_passed" if ok else "manual_review",
        "wrong_reason": wrong_reason,
        "reason": reason,
        "message": message,
    }
    if not ok or expected is None or expected < PEOPLE_GUARD_MIN_COUNT:
        return result

    try:
        counter_count, counter_error, _ = _independent_count(
            VLM_COUNT_MODEL,
            counter_encoded,
            "full",
        )
    except Exception as exc:  # noqa: BLE001
        result.update(
            ok=False,
            count_consensus=False,
            review_status="manual_review",
            reason="counter_review_error",
            message=f"独立人数复核失败：{str(exc)[:160]}",
            wrong_reason=str(exc)[:200],
        )
        return result

    result["counter_character_count"] = counter_count
    if counter_error or counter_count != expected:
        result.update(
            ok=False,
            count_consensus=False,
            review_status="manual_review",
            reason="independent_count",
            message=(
                f"详细复核为 {count} 人，独立计数为 "
                f"{counter_count if counter_count is not None else '未知'} 人，"
                f"提示词期望 {expected} 人"
            ),
        )
        return result

    crop_counts: dict[str, int | None] = {}
    crop_errors: dict[str, str] = {}
    try:
        region_images = _encode_region_images(path)
    except Exception as exc:  # noqa: BLE001
        crop_errors["regions"] = str(exc)[:160]
    else:
        for name in ("left", "right"):
            try:
                crop_count, crop_error, _ = _independent_count(
                    VLM_COUNT_MODEL,
                    region_images[name],
                    name,
                    allow_uncertain=True,
                )
            except Exception as exc:  # noqa: BLE001
                crop_counts[name] = None
                crop_errors[name] = str(exc)[:160]
                continue
            crop_counts[name] = crop_count
            if crop_error:
                crop_errors[name] = crop_error

    left_count = crop_counts.get("left")
    right_count = crop_counts.get("right")
    crop_sum = (
        left_count + right_count
        if isinstance(left_count, int) and isinstance(right_count, int)
        else None
    )
    result["crop_counts"] = crop_counts
    result["crop_sum"] = crop_sum
    result["crop_errors"] = crop_errors
    if crop_sum is not None and crop_sum < counter_count:
        result.update(
            ok=False,
            count_consensus=False,
            review_status="manual_review",
            reason="crop_count",
            message=(
                f"整图独立计数为 {counter_count} 人，左右半区仅合计为 {crop_sum} 人"
            ),
        )
        return result

    result.update(
        ok=True,
        count_consensus=True,
        review_status="auto_passed",
        reason="",
        message="",
    )
    return result


def _maybe_visual_review(image_path: str | None, prompt: str) -> dict | None:
    """生成后视觉复核入口：开关关闭或忙碌时跳过。"""
    if not image_path or not Path(image_path).exists() or not visual_review_enabled():
        return None
    other_tasks = [task for task in task_state.running_tasks() if task["type"] != "draw"]
    if other_tasks:
        labels = "、".join(task["label"] for task in other_tasks)
        return {
            "ok": False,
            "skipped": True,
            "reason": "review_skipped",
            "message": f"有其他项目正在运行（{labels}），已跳过视觉复核",
        }
    try:
        return _review_image(Path(image_path), _expected_count(prompt), prompt)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "reason": "review_error",
            "message": f"视觉复核失败：{str(exc)[:160]}",
            "error": str(exc),
        }


@router.get("/api/loras")
def get_loras() -> dict:
    """返回 ComfyUI LoRA 目录下的模型文件列表（含使用次数与保护状态）。"""
    counts = database.lora_usage_counts()
    items = []
    for item in list_loras():
        name = item["name"]
        usage = counts.get(name, 0)
        if usage >= PROTECT_THRESHOLD and not database.get_lora_protection(name):
            database.set_lora_protection(name, True)
        item["usage_count"] = usage
        item["protected"] = database.get_lora_protection(name)
        items.append(item)
    return {"loras": items}


@router.delete("/api/loras/{filename}")
def delete_lora(filename: str) -> dict:
    """删除 ComfyUI LoRA 目录下的指定 LoRA 文件。"""
    if not filename or Path(filename).name != filename or not filename.endswith(".safetensors"):
        raise HTTPException(status_code=400, detail="文件名不合法")
    path = LORAS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="LoRA 文件不存在")
    if database.get_lora_protection(filename):
        raise HTTPException(status_code=403, detail="该 LoRA 已被保护，请先取消保护")
    path.unlink(missing_ok=True)
    return {"ok": True}


@router.post("/api/loras/{filename}/protect")
def protect_lora(filename: str) -> dict:
    """为指定 LoRA 添加保护标记。"""
    if not filename or Path(filename).name != filename or not filename.endswith(".safetensors"):
        raise HTTPException(status_code=400, detail="文件名不合法")
    if not (LORAS_DIR / filename).exists():
        raise HTTPException(status_code=404, detail="LoRA 文件不存在")
    database.set_lora_protection(filename, True)
    return {"ok": True, "protected": True}


@router.post("/api/loras/{filename}/unprotect")
def unprotect_lora(filename: str) -> dict:
    """取消指定 LoRA 的保护标记。"""
    if not filename or Path(filename).name != filename or not filename.endswith(".safetensors"):
        raise HTTPException(status_code=400, detail="文件名不合法")
    if not (LORAS_DIR / filename).exists():
        raise HTTPException(status_code=404, detail="LoRA 文件不存在")
    database.set_lora_protection(filename, False)
    return {"ok": True, "protected": False}


@router.get("/api/models")
def get_models() -> dict:
    """返回可选的绘画底模列表和默认底模。"""
    return {"models": list_diffusion_models(), "default": DEFAULT_MODEL}


@router.get("/api/images/library")
def image_library(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    model: str | None = Query(None),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
    batch_id: str | None = Query(None),
    page: int = Query(
        config.QUERY_IMAGE_LIBRARY_PAGE_DEFAULT,
        ge=config.QUERY_PAGE_MIN,
    ),
    page_size: int = Query(
        config.QUERY_IMAGE_LIBRARY_PAGE_SIZE_DEFAULT,
        ge=config.QUERY_PAGE_MIN,
        le=config.QUERY_IMAGE_LIBRARY_PAGE_SIZE_MAX,
    ),
) -> dict:
    """分页查询图片库。"""
    return database.query_draw_images(
        date_from,
        date_to,
        model,
        status,
        keyword,
        batch_id,
        page,
        page_size,
    )


@router.get("/api/images/library/batches")
def image_library_batches(
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    model: str | None = Query(None),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
) -> dict:
    """图片库按批次分组统计。"""
    return {"items": database.list_draw_batches(date_from, date_to, model, status, keyword)}


@router.post("/api/images/library/export")
def export_images(payload: dict = Body(...)) -> StreamingResponse:
    """按记录 ID 批量导出图片为 zip。"""
    ids = [int(item) for item in (payload.get("ids") or []) if str(item).isdigit()]
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要导出的图片")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for record_id in ids:
            record = database.get_draw_image(record_id)
            if not record or not record.get("image_path"):
                continue
            path = Path(record["image_path"])
            if path.exists():
                archive.write(path, arcname=path.name)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="image-library.zip"'},
    )


@router.delete("/api/images/library/{record_id}")
def delete_image(record_id: int) -> dict:
    """删除图片库记录并尝试删除对应文件。"""
    record = database.get_draw_image(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    image_path = record.get("image_path")
    if image_path:
        try:
            Path(image_path).unlink(missing_ok=True)
        except OSError:
            pass
    database.delete_draw_image(record_id)
    return {"ok": True}


@router.get("/api/images/{filename}")
def get_image(filename: str) -> Response:
    """从 AIproduct 目录提供生成的图片。"""
    safe_name = Path(filename).name
    path = AI_PRODUCT_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="image not found")
    return Response(path.read_bytes(), media_type="image/png")


@router.get("/api/test-images/{filename}")
def get_test_image(filename: str) -> Response:
    """从对比出图目录提供测试图片。"""
    safe_name = Path(filename).name
    path = config.COMPARE_OUTPUT_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="image not found")
    return Response(path.read_bytes(), media_type="image/png")


@router.post("/api/images/open-library")
def open_image_library() -> dict:
    """在资源管理器中打开 AIproduct 图片目录。"""
    AI_PRODUCT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer.exe", str(AI_PRODUCT_DIR)])
    return {"ok": True, "path": str(AI_PRODUCT_DIR)}


@router.post("/api/draw/batch")
def draw_batch(payload: dict = Body(...)):
    """批量绘画：多组提示词，每组指定张数，后台执行并返回任务ID。"""
    model = _validate_model(payload.get("model"))
    fallback_negative = str(payload.get("negative_prompt") or "")
    groups_raw = payload.get("groups")
    if not groups_raw:
        prompt = str(payload.get("prompt") or "").strip()
        raw_document = payload.get("prompt_document")
        if not prompt and not raw_document:
            raise HTTPException(status_code=400, detail="prompt 不能为空")
        groups_raw = [
            {
                "prompt": prompt,
                "prompt_document": raw_document,
                "count": int(payload.get("count", GROUP_COUNT_MIN)),
            }
        ]

    groups: list[dict] = []
    for group in groups_raw:
        raw_prompt = str(group.get("prompt") or "").strip()
        count = int(group.get("count", GROUP_COUNT_MIN))
        if count < GROUP_COUNT_MIN or count > MAX_GROUP_COUNT:
            raise HTTPException(
                status_code=400,
                detail=f"每组张数必须在 {GROUP_COUNT_MIN}-{MAX_GROUP_COUNT} 张之间",
            )
        prompt, group_negative, document_json = _resolve_draw_document(
            raw_prompt,
            group.get("prompt_document"),
            fallback_negative,
        )
        groups.append(
            {
                "prompt": prompt,
                "negative_prompt": group_negative,
                "prompt_document_json": document_json,
                "count": count,
            }
        )

    total = sum(group["count"] for group in groups)
    if total > MAX_TOTAL_COUNT:
        raise HTTPException(status_code=400, detail=f"总张数最多 {MAX_TOTAL_COUNT} 张")
    _validate_lora_compatibility(payload.get("loras") or [])

    other_tasks = [task for task in task_state.running_tasks() if task["type"] != "draw"]
    if other_tasks:
        labels = "、".join(task["label"] for task in other_tasks)
        raise HTTPException(status_code=409, detail=f"有其他项目正在运行（{labels}），请稍后再进行")

    settings = _parse_draw_settings(payload)
    generation_config = {
        "negative_prompt": fallback_negative,
        **settings,
        "model": model,
        "loras": payload.get("loras") or [],
        "seed": payload.get("seed"),
    }

    job_id = uuid.uuid4().hex
    global ACTIVE_BATCH_ID
    with ACTIVE_BATCH_LOCK:
        if ACTIVE_BATCH_ID and BATCH_JOBS.get(ACTIVE_BATCH_ID, {}).get("status") == "running":
            raise HTTPException(status_code=409, detail="已有绘画任务在运行，请等待完成或先停止")
        ACTIVE_BATCH_ID = job_id
    BATCH_JOBS[job_id] = {
        "batch_id": job_id,
        "status": "running",
        "total": total,
        "done": 0,
        "current_group": 0,
        "results": [],
        "error": None,
        "created_at": database.now_iso(),
        "finished_at": None,
        "stop_requested": False,
    }
    task_registry.register("draw", job_id, total=total, resources=task_resources.for_kind("draw"))
    _persist_job(BATCH_JOBS[job_id])
    threading.Thread(target=_run_batch, args=(job_id, groups, generation_config), daemon=True).start()
    return {"batch_id": job_id, "total": total, "status": "running"}


@router.get("/api/draw/batch/{batch_id}")
def draw_batch_status(batch_id: str) -> dict:
    """查询批量绘画任务进度。"""
    job = BATCH_JOBS.get(batch_id)
    if not job:
        job = database.get_batch_job(batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="batch not found")
    return job


@router.post("/api/draw/batch/{batch_id}/stop")
def stop_batch(batch_id: str) -> dict:
    """请求停止批量绘画任务（当前图完成后停止）。"""
    job = BATCH_JOBS.get(batch_id)
    if not job:
        job = database.get_batch_job(batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="batch not found")
    job["stop_requested"] = True
    _persist_job(job)
    return {"ok": True}


def restore_batch_jobs() -> None:
    """后端启动时把运行中的批量任务标记为中断。"""
    for job in database.list_batch_jobs():
        if job.get("status") == "running":
            job["status"] = "interrupted"
            job["error"] = "后端重启中断，任务无法继续"
            job["finished_at"] = database.now_iso()
            database.save_batch_job(job)


@router.post("/api/draw")
def draw(payload: dict = Body(...)):
    """兼容旧接口：单张绘画，同步返回结果。"""
    model = _validate_model(payload.get("model"))
    prompt, negative_prompt, prompt_document_json = _resolve_draw_document(
        str(payload.get("prompt") or ""),
        payload.get("prompt_document"),
        str(payload.get("negative_prompt") or ""),
    )
    _validate_lora_compatibility(payload.get("loras") or [])
    other_tasks = [task for task in task_state.running_tasks() if task["type"] != "draw"]
    if other_tasks:
        labels = "、".join(task["label"] for task in other_tasks)
        raise HTTPException(status_code=409, detail=f"有其他项目正在运行（{labels}），请稍后再进行")
    settings = _parse_draw_settings(payload)
    result = _generate_and_record(
        prompt,
        negative_prompt,
        settings["width"],
        settings["height"],
        settings["steps"],
        settings["cfg"],
        model,
        payload.get("loras") or [],
        payload.get("seed"),
        None,
        0,
        0,
        settings["lora_strength_model"],
        settings["lora_strength_clip"],
        settings["lora_strengths"],
        prompt_document_json=prompt_document_json,
    )
    return result


# ---------------------------------------------------------------------------
# Reference-image local inpaint (v1)
# ---------------------------------------------------------------------------


def _inpaint_source_path(source_id: str) -> Path:
    if not INPAINT_SOURCE_RE.match(source_id):
        raise HTTPException(status_code=404, detail="参考图不存在")
    path = (INPAINT_SOURCE_DIR / f"{source_id}.png").resolve()
    if INPAINT_SOURCE_DIR.resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="参考图不存在")
    return path


def _inpaint_source_meta_path(source_id: str) -> Path:
    return _inpaint_source_path(source_id).with_suffix(".json")


def _read_inpaint_source_meta(source_id: str) -> dict | None:
    path = _inpaint_source_meta_path(source_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _validate_inpaint_text(text: str) -> None:
    if content_filter.is_always_blocked(text):
        raise HTTPException(status_code=403, detail="该内容被禁止生成")
    if content_restriction_enabled() and content_filter.is_nsfw(text):
        raise HTTPException(status_code=403, detail="内容限制已开启，已阻止该请求")


def _normalize_inpaint_source(data: bytes) -> tuple[Image.Image, dict]:
    if len(data) > INPAINT_MAX_SOURCE_BYTES:
        raise HTTPException(status_code=413, detail="参考图不能超过 20 MB")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            fmt = (opened.format or "").upper()
            if fmt not in {"PNG", "JPEG", "WEBP"}:
                raise HTTPException(status_code=400, detail="参考图只支持 PNG/JPEG/WebP")
            opened.load()
            image = ImageOps.exif_transpose(opened).copy()
            had_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
            if had_alpha:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="参考图格式无法识别") from None

    original_width, original_height = image.size
    if min(original_width, original_height) < INPAINT_MIN_SIDE:
        raise HTTPException(status_code=400, detail="参考图最短边不能小于 64 px")
    if max(original_width, original_height) > INPAINT_MAX_SIDE:
        raise HTTPException(status_code=413, detail="参考图最长边不能超过 4096 px")
    working_width = (original_width // 8) * 8
    working_height = (original_height // 8) * 8
    if min(working_width, working_height) < INPAINT_MIN_SIDE:
        raise HTTPException(status_code=400, detail="参考图裁到 8 的倍数后小于 64 px")
    working = image.crop((0, 0, working_width, working_height))
    return working, {
        "width": working_width,
        "height": working_height,
        "working_width": working_width,
        "working_height": working_height,
        "original_width": original_width,
        "original_height": original_height,
        "had_alpha": had_alpha,
        "created_at": database.now_iso(),
    }


def _create_inpaint_source(data: bytes) -> tuple[str, Path, dict]:
    working, meta = _normalize_inpaint_source(data)
    source_id = f"src_{uuid.uuid4().hex}"
    INPAINT_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    path = _inpaint_source_path(source_id)
    working.save(path, format="PNG")
    meta["source_id"] = source_id
    _inpaint_source_meta_path(source_id).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return source_id, path, meta


def _resolve_inpaint_source(payload: dict) -> tuple[str, Path, int, int, int | None]:
    source_id = str(payload.get("source_id") or "").strip()
    raw_record = payload.get("source_record_id")
    if source_id and raw_record not in (None, ""):
        raise HTTPException(status_code=400, detail="source_id 和 source_record_id 只能二选一")
    if source_id:
        path = _inpaint_source_path(source_id)
        meta = _read_inpaint_source_meta(source_id)
        if not path.exists() or not meta:
            raise HTTPException(status_code=404, detail="参考图不存在")
        return (
            source_id,
            path,
            int(meta.get("working_width") or meta.get("width") or 0),
            int(meta.get("working_height") or meta.get("height") or 0),
            None,
        )
    if raw_record in (None, ""):
        raise HTTPException(status_code=400, detail="必须提供 source_id 或 source_record_id")
    try:
        record_id = int(raw_record)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="source_record_id 格式不正确") from None
    record = database.get_draw_image(record_id)
    if not record or not record.get("image_path"):
        raise HTTPException(status_code=404, detail="来源图片记录不存在")
    image_path = Path(str(record["image_path"])).resolve()
    if AI_PRODUCT_DIR.resolve() not in image_path.parents:
        raise HTTPException(status_code=400, detail="来源图片不在允许目录内")
    try:
        data = image_path.read_bytes()
    except OSError:
        raise HTTPException(status_code=404, detail="来源图片文件不存在") from None
    created_id, path, meta = _create_inpaint_source(data)
    return (
        created_id,
        path,
        int(meta["working_width"]),
        int(meta["working_height"]),
        record_id,
    )


def _decode_inpaint_mask(raw: object, width: int, height: int) -> Image.Image:
    text = str(raw or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="mask 不能为空")
    if text.startswith("data:"):
        if "," not in text:
            raise HTTPException(status_code=400, detail="mask data URL 格式不正确")
        text = text.split(",", 1)[1]
    if len(text) > INPAINT_MAX_MASK_BASE64:
        raise HTTPException(status_code=413, detail="mask 数据过大")
    try:
        data = base64.b64decode(text, validate=True)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="mask base64 解码失败") from None
    try:
        with Image.open(io.BytesIO(data)) as opened:
            if (opened.format or "").upper() != "PNG":
                raise HTTPException(status_code=400, detail="mask 必须是 PNG")
            mask = opened.convert("L")
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="mask 格式无法识别") from None
    if mask.size != (width, height):
        raise HTTPException(
            status_code=400,
            detail=f"mask 尺寸必须是 {width}x{height}，当前为 {mask.size[0]}x{mask.size[1]}",
        )
    if mask.getbbox() is None:
        raise HTTPException(status_code=400, detail="mask 不能为空白")
    return mask


def _public_inpaint_job(job: dict) -> dict:
    status = str(job.get("status") or "failed")
    error = job.get("error")
    results = job.get("results") or []
    first_result = results[0] if results else {}
    error_obj = None
    if error:
        error_obj = {
            "code": str(job.get("error_code") or ("CANCELLED" if status == "cancelled" else "INPAINT_FAILED")),
            "message": str(error),
        }
    return {
        "job_id": str(job.get("job_id") or job.get("batch_id") or ""),
        "status": status,
        "progress": {
            "completed": int(job.get("done") or 0),
            "total": int(job.get("total") or 0),
        },
        "source_id": job.get("source_id") or first_result.get("source_id"),
        "width": job.get("width") or first_result.get("width"),
        "height": job.get("height") or first_result.get("height"),
        "results": results,
        "error": error_obj,
        "created_at": job.get("created_at"),
        "finished_at": job.get("finished_at"),
    }


def _persist_inpaint_job(job: dict) -> None:
    job_id = str(job.get("job_id") or job.get("batch_id") or "")
    if not job_id:
        return
    try:
        database.save_batch_job(
            {
                "batch_id": job_id,
                "status": job.get("status"),
                "total": int(job.get("total") or 0),
                "done": int(job.get("done") or 0),
                "current_group": 0,
                "results": job.get("results") or [],
                "error": job.get("error"),
                "created_at": job.get("created_at"),
                "finished_at": job.get("finished_at"),
                "stop_requested": bool(job.get("stop_requested")),
                "mode": "inpaint",
            }
        )
    except Exception:
        pass


def _cleanup_inpaint_inputs(job: dict) -> None:
    for name in (job.get("comfy_source_name"), job.get("comfy_mask_name")):
        if not name:
            continue
        try:
            (config.COMFY_INPUT_DIR / str(name)).unlink(missing_ok=True)
        except OSError:
            pass


def _run_inpaint_job(job_id: str) -> None:
    job = INPAINT_JOBS.get(job_id)
    if not job:
        return
    job["status"] = "running"
    _persist_inpaint_job(job)
    error_code: str | None = None
    error: str | None = None
    try:
        for index in range(int(job["total"])):
            if job.get("stop_requested"):
                break
            base_seed = job.get("seed")
            seed = (
                min(config.DRAW_SEED_MAX, int(base_seed) + index)
                if base_seed is not None
                else random.randint(0, config.DRAW_SEED_MAX)
            )
            edit_params = {
                "source_id": job["source_id"],
                "grow": job["grow"],
                "feather": job["feather"],
                "count": job["total"],
                "model": job["model"],
                "loras": job["loras"],
                "lora_strengths": job["lora_strengths"],
                "seed": seed,
            }
            record_id = database.insert_draw_start(
                job["prompt"],
                translate_text(job["prompt"]),
                job["negative_prompt"],
                translate_text(job["negative_prompt"]),
                job["width"],
                job["height"],
                job["steps"],
                job["cfg"],
                job["model"],
                lora_anima_turbo=any("anima-turbo" in str(name) for name in job["loras"]),
                lora_high_contrast=any("high-contrast" in str(name) for name in job["loras"]),
                loras=job["loras"],
                group_index=index,
                prompt_document_json=job["prompt_document_json"],
                edit_mode="inpaint",
                source_record_id=job.get("source_record_id"),
                source_image_path=job["source_path"],
                mask_image_path=job["mask_path"],
                masked_prompt=job["masked_prompt"],
                inpaint_denoise=job["denoise"],
                edit_params_json=json.dumps(edit_params, ensure_ascii=False),
            )
            started = time.time()
            try:
                result = generate_inpaint(
                    source_image=job["comfy_source_name"],
                    mask_image=job["comfy_mask_name"],
                    prompt=job["prompt"],
                    negative_prompt=job["negative_prompt"],
                    masked_prompt=job["masked_prompt"],
                    model_name=job["model"],
                    loras=job["loras"],
                    seed=seed,
                    steps=job["steps"],
                    cfg=job["cfg"],
                    denoise=job["denoise"],
                    grow=job["grow"],
                    feather=job["feather"],
                    lora_strength_model=job["lora_strength_model"],
                    lora_strength_clip=job["lora_strength_clip"],
                    lora_strengths=job["lora_strengths"],
                    cancel_event=job.get("cancel_event"),
                )
                elapsed_ms = int((time.time() - started) * 1000)
                database.finish_draw(
                    record_id,
                    round(elapsed_ms / 1000, 2),
                    result.get("saved_path"),
                    result.get("image_url"),
                    result.get("seed"),
                    "success",
                )
                job["results"].append(
                    {
                        "record_id": record_id,
                        "image_url": result.get("image_url"),
                        "seed": result.get("seed"),
                        "denoise": job["denoise"],
                        "width": job["width"],
                        "height": job["height"],
                        "source_id": job["source_id"],
                        "elapsed_ms": elapsed_ms,
                    }
                )
                job["done"] = index + 1
                _persist_inpaint_job(job)
            except Exception as exc:  # noqa: BLE001
                message = "任务已取消" if job.get("stop_requested") else str(exc)
                database.finish_draw(
                    record_id,
                    round(time.time() - started, 2),
                    None,
                    None,
                    None,
                    "error",
                    message,
                )
                raise
    except Exception as exc:  # noqa: BLE001
        error_code = "INPAINT_FAILED"
        error = str(exc)
    finally:
        if job.get("stop_requested"):
            job["status"] = "cancelled"
            job["error"] = "已手动停止"
            job["error_code"] = "CANCELLED"
        elif error:
            job["status"] = "failed"
            job["error"] = error
            job["error_code"] = error_code
        else:
            job["status"] = "succeeded"
            job["error"] = None
            job["error_code"] = None
        job["finished_at"] = database.now_iso()
        _persist_inpaint_job(job)
        try:
            registry_status = {
                "succeeded": "done",
                "failed": "error",
                "cancelled": "cancelled",
                "interrupted": "interrupted",
            }.get(job["status"], job["status"])
            task_registry.finish("draw", job_id, registry_status, job.get("error"))
        except Exception:
            pass
        _cleanup_inpaint_inputs(job)


@router.post("/api/draw/inpaint/sources")
def upload_inpaint_source(file: UploadFile = File(...)):
    data = file.file.read(INPAINT_MAX_SOURCE_BYTES + 1)
    if len(data) > INPAINT_MAX_SOURCE_BYTES:
        raise HTTPException(status_code=413, detail="参考图不能超过 20 MB")
    source_id, _, meta = _create_inpaint_source(data)
    return {
        "source_id": source_id,
        "width": meta["original_width"],
        "height": meta["original_height"],
        "working_width": meta["working_width"],
        "working_height": meta["working_height"],
        "preview_url": f"/api/draw/inpaint/sources/{source_id}/preview",
    }


@router.get("/api/draw/inpaint/sources/{source_id}/preview")
def inpaint_source_preview(source_id: str):
    path = _inpaint_source_path(source_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="参考图不存在")
    return Response(path.read_bytes(), media_type="image/png")


@router.post("/api/draw/inpaint/jobs", status_code=202)
def create_inpaint_job(payload: dict = Body(...)):
    source_id, source_path, width, height, source_record_id = _resolve_inpaint_source(payload)
    prompt, negative_prompt, prompt_document_json = _resolve_draw_document(
        str(payload.get("prompt") or ""),
        payload.get("prompt_document"),
        str(payload.get("negative_prompt") or ""),
    )
    prompt, negative_prompt = _prepare_prompts(prompt, negative_prompt)
    masked_prompt = str(payload.get("masked_prompt") or "").strip() or prompt
    _validate_inpaint_text(masked_prompt)
    model = _validate_model(payload.get("model"))
    loras = [str(item) for item in (payload.get("loras") or []) if str(item).strip()]
    _validate_lora_compatibility(loras)

    try:
        count = int(payload.get("count", 2))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="候选数格式不正确") from None
    if count < 1 or count > 4:
        raise HTTPException(status_code=400, detail="候选数必须在 1-4 之间")
    raw_seed = payload.get("seed")
    if raw_seed in (None, ""):
        seed = None
    else:
        try:
            seed = int(raw_seed)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="seed 格式不正确") from None
        if seed < config.DRAW_SEED_MIN or seed > config.DRAW_SEED_MAX:
            raise HTTPException(status_code=400, detail="seed 超出允许范围")
    try:
        steps = int(payload.get("steps", config.DRAW_DEFAULT_STEPS))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="步数格式不正确") from None
    if steps < 1 or steps > 60:
        raise HTTPException(status_code=400, detail="步数必须在 1-60 之间")
    try:
        cfg = float(payload.get("cfg", config.DRAW_DEFAULT_CFG))
        denoise = float(payload.get("denoise", 0.75))
        grow = int(payload.get("grow", 12))
        feather = int(payload.get("feather", 8))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="重绘参数格式不正确") from None
    if cfg < 0 or cfg > 30:
        raise HTTPException(status_code=400, detail="CFG 必须在 0-30 之间")
    if denoise < 0.2 or denoise > 1.0:
        raise HTTPException(status_code=400, detail="denoise 必须在 0.2-1.0 之间")
    if grow < 0 or grow > 64 or feather < 0 or feather > 64:
        raise HTTPException(status_code=400, detail="grow/feather 必须在 0-64 之间")

    mask = _decode_inpaint_mask(payload.get("mask_base64"), width, height)
    lora_strengths = _parse_lora_strengths(payload.get("lora_strengths"))
    other_tasks = [task for task in task_state.running_tasks() if task["type"] != "draw"]
    if other_tasks:
        labels = "、".join(task["label"] for task in other_tasks)
        raise HTTPException(status_code=409, detail=f"有其他项目正在运行（{labels}），请稍后再进行")
    job_id = f"inp_{uuid.uuid4().hex}"
    INPAINT_MASK_DIR.mkdir(parents=True, exist_ok=True)
    mask_path = INPAINT_MASK_DIR / f"{job_id}_mask.png"
    mask.save(mask_path, format="PNG")
    config.COMFY_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    comfy_source_name = f"{job_id}_source.png"
    comfy_mask_name = f"{job_id}_mask.png"
    (config.COMFY_INPUT_DIR / comfy_source_name).write_bytes(source_path.read_bytes())
    (config.COMFY_INPUT_DIR / comfy_mask_name).write_bytes(mask_path.read_bytes())

    job = {
        "job_id": job_id,
        "status": "queued",
        "total": count,
        "done": 0,
        "current_group": 0,
        "results": [],
        "error": None,
        "error_code": None,
        "created_at": database.now_iso(),
        "finished_at": None,
        "stop_requested": False,
        "source_id": source_id,
        "source_record_id": source_record_id,
        "source_path": str(source_path),
        "mask_path": str(mask_path),
        "width": width,
        "height": height,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "prompt_document_json": prompt_document_json,
        "masked_prompt": masked_prompt,
        "denoise": denoise,
        "seed": seed,
        "model": model,
        "loras": loras,
        "lora_strengths": lora_strengths,
        "steps": steps,
        "cfg": cfg,
        "grow": grow,
        "feather": feather,
        "comfy_source_name": comfy_source_name,
        "comfy_mask_name": comfy_mask_name,
        "lora_strength_model": config.DRAW_DEFAULT_LORA_STRENGTH_MODEL,
        "lora_strength_clip": config.DRAW_DEFAULT_LORA_STRENGTH_CLIP,
        "cancel_event": threading.Event(),
    }
    with INPAINT_LOCK:
        if any(item.get("status") in {"queued", "running"} for item in INPAINT_JOBS.values()):
            _cleanup_inpaint_inputs(job)
            raise HTTPException(status_code=409, detail="已有局部重绘任务在运行，请等待完成或先取消")
        INPAINT_JOBS[job_id] = job
    try:
        task_registry.register("draw", job_id, total=count, resources=task_resources.for_kind("draw"))
    except database.ResourceConflictError as exc:
        INPAINT_JOBS.pop(job_id, None)
        _cleanup_inpaint_inputs(job)
        raise HTTPException(status_code=409, detail=task_resources.conflict_message(exc)) from exc
    _persist_inpaint_job(job)
    threading.Thread(target=_run_inpaint_job, args=(job_id,), daemon=True).start()
    return {"job_id": job_id, "status": "queued", "created_at": job["created_at"]}


@router.get("/api/draw/inpaint/jobs/{job_id}")
def inpaint_job_status(job_id: str):
    job = INPAINT_JOBS.get(job_id)
    if not job:
        job = database.get_batch_job(job_id)
        if not job or job.get("mode") != "inpaint":
            raise HTTPException(status_code=404, detail="局部重绘任务不存在")
        if job.get("status") == "running":
            job["status"] = "interrupted"
            job["error"] = "后端重启中断，任务无法继续"
            job["error_code"] = "INTERRUPTED"
    return _public_inpaint_job(job)


@router.post("/api/draw/inpaint/jobs/{job_id}/cancel")
def cancel_inpaint_job(job_id: str):
    job = INPAINT_JOBS.get(job_id)
    if not job:
        job = database.get_batch_job(job_id)
        if not job or job.get("mode") != "inpaint":
            raise HTTPException(status_code=404, detail="局部重绘任务不存在")
    if job.get("status") in {"succeeded", "failed", "cancelled", "interrupted"}:
        return _public_inpaint_job(job)
    job["stop_requested"] = True
    job["status"] = "cancelled"
    job["error"] = "已手动停止"
    job["error_code"] = "CANCELLED"
    job["finished_at"] = database.now_iso()
    cancel_event = job.get("cancel_event")
    if cancel_event is not None:
        cancel_event.set()
    _persist_inpaint_job(job)
    # 运行中的内存任务由 worker 在当前候选结束后统一释放资源，避免
    # 取消响应先释放 GPU/ComfyUI 而当前 ComfyUI prompt 仍在执行。
    if job_id not in INPAINT_JOBS:
        try:
            task_registry.finish("draw", job_id, "cancelled", job["error"])
        except Exception:
            pass
    return _public_inpaint_job(job)
