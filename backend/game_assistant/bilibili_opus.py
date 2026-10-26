"""Bilibili Opus image-guide extraction through the public web API."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

import config

from .source_domain import SourceImageContext

_OPUS_PATH = re.compile(r"^/opus/(\d+)/?$")
_API_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/detail"


class BilibiliOpusError(ValueError):
    """Raised when an Opus URL cannot be resolved into ordered content."""


@dataclass(frozen=True)
class BilibiliOpusContent:
    opus_id: str
    final_url: str
    title: str
    publisher: str
    text: str
    images: list[str]
    image_contexts: list[SourceImageContext]
    http_status: int
    warnings: list[str]


def opus_id_from_url(url: str) -> str | None:
    parsed = urlparse(str(url or "").strip())
    if parsed.hostname not in {"www.bilibili.com", "bilibili.com"}:
        return None
    match = _OPUS_PATH.match(parsed.path)
    return match.group(1) if match else None


def _module(item: dict, module_type: str) -> dict:
    for module in item.get("modules") or []:
        if module.get("module_type") == module_type:
            return module
    return {}


def _text_nodes(paragraph: dict) -> str:
    values: list[str] = []
    text = paragraph.get("text") or {}
    for node in text.get("nodes") or []:
        word = node.get("word") or {}
        value = str(word.get("words") or "").strip()
        if not value:
            rich = node.get("rich") or {}
            value = str(rich.get("text") or rich.get("orig_text") or "").strip()
        if value:
            values.append(value)
    return "".join(values).strip()


def _normalise_image_url(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("//"):
        return f"https:{text}"
    if text.startswith("http://"):
        return f"https://{text[7:]}"
    return text


def parse_opus_payload(payload: dict, *, final_url: str) -> BilibiliOpusContent:
    if int(payload.get("code") or 0) != 0:
        raise BilibiliOpusError(str(payload.get("message") or "Bilibili Opus API 返回错误"))
    item = ((payload.get("data") or {}).get("item") or {})
    if not item:
        raise BilibiliOpusError("Bilibili Opus 没有返回正文")

    title_module = _module(item, "MODULE_TYPE_TITLE")
    title = str(((title_module.get("module_title") or {}).get("text") or "")).strip()
    author_module = _module(item, "MODULE_TYPE_AUTHOR")
    author = author_module.get("module_author") or {}
    publisher = str(author.get("name") or "").strip()
    paragraphs = (
        ((_module(item, "MODULE_TYPE_CONTENT").get("module_content") or {}).get("paragraphs"))
        or []
    )

    lines: list[str] = []
    image_urls: list[str] = []
    contexts: list[SourceImageContext] = []
    latest_section = ""
    for paragraph_index, paragraph in enumerate(paragraphs, start=1):
        paragraph_text = _text_nodes(paragraph)
        if paragraph_text:
            latest_section = paragraph_text[:240]
            lines.append(paragraph_text)

        pic_module = paragraph.get("pic") or {}
        for pic in pic_module.get("pics") or []:
            url = _normalise_image_url(str(pic.get("url") or ""))
            if not url:
                continue
            image_id = f"img-{len(image_urls) + 1:02d}"
            image_urls.append(url)
            contexts.append(
                SourceImageContext(
                    image_id=image_id,
                    url=url,
                    paragraph_index=paragraph_index,
                    section=latest_section,
                    caption=str(pic.get("comment") or "").strip(),
                    width=int(pic.get("width") or 0),
                    height=int(pic.get("height") or 0),
                )
            )
            label = latest_section or "未命名章节"
            lines.append(f"[图片 {image_id} | {label}]")

    warnings: list[str] = []
    if not lines:
        warnings.append("Opus 没有可提取的文字或图片")
    elif not image_urls:
        warnings.append("Opus 没有检测到图片")

    return BilibiliOpusContent(
        opus_id=str(item.get("id_str") or ""),
        final_url=final_url,
        title=title or "Bilibili Opus",
        publisher=publisher,
        text="\n".join(lines).strip(),
        images=image_urls,
        image_contexts=contexts,
        http_status=200,
        warnings=warnings,
    )


def fetch_opus_content(url: str) -> BilibiliOpusContent:
    opus_id = opus_id_from_url(url)
    if not opus_id:
        raise BilibiliOpusError("不是受支持的 Bilibili Opus URL")
    try:
        response = requests.get(
            _API_URL,
            params={"timezone_offset": -480, "id": opus_id},
            headers={
                # Bilibili's anti-bot endpoint currently accepts this generic
                # UA and returns -352 for a more specific Chrome UA.
                "User-Agent": "Mozilla/5.0",
                "Referer": f"https://www.bilibili.com/opus/{opus_id}",
            },
            timeout=config.GAME_ASSISTANT_SOURCE_TIMEOUT,
        )
        response.raise_for_status()
        if len(response.content) > config.GAME_ASSISTANT_SOURCE_MAX_BYTES:
            raise BilibiliOpusError("Bilibili Opus API 响应超过大小限制")
        payload = response.json()
        parsed = parse_opus_payload(payload, final_url=url)
        return BilibiliOpusContent(
            **{
                **parsed.__dict__,
                "opus_id": parsed.opus_id or opus_id,
                "http_status": response.status_code,
            }
        )
    except BilibiliOpusError:
        raise
    except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
        raise BilibiliOpusError(
            f"Bilibili Opus API 读取失败：{type(exc).__name__}: {exc}"
        ) from exc
