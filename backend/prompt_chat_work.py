"""作品查询增强：名称归一化匹配 + 元数据查询。"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

import config

WORK_LIMIT = 12


def _normalize(text: str) -> str:
    """去掉标点空格，便于宽松匹配。"""
    return re.sub(r"[\s:：·\-—_/、,，.。()（）]", "", str(text or "")).lower()


def list_works() -> list[str]:
    con = sqlite3.connect(f"{config.DB_PATH.as_uri()}?mode=ro", uri=True)
    rows = con.execute(
        "select distinct work from character_appearance_presets"
        " where enabled = 1 and category = '角色' and work != ''"
    ).fetchall()
    con.close()
    return [row[0] for row in rows if row[0]]


ALIASES = {
    "五等分": "五等分的花嫁",
    "五等分的花嫁": "五等分的花嫁",
    "fgo": "Fate/Grand Order",
    "fate grand order": "Fate/Grand Order",
    "碧蓝航线": "碧蓝航线",
    "碧蓝": "碧蓝航线",
    "方舟": "明日方舟",
    "明日方舟": "明日方舟",
    "星铁": "崩坏：星穹铁道",
    "星穹铁道": "崩坏：星穹铁道",
    "崩坏星穹铁道": "崩坏：星穹铁道",
    "原神": "原神",
    "鸣潮": "鸣潮",
    "绝区零": "绝区零",
    "碧蓝档案": "碧蓝档案",
    "蔚蓝档案": "碧蓝档案",
    "妮姬": "胜利女神：妮姬",
    "胜利女神": "胜利女神：妮姬",
    "胜利女神妮姬": "胜利女神：妮姬",
    "nikke": "胜利女神：妮姬",
    "少女前线": "少女前线",
    "少前": "少女前线",
    "刀剑神域": "刀剑神域",
    "sao": "刀剑神域",
}


def detect_work(text: str) -> str | None:
    """从自然语言识别作品名：先精确、再归一化、最后走别名。"""
    if not text:
        return None
    works = list_works()

    # 1) 原文包含
    for work in sorted(works, key=len, reverse=True):
        if work and work in text:
            return work

    # 2) 归一化后包含
    norm_text = _normalize(text)
    for work in sorted(works, key=len, reverse=True):
        if work and _normalize(work) in norm_text:
            return work

    # 3) 别名表
    for alias, work in ALIASES.items():
        if _normalize(alias) in norm_text:
            if work in works:
                return work
    return None


def query_work_characters(work: str, limit: int = WORK_LIMIT) -> dict[str, Any]:
    con = sqlite3.connect(f"{config.DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select name, identity_tags, appearance_tags from character_appearance_presets"
        " where enabled = 1 and category = '角色' and work = ?"
        " order by name limit ?",
        (work, limit),
    ).fetchall()
    total = con.execute(
        "select count(*) from character_appearance_presets"
        " where enabled = 1 and category = '角色' and work = ?",
        (work,),
    ).fetchone()[0]
    con.close()

    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            appearance = json.loads(row["appearance_tags"] or "[]")
        except json.JSONDecodeError:
            appearance = []
        items.append({"name": row["name"], "appearance": appearance})
    return {"items": items, "total": total}


def query_work_meta(work: str) -> dict[str, Any] | None:
    """查作品元数据（类型、简介、推荐场景）。"""
    con = sqlite3.connect(f"{config.DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "select * from work_meta where work = ?",
        (work,),
    ).fetchone()
    con.close()
    if not row:
        return None
    try:
        genres = json.loads(row["genres"] or "[]")
    except json.JSONDecodeError:
        genres = []
    try:
        scenes = json.loads(row["scene_hints"] or "[]")
    except json.JSONDecodeError:
        scenes = []
    return {
        "work": row["work"],
        "year": row["year"],
        "medium": row["medium"],
        "genres": genres,
        "summary": row["summary"],
        "scene_hints": scenes,
    }


def build_work_reply(work: str, data: dict[str, Any]) -> str:
    items = data["items"]
    total = data["total"]
    if not items:
        return f"「{work}」下暂时没有收录角色。"
    lines = [
        f"「{work}」共收录 {total} 位角色"
        + (f"，先看前 {len(items)} 位：" if total > len(items) else "：")
    ]
    for item in items:
        tags = [tag for tag in item["appearance"] if tag not in {"1girl", "solo"}][:8]
        lines.append(f"{item['name']}：{'、'.join(tags) if tags else '（暂无外貌 tag）'}")
    if total > len(items):
        lines.append("需要更多可以指定角色名，我单独查。")
    return "\n".join(lines)


def build_work_meta_reply(meta: dict[str, Any], total: int) -> str:
    genres = "、".join(meta["genres"]) or "未标注"
    scenes = "、".join(meta["scene_hints"]) or "未标注"
    lines = [
        f"「{meta['work']}」",
        f"{meta['year'] or '?'} 年 · {meta['medium'] or '?'} · {genres}",
        meta["summary"] or "",
        f"已收录 {total} 位角色，推荐场景：{scenes}",
    ]
    return "\n".join(line for line in lines if line)


def find_similar(work: str, limit: int = 5) -> list[dict[str, Any]]:
    """按类型重叠度找相似作品。"""
    con = sqlite3.connect(f"{config.DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("select * from work_meta").fetchall()
    con.close()

    def parse(raw: str) -> set[str]:
        try:
            return set(json.loads(raw or "[]"))
        except json.JSONDecodeError:
            return set()

    target = next((r for r in rows if r["work"] == work), None)
    if not target:
        return []
    base = parse(target["genres"])
    if not base:
        return []

    scored = []
    for row in rows:
        if row["work"] == work:
            continue
        genres = parse(row["genres"])
        overlap = base & genres
        if not overlap:
            continue
        score = len(overlap) / len(base | genres)
        scored.append(
            {
                "work": row["work"],
                "genres": sorted(genres),
                "overlap": sorted(overlap),
                "score": round(score, 2),
                "summary": row["summary"],
            }
        )
    scored.sort(key=lambda x: (-x["score"], -len(x["overlap"])))
    return scored[:limit]
