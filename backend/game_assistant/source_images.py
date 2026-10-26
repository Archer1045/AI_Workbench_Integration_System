"""Download and locally analyze image-only guide sources."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

import requests

import config

from .source_domain import SourceImageAnalysisResult, SourceImageAsset, SourceImagePrepareResult
from .source_service import SourceError, _extract_json, _validate_public_url
from .source_store import SourceStore


def _ollama_generate(
    image_bytes: bytes,
    model: str,
    prompt: str,
    *,
    json_response: bool,
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [base64.b64encode(image_bytes).decode("ascii")],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": config.GAME_ASSISTANT_VLM_NUM_PREDICT,
            "num_ctx": config.GAME_ASSISTANT_VLM_NUM_CTX,
        },
    }
    if json_response:
        payload["format"] = "json"
    response = requests.post(
        config.OLLAMA_BASE.rstrip("/") + "/api/generate",
        json=payload,
        timeout=config.GAME_ASSISTANT_LLM_TIMEOUT,
    )
    response.raise_for_status()
    return str(response.json().get("response") or "").strip()


def vision_analyze(
    image_bytes: bytes,
    model: str,
    *,
    section: str = "",
    caption: str = "",
) -> dict:
    context_hint = ""
    if section or caption:
        context_hint = (
            f"\n来源章节提示（只用于定位，不得当作图片内可见证据）："
            f"{section or '无'}；图片说明：{caption or '无'}。"
        )
    prompt = (
        "你是 FGO 攻略图片事实提取器。仅依据图片中直接可见的内容，提取全部文字、关卡、敌人、"
        "从者、礼装、操作顺序和注意事项。不要猜测。只输出 JSON 对象，格式为 "
        "{\"text\":\"图片全部可见文字\",\"facts\":[{\"kind\":\"quest|enemy|servant|craft_essence|mystic_code|mechanic|note\","
        "\"value\":\"事实内容\",\"evidence\":\"对应文字或区域\"}],\"warnings\":[]}。"
        f"{context_hint}"
    )
    raw = _ollama_generate(image_bytes, model, prompt, json_response=True)
    try:
        return _extract_json(raw)
    except SourceError:
        # A dense guide image can make the model close JSON incorrectly even
        # with a large token budget. Preserve visible OCR as review-only text
        # instead of discarding the entire image.
        fallback_prompt = (
            "你是 OCR 工具。逐行提取图片中所有可见文字，保留关卡名、从者名、"
            "礼装名、数字、符号和操作顺序。不要解释、不要补充、不要输出 JSON。"
            f"{context_hint}"
        )
        fallback_text = _ollama_generate(
            image_bytes,
            model,
            fallback_prompt,
            json_response=False,
        )
        if not fallback_text:
            raise SourceError("模型没有返回可复核的图片文字")
        return {
            "text": fallback_text,
            "facts": [],
            "warnings": ["结构化 JSON 失败，已降级为纯文本 OCR，请人工核对。"],
        }


def prepare_images(
    source_id: str,
    store: SourceStore,
    max_images: int | None = None,
) -> SourceImagePrepareResult:
    record = store.get(source_id)
    if record is None:
        raise SourceError("来源快照不存在")
    if not record.images:
        raise SourceError("该来源没有检测到图片")
    asset_dir = config.GAME_ASSISTANT_SOURCE_ASSET_DIR / source_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    existing = {asset.url: asset for asset in record.image_assets if asset.status == "downloaded"}
    assets: list[SourceImageAsset] = []
    image_limit = max(
        1,
        min(
            int(max_images or config.GAME_ASSISTANT_SOURCE_IMAGE_MAX_COUNT),
            config.GAME_ASSISTANT_SOURCE_IMAGE_MAX_COUNT,
        ),
    )
    for index, url in enumerate(record.images[:image_limit], start=1):
        context = next(
            (
                item
                for item in record.image_contexts
                if item.image_id == f"img-{index:02d}" and item.url == url
            ),
            None,
        )
        prior = existing.get(url)
        if prior is not None:
            assets.append(
                prior.model_copy(
                    update={
                        "paragraph_index": context.paragraph_index if context else prior.paragraph_index,
                        "section": context.section if context else prior.section,
                        "caption": context.caption if context else prior.caption,
                        "width": context.width if context else prior.width,
                        "height": context.height if context else prior.height,
                    }
                )
            )
            continue
        image_id = f"img-{index:02d}"
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            suffix = ".img"
        target = asset_dir / f"{image_id}{suffix}"
        try:
            _validate_public_url(url)
            response = requests.get(
                url,
                headers={"User-Agent": "AI-Workbench-Game-Assistant/1.0", "Referer": record.final_url or record.url},
                timeout=config.GAME_ASSISTANT_SOURCE_TIMEOUT,
                stream=True,
            )
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if content_type and not content_type.lower().startswith("image/") and suffix == ".img":
                raise SourceError(f"图片内容类型不支持: {content_type}")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > config.GAME_ASSISTANT_SOURCE_IMAGE_MAX_BYTES:
                    raise SourceError("图片超过大小限制")
                chunks.append(chunk)
            body = b"".join(chunks)
            if not body:
                raise SourceError("图片内容为空")
            temp = target.with_suffix(target.suffix + ".part")
            temp.write_bytes(body)
            temp.replace(target)
            assets.append(SourceImageAsset(
                image_id=image_id,
                url=url,
                paragraph_index=context.paragraph_index if context else 0,
                section=context.section if context else "",
                caption=context.caption if context else "",
                width=context.width if context else 0,
                height=context.height if context else 0,
                local_path=str(target),
                mime_type=content_type,
                byte_size=len(body),
                sha256=hashlib.sha256(body).hexdigest().upper(),
                status="downloaded",
            ))
        except Exception as exc:
            assets.append(SourceImageAsset(image_id=image_id, url=url, status="failed", error=f"{type(exc).__name__}: {exc}"))
    record.image_assets = assets
    store.save(record)
    return SourceImagePrepareResult(source_id=source_id, total=len(assets), downloaded=sum(a.status == "downloaded" for a in assets), failed=sum(a.status == "failed" for a in assets), images=assets)


def analyze_images(
    source_id: str,
    store: SourceStore,
    model: str = "",
    *,
    retry_failed_only: bool = False,
) -> SourceImageAnalysisResult:
    record = store.get(source_id)
    if record is None:
        raise SourceError("来源快照不存在")
    if not record.image_assets:
        prepare_images(source_id, store)
        record = store.get(source_id)
        if record is None:
            raise SourceError("来源快照不存在")
    use_model = model or config.VLM_MODEL
    combined: list[str] = []
    for asset in record.image_assets:
        if retry_failed_only and asset.analysis_status == "completed":
            if asset.analysis_text:
                combined.append(f"[{asset.image_id}] {asset.analysis_text}")
            continue
        if asset.status != "downloaded" or not asset.local_path:
            asset.analysis_status = "failed"
            asset.analysis_error = "图片尚未下载成功"
            continue
        try:
            result = vision_analyze(
                Path(asset.local_path).read_bytes(),
                model=use_model,
                section=asset.section,
                caption=asset.caption,
            )
            asset.analysis_status = "completed"
            asset.analysis_text = str(result.get("text") or "")
            asset.analysis_facts = list(result.get("facts") or [])
            asset.analysis_error = ""
            if asset.analysis_text:
                combined.append(f"[{asset.image_id}] {asset.analysis_text}")
        except Exception as exc:
            asset.analysis_status = "failed"
            asset.analysis_error = f"{type(exc).__name__}: {exc}"
    store.save(record)
    return SourceImageAnalysisResult(source_id=source_id, model=use_model, completed=sum(a.analysis_status == "completed" for a in record.image_assets), failed=sum(a.analysis_status == "failed" for a in record.image_assets), combined_text="\n\n".join(combined), images=record.image_assets)
