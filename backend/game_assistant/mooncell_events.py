"""Mooncell 活动表（国服 + 日服）→ 本地缓存 → 日服同期参考。

为什么要它（2026-10-15 用户口径）：**日服比国服早约 12 个月**，所以"今天往前推一年"的日服档期
就是国服接下来会遇到什么的参考。实测：日服「Final Order Project [Ordeal Call Ⅳ]通关应援」
= 2025-10-20，国服 Ⅲ = 2026-10-13，同一条线每周一排 ⇒ 约整 12 个月。

**它只是参考**：不参与「下一个活动」的回答（那条线只认 `upcoming_events_cn.json` 里的
confirmed），也不会被写成国服日程——页面上必须明确标成「日服·参考」。

数据：Mooncell「活动一览」页里有两张表——`未来活动` 段 = 日服（日本标准时间），按年份的分段
= 国服。缓存落在 `KB/mooncell_events.json`：页面读本地、不每次抓网。
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import config

SHANGHAI = ZoneInfo("Asia/Shanghai")
WIKI_API = "https://fgo.wiki/api.php"
PAGE = "活动一览"
JP_SECTION = "未来活动"
USER_AGENT = "Mozilla/5.0 (compatible; ai-workbench game assistant)"
FETCH_TIMEOUT = 30.0
CACHE_VERSION = 1
REFERENCE_MONTHS_BACK = 12
REFERENCE_WINDOW_DAYS = 30

_H2 = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)
_TR = re.compile(r"<tr.*?</tr>", re.S)
_TAGS = re.compile(r"<[^>]+>")
_ROW = re.compile(
    r"^(\d{4})年(\d{1,2})月(\d{1,2})日[^\d]*?(\d{1,2}):(\d{2})\s+"
    # 「～？」是页面里的全角写法（没写结束时间），半角 ? 也一起认
    r"(?:(\d{4})年(\d{1,2})月(\d{1,2})日[^\d]*?(\d{1,2}):(\d{2})|[～~]\s*[?？])\s+"
    r"(.+?)\s+(Event|Campaign|Other)$"
)


def cache_path() -> Path:
    """缓存路径。**每次现读 config**，测试 monkeypatch KB 目录就能隔离。"""
    return Path(config.GAME_ASSISTANT_KB_DIR) / "mooncell_events.json"


def _plain(fragment: str) -> str:
    text = _TAGS.sub(" ", fragment)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def parse_page(html: str) -> list[dict[str, Any]]:
    """把「活动一览」的 HTML 拆成条目列表（`server` = `jp` / `cn`）。"""
    items: list[dict[str, Any]] = []
    for chunk in re.split(r"(?=<h2)", html):
        heading_match = _H2.match(chunk)
        if not heading_match:
            continue
        heading = _plain(heading_match.group(1)).replace("[ 编辑 ]", "").strip()
        if heading.startswith(JP_SECTION):
            server = "jp"
        elif re.match(r"^\d{4}年", heading):
            server = "cn"
        else:
            continue
        for row in _TR.findall(chunk):
            match = _ROW.match(_plain(row))
            if not match:
                continue
            starts_at = datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3)),
                int(match.group(4)), int(match.group(5)), tzinfo=SHANGHAI,
            )
            ends_at = None
            if match.group(6):
                ends_at = datetime(
                    int(match.group(6)), int(match.group(7)), int(match.group(8)),
                    int(match.group(9)), int(match.group(10)), tzinfo=SHANGHAI,
                )
            items.append(
                {
                    "server": server,
                    "title": match.group(11).strip(),
                    "starts_at": starts_at.isoformat(),
                    "ends_at": ends_at.isoformat() if ends_at else None,
                    "type": match.group(12),
                }
            )
    return items


def fetch_page_html(timeout: float = FETCH_TIMEOUT) -> str:
    query = urllib.parse.urlencode(
        {"action": "parse", "page": PAGE, "prop": "text", "format": "json", "formatversion": 2}
    )
    request = urllib.request.Request(f"{WIKI_API}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    return ((payload.get("parse") or {}).get("text")) or ""


def refresh_cache(
    *, now: datetime | None = None, html: str | None = None, fetcher=fetch_page_html,
) -> dict[str, Any]:
    """抓一次页面并落缓存；失败时保留旧缓存（只把错误信息返回，不抛异常）。"""
    moment = now or datetime.now(SHANGHAI)
    try:
        page = html if html is not None else fetcher()
        items = parse_page(page)
    except Exception as exc:   # 抓不到就用旧缓存：页面不该因此打不开
        return {"ok": False, "error": f"抓 Mooncell 活动表失败：{exc}", "items": 0}
    if not items:
        return {"ok": False, "error": "Mooncell 活动表解析出 0 条：页面结构可能变了", "items": 0}
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": CACHE_VERSION,
                "fetched_at": moment.isoformat(timespec="seconds"),
                "items": items,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "items": len(items),
        "jp": sum(1 for item in items if item["server"] == "jp"),
        "cn": sum(1 for item in items if item["server"] == "cn"),
        "fetched_at": moment.isoformat(timespec="seconds"),
    }


def load_cache() -> dict[str, Any]:
    """读缓存；文件不存在 / 坏了都当空（不编数据）。"""
    try:
        payload = json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"items": [], "fetched_at": None}
    if not isinstance(payload, dict):
        return {"items": [], "fetched_at": None}
    return {"items": payload.get("items") or [], "fetched_at": payload.get("fetched_at")}


def japanese_reference(
    now: datetime | None = None,
    *,
    months_back: int = REFERENCE_MONTHS_BACK,
    window_days: int = REFERENCE_WINDOW_DAYS,
    limit: int = 8,
) -> dict[str, Any]:
    """日服「同期」参考：今天往前推 `months_back` 个月、前后放宽 `window_days` 天的日服条目。"""
    moment = now or datetime.now(SHANGHAI)
    anchor = moment - timedelta(days=int(months_back * 30.44))
    start = anchor - timedelta(days=window_days)
    end = anchor + timedelta(days=window_days)
    cache = load_cache()
    picked: list[dict[str, Any]] = []
    for item in cache["items"]:
        if item.get("server") != "jp":
            continue
        try:
            begins = datetime.fromisoformat(str(item.get("starts_at")))
        except (TypeError, ValueError):
            continue
        if start <= begins <= end:
            picked.append(item)
    picked.sort(key=lambda item: str(item.get("starts_at")))
    return {
        "fetched_at": cache["fetched_at"],
        "anchor": anchor.date().isoformat(),
        "window_start": start.date().isoformat(),
        "window_end": end.date().isoformat(),
        "items": picked[:limit],
        "note": (
            f"日服·参考（锚点 {anchor.date().isoformat()} 前后 {window_days} 天）：日服比国服早约 12 个月，"
            "这里只是「接下来会遇到什么」的参考，不代表国服排期。"
        ),
    }
