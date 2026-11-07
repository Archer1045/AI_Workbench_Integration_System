"""Mooncell「道具一览」→ 素材掉落 top3 关卡库。

数据源（用户 2026-10-11 指定）：`https://fgo.wiki/w/道具一览`，该页为每个素材列出
掉落率最高的 top3 关卡（章节 + 关卡名 + 消耗 AP + 掉落率）。页面本身是 SMW + 模板渲染，
因此这里解析的是 `action=parse&prop=text` 的**渲染后 HTML**，不是 wikitext。

用法：
    python -m game_assistant.mooncell_drops                     # 抓取并写入 KB 目录
    python -m game_assistant.mooncell_drops --html-file x.html  # 离线重解析
    python -m game_assistant.mooncell_drops --out some/dir

为什么值得单独一个库：这是「我缺素材 X，该刷哪个本」的直接答案，
也是 Atlas 侧完全缺失的一块（Atlas 的 15,284 个关卡 dropInfos 全为空）。

注意：该页的「掉落率」是 wiki 的口径，**可以超过 100%**（实测「世界树之种」的首选关卡是
`27.91 AP / 143.3%`，即一次战斗可能掉多个）。所以不要把 >100% 当成解析错误。
"""
from __future__ import annotations

import argparse
import html as html_module
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

import config

LIBRARY = "material_drops"
OUTPUT_FILENAME = "material_drops_cn.json"
API = "https://fgo.wiki/api.php"
PAGE = "道具一览"

_ROW_RE = re.compile(r"<tr>.*?</tr>", re.S)
_RATE_RE = re.compile(r"\(\s*([0-9.]+)\s*AP\s*/\s*([0-9.]+)%\s*\)")
_LINK_RE = re.compile(r'<a\s+href="[^"]*#([^"]*)"\s+title="([^"]*?)">([^<]*)</a>')
_NAME_RE = re.compile(r'<td><a href="[^"]*" title="([^"]*)">([^<]*)<br')
_CATEGORY_RE = re.compile(r'class="道具一览&#95;([^&#]+)&#95;\d"')
_DESC_RE = re.compile(r'class="道具一览&#95;[^&#]+&#95;1"[^>]*>([^<]*)<')
_STRIP_RE = re.compile(r"<[^>]+>")

# Atlas 素材库与 Mooncell 对同一素材的写法不一致（实测：Atlas「祸骨」/ Mooncell「凶骨」）。
# 查询入口统一在这里归一，避免调用方各自记一套名字。
NAME_ALIASES = {"祸骨": "凶骨"}


def drops_for_material(
    payload: dict[str, Any], material: str, limit: int = 3
) -> list[dict[str, Any]]:
    """查询某素材的掉落 top 关卡（按名字归一，返回 [{rank, chapter, quests, ap, rate}, ...]）。"""
    wanted = NAME_ALIASES.get(str(material or "").strip(), str(material or "").strip())
    if not wanted:
        return []
    for item in payload.get("items") or []:
        if item.get("material") == wanted:
            return list(item.get("entries") or [])[:limit]
    return []


def fetch_page(page: str = PAGE, api: str = API, timeout: int = 90) -> str:
    """抓取渲染后的 HTML（该页是 SMW/模板渲染，wikitext 里没有掉落数据）。"""
    response = requests.get(
        api,
        params={
            "action": "parse",
            "page": page,
            "prop": "text",
            "format": "json",
            "formatversion": "2",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    html = (payload.get("parse") or {}).get("text") or ""
    if not html:
        raise ValueError(f"页面 {page} 没有返回渲染内容")
    return html


def parse_row(row_html: str) -> dict[str, Any] | None:
    """解析单个素材行，返回 {material, category, desc, entries[top3]}；没有掉落数据时返回 None。"""
    name_match = _NAME_RE.search(row_html)
    if not name_match:
        return None
    material = html_module.unescape(name_match.group(2)).strip()
    if not material:
        return None
    if not _RATE_RE.search(row_html):
        return None  # 活动道具等没有掉落率

    category_match = _CATEGORY_RE.search(row_html)
    desc_match = _DESC_RE.search(row_html)
    body = row_html.split('<td class="nomobile">', 1)[-1]

    entries: list[dict[str, Any]] = []
    position = 0
    while True:
        rate_match = _RATE_RE.search(body, position)
        if not rate_match:
            break
        segment = body[position : rate_match.start()]
        chapter = ""
        quests: list[str] = []
        for anchor, _title, text in _LINK_RE.findall(segment):
            anchor = html_module.unescape(anchor).strip()
            text = html_module.unescape(text).strip()
            if not chapter:
                chapter = text
                continue
            if anchor and anchor != "自由关卡":
                quests.append(anchor)
        entries.append(
            {
                "rank": len(entries) + 1,
                "chapter": chapter,
                "quests": quests,
                "ap": float(rate_match.group(1)),
                "rate": float(rate_match.group(2)),
            }
        )
        position = rate_match.end()

    if not entries:
        return None
    return {
        "material": material,
        "category": category_match.group(1) if category_match else "",
        "desc": html_module.unescape(_STRIP_RE.sub("", desc_match.group(1))).strip()
        if desc_match
        else "",
        "entries": entries[:3],
    }


def build_library(html: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row_html in _ROW_RE.findall(html):
        parsed = parse_row(row_html)
        if not parsed or parsed["material"] in seen:
            continue
        seen.add(parsed["material"])
        rows.append(parsed)
    rows.sort(key=lambda item: (item["category"], item["material"]))
    return {
        "library": LIBRARY,
        "source": {
            "name": "Mooncell 道具一览（渲染页）",
            "url": f"https://fgo.wiki/w/{PAGE}",
            "entries": len(rows),
            "kept": len(rows),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "note": "每素材 top3 掉落关卡（章节/关卡/消耗AP/掉落率）；数据来自 wiki 渲染页，随游戏版本变化",
        },
        "items": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 Mooncell 素材掉落 top3 关卡库")
    parser.add_argument("--html-file", default="", help="离线重解析：直接读本地 HTML")
    parser.add_argument("--page", default=PAGE)
    parser.add_argument("--out-dir", default="", help="默认写入 config.GAME_ASSISTANT_KB_DIR")
    args = parser.parse_args(argv)

    if args.html_file:
        html = Path(args.html_file).read_text(encoding="utf-8")
    else:
        html = fetch_page(args.page)
    payload = build_library(html)
    target = Path(args.out_dir or config.GAME_ASSISTANT_KB_DIR) / OUTPUT_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {target}：{len(payload['items'])} 个素材的掉落 top3", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
