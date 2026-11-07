"""提示词 Agent 的聊天式接口：查角色/服装/tag，拼装提示词。

设计原则：
- 工具查询走本地数据（数据库 + tag 库 + wiki），毫秒级、可解释；
- LLM 只负责把结果组织成自然语言，不负责猜数据；
- 用户说「换成 X」时只改对应部分，角色身份保持不变。
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import config

TAG_DB = Path(r"D:\AI\danbooru-tags\danbooru_tags.db")
WIKI = Path(r"D:\AI\danbooru-meta\danbooru_wiki_2026-04-28.jsonl")

COLOR_WORDS = ("发色", "瞳色", "头发", "眼睛", "眼瞳")


def _studio_conn() -> sqlite3.Connection:
    con = sqlite3.connect(f"{config.DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _tag_conn() -> sqlite3.Connection | None:
    if not TAG_DB.exists():
        return None
    con = sqlite3.connect(f"{TAG_DB.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _parse_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
        return [str(item).strip() for item in value if str(item).strip()]
    except json.JSONDecodeError:
        return []


def query_character(name: str) -> dict[str, Any] | None:
    """按中文名、preset_id 或 identity tag 查找角色，返回外貌与服装。"""
    keyword = (name or "").strip()
    if not keyword:
        return None
    con = _studio_conn()
    row = con.execute(
        "select preset_id, name, work, identity_tags, appearance_tags, outfit_id,"
        " clothing_tags from character_appearance_presets"
        " where enabled = 1 and (name = ? or preset_id = ?)",
        (keyword, keyword),
    ).fetchone()
    if not row:
        row = con.execute(
            "select preset_id, name, work, identity_tags, appearance_tags, outfit_id,"
            " clothing_tags from character_appearance_presets"
            " where enabled = 1 and (name like ? or preset_id like ? or identity_tags like ?)"
            " order by length(name) limit 1",
            (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"),
        ).fetchone()
    con.close()
    if not row:
        return None

    identity = _parse_list(row["identity_tags"])
    appearance = _parse_list(row["appearance_tags"])
    outfit = None
    outfit_id = str(row["outfit_id"] or "")
    if outfit_id:
        outfit = query_outfit(outfit_id)
    return {
        "preset_id": row["preset_id"],
        "name": row["name"],
        "work": row["work"],
        "identity": identity,
        "appearance": appearance,
        "outfit": outfit,
    }


def query_outfit(keyword: str) -> dict[str, Any] | None:
    """按预设 id 或名称查找服装，返回 tag 列表。"""
    keyword = (keyword or "").strip()
    if not keyword:
        return None
    try:
        import clothing_presets
    except Exception:
        return None

    target = keyword.lower()
    for item in clothing_presets.CLOTHING_PRESETS:
        pid = str(item.get("id") or "")
        label = str(item.get("label") or "")
        if pid == keyword or label == keyword:
            return {
                "id": pid,
                "name": label,
                "part": item.get("part"),
                "tags": list(item.get("tags") or []),
            }
    for item in clothing_presets.CLOTHING_PRESETS:
        pid = str(item.get("id") or "").lower()
        label = str(item.get("label") or "").lower()
        if target in pid or (label and target in label):
            return {
                "id": str(item.get("id") or ""),
                "name": str(item.get("label") or ""),
                "part": item.get("part"),
                "tags": list(item.get("tags") or []),
            }
    return None


def lookup_tag(tag: str) -> dict[str, Any] | None:
    """查单个 tag 是否存在，返回分类与帖子数。"""
    con = _tag_conn()
    if con is None:
        return None
    row = con.execute(
        "select tag, danbooru_category, post_count, aliases from tags where tag = ?",
        (tag,),
    ).fetchone()
    if not row:
        alias = con.execute(
            "select t.tag, t.danbooru_category, t.post_count, t.aliases"
            " from aliases a join tags t on t.tag = a.tag where a.alias = ?",
            (tag,),
        ).fetchone()
        row = alias
    con.close()
    if not row:
        return None
    return {
        "tag": row["tag"],
        "category": row["danbooru_category"],
        "post_count": row["post_count"],
    }


def search_tags(keyword: str, limit: int = 10) -> list[dict[str, Any]]:
    """模糊搜索 tag，按帖子数排序。"""
    con = _tag_conn()
    if con is None or not keyword.strip():
        return []
    rows = con.execute(
        "select tag, danbooru_category, post_count from tags"
        " where tag like ? order by post_count desc limit ?",
        (f"%{keyword.strip()}%", limit),
    ).fetchall()
    con.close()
    return [
        {"tag": r["tag"], "category": r["danbooru_category"], "post_count": r["post_count"]}
        for r in rows
    ]


def get_wiki(name: str) -> dict[str, Any] | None:
    """查角色 wiki（别名 + 正文摘要）。"""
    keyword = (name or "").strip().lower()
    if not keyword or not WIKI.exists():
        return None
    with WIKI.open("r", encoding="utf-8") as fh:
        for line in fh:
            if keyword not in line.lower():
                continue
            obj = json.loads(line)
            title = str(obj.get("title") or "")
            if keyword not in title.lower():
                continue
            body = str(obj.get("body") or "")
            return {
                "title": title,
                "category": obj.get("category_name"),
                "post_count": obj.get("post_count"),
                "other_names": list(obj.get("other_names") or [])[:10],
                "summary": body[:500],
            }
    return None


def list_characters_by_work(work: str, limit: int = 20) -> list[dict[str, str]]:
    con = _studio_conn()
    rows = con.execute(
        "select preset_id, name from character_appearance_presets"
        " where enabled = 1 and category = '角色' and work like ?"
        " order by name limit ?",
        (f"%{work}%", limit),
    ).fetchall()
    con.close()
    return [{"preset_id": r["preset_id"], "name": r["name"]} for r in rows]


CHANGE_PATTERN = re.compile(r"(换成|改成|变成|换成个|换个|改为)")


def is_change_request(text: str) -> bool:
    return bool(CHANGE_PATTERN.search(text or ""))


def build_prompt(
    character: dict[str, Any] | None,
    outfit: dict[str, Any] | None,
    extra_tags: list[str] | None = None,
) -> str:
    """按「身份 → 外貌 → 服装 → 其他」拼装提示词。"""
    parts: list[str] = ["1girl", "solo"]
    if character:
        parts.extend(character["identity"])
        parts.extend(character["appearance"])
        if outfit and outfit.get("tags"):
            parts.extend(outfit["tags"])
    if extra_tags:
        parts.extend(extra_tags)
    deduped: list[str] = []
    for item in parts:
        text = str(item).strip()
        if text and text not in deduped:
            deduped.append(text)
    return ", ".join(deduped)
