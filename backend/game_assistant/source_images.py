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


def vision_analyze(image_bytes: bytes, model: str) -> dict:
    prompt = (
        "你是 FGO 攻略图片事实提取器。仅依据图片中直接可见的内容，提取全部文字、关卡、敌人、"
        "从者、礼装、操作顺序和注意事项。不要猜测。只输出 JSON 对象，格式为 "
        "{\"text\":\"图片全部可见文字\",\"facts\":[{\"kind\":\"quest|enemy|servant|craft_essence|mystic_code|mechanic|note\","
        "\"value\":\"事实内容\",\"evidence\":\"对应文字或区域\"}],\"warnings\":[]}。"
    )
    response = requests.post(
        config.OLLAMA_BASE.rstrip("/") + "/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "images": [base64.b64encode(image_bytes).decode("ascii")],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 1800, "num_ctx": 8192},
        },
        timeout=config.GAME_ASSISTANT_LLM_TIMEOUT,
    )
    response.raise_for_status()
    return _extract_json(((response.json().get("response") or "").strip()))


def prepare_images(source_id: str, store: SourceStore, max_images: int = 20) -> SourceImagePrepareResult:
    record = store.get(source_id)
    if record is None:
        raise SourceError("来源快照不存在")
    if not record.images:
        raise SourceError("该来源没有检测到图片")
    asset_dir = config.GAME_ASSISTANT_SOURCE_ASSET_DIR / source_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    existing = {asset.url: asset for asset in record.image_assets if asset.status == "downloaded"}
    assets: list[SourceImageAsset] = []
    for index, url in enumerate(record.images[:max_images], start=1):
        prior = existing.get(url)
        if prior is not None:
            assets.append(prior)
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


def analyze_images(source_id: str, store: SourceStore, model: str = "") -> SourceImageAnalysisResult:
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
        if asset.status != "downloaded" or not asset.local_path:
            asset.analysis_status = "failed"
            asset.analysis_error = "图片尚未下载成功"
            continue
        try:
            result = vision_analyze(Path(asset.local_path).read_bytes(), model=use_model)
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
