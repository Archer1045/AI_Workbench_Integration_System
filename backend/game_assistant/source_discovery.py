"""Whitelisted source discovery for the FGO game assistant.

Search results are candidates only. Discovery never publishes an event bundle;
the existing source snapshot, extraction preview, and explicit confirmation
gates still apply after ingestion.
"""
from __future__ import annotations

import html as html_mod
import json
import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlparse

from web_tools import SearchResult, WebToolsError, get_web_tools_service

OFFICIAL_DOMAINS = (
    "biligame.com",
    "fgo.163.com",
    "game.bilibili.com",
)
WIKI_DOMAINS = ("fgo.wiki",)
ALLOWED_DOMAINS = OFFICIAL_DOMAINS + WIKI_DOMAINS

# 国服助手不把日服官网公告当作国服事实来源；日服内容只允许作为
# Mooncell 的「日服·参考」存在，不能直接进入国服活动 bundle。

_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)")
_RAW_IMAGE = re.compile(
    r"https?://[^\s\"'<>]+?\.(?:jpg|jpeg|png|webp)(?:\?[^\s\"'<>]*)?",
    flags=re.IGNORECASE,
)
_SCRIPT_STYLE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", flags=re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_PUNCT_ESCAPE = re.compile(r"\\(?=[^A-Za-z0-9\s])")


def normalized_host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").rstrip(".").lower()
    except ValueError:
        return ""


def host_allowed(host: str) -> bool:
    value = host.rstrip(".").lower()
    return any(value == domain or value.endswith("." + domain) for domain in ALLOWED_DOMAINS)


def url_allowed(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and host_allowed(parsed.hostname)


def source_type_for(host: str) -> str:
    value = host.rstrip(".").lower()
    if any(value == domain or value.endswith("." + domain) for domain in WIKI_DOMAINS):
        return "wiki"
    return "official"


def discovery_query(query: str, days: int) -> str:
    value = query.strip()
    if days > 0:
        since = (date.today() - timedelta(days=days)).isoformat()
        value = f"{value} after:{since}"
    return value[:128]


def filter_results(
    results: list[SearchResult],
    *,
    limit: int = 8,
    min_authority: int = 2,
) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    filtered = 0
    for item in results:
        host = normalized_host(item.url)
        if not host_allowed(host):
            filtered += 1
            continue
        if item.authority is not None and item.authority < min_authority:
            filtered += 1
            continue
        key = item.url.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "title": item.title,
                "url": item.url,
                "summary": item.summary or item.snippet,
                "date": item.date,
                "authority": item.authority,
                "site_name": item.site_name,
                "source_type": source_type_for(host),
            }
        )
        if len(items) >= limit:
            break
    return items, filtered


def discover(query: str, *, count: int = 8, days: int = 60) -> dict[str, Any]:
    value = str(query or "").strip()
    if not value:
        raise WebToolsError("搜索词不能为空")
    service = get_web_tools_service()
    response = service.search(
        discovery_query(value, days),
        count=max(1, min(count, 20)),
        ori_question=value,
        need_content=False,
        app="game-assistant-source-discover",
    )
    items, filtered = filter_results(response.results, limit=count)
    return {
        "provider": response.provider,
        "cached": response.cached,
        "query": value,
        "results": items,
        "filtered_out": filtered,
    }


def extract_image_urls(markdown: str) -> list[str]:
    values = [match.group(1) for match in _MARKDOWN_IMAGE.finditer(markdown)]
    values.extend(match.group(0) for match in _RAW_IMAGE.finditer(markdown))
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= 50:
            break
    return result


def _html_to_text(value: str) -> str:
    text = _SCRIPT_STYLE.sub("\n", value)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", text, flags=re.IGNORECASE)
    text = _TAG.sub("", text)
    text = html_mod.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _unescape_markdown_json(value: str) -> str:
    marker = "\x00"
    candidate = value.replace('\\\\\\"', marker)
    candidate = _PUNCT_ESCAPE.sub("", candidate)
    return candidate.replace(marker, '\\"')


def normalize_fetched_page(title: str, content: str) -> tuple[str, str, list[str]]:
    """Handle both Markdown pages and JSON-wrapped official news responses."""
    value = content.strip()
    images = extract_image_urls(value)
    if value.startswith("{") or value.startswith("\\{"):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            payload = None
        if payload is None:
            try:
                payload = json.loads(_unescape_markdown_json(value))
            except json.JSONDecodeError:
                payload = None
        if isinstance(payload, dict):
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            raw = data.get("content") or data.get("body") or ""
            if isinstance(raw, str) and raw.strip():
                merged: list[str] = []
                for item in [*extract_image_urls(raw), *images]:
                    if item not in merged:
                        merged.append(item)
                page_title = str(data.get("title") or payload.get("title") or title)
                return page_title.strip(), _html_to_text(raw), merged[:50]
    return title, value, images[:50]
