"""我的世界知识助手：查询接口。

数据来源：D:\\AI\\mc-data\\mc_assistant.sqlite（Wiki + 合成表 + 图标索引）
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

import mc_chat
from fastapi.responses import FileResponse

router = APIRouter()

DATA_DIR = Path(r"D:\AI\mc-data")
DB_PATH = DATA_DIR / "mc_assistant.sqlite"
ICON_DIR = DATA_DIR / "icons"

# 版本列表（按新旧排序）
VERSIONS = ["1.7.10", "1.11", "1.13", "1.16", "1.20", "1.21"]


def _conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail=f"MC 数据库不存在: {DB_PATH}")
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


_STRIP_PATTERNS = [
    (re.compile(r"\{\{[^{}]*\}\}"), ""),
    (re.compile(r"\[\[(?:File|文件|Image|图像)[^\]]*\]\]", re.IGNORECASE), ""),
    (re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]"), r"\2"),
    (re.compile(r"\[\[([^\]]+)\]\]"), r"\1"),
    (re.compile(r"''+"), ""),
    (re.compile(r"<ref[^>]*>.*?</ref>", re.DOTALL), ""),
    (re.compile(r"<[^>]+>"), ""),
    (re.compile(r"\n{2,}"), "\n"),
]


def _strip_wiki(text: str, limit: int = 400) -> str:
    t = text or ""
    for pattern, repl in _STRIP_PATTERNS:
        t = pattern.sub(repl, t)
    return t.strip()[:limit]


@router.get("/api/mc/versions")
def list_versions() -> dict:
    """返回支持的版本列表与库统计。"""
    con = _conn()
    rows = con.execute(
        "select version, count(*) as n from entity_version group by version"
    ).fetchall()
    counts = {r["version"]: r["n"] for r in rows}
    entity_total = con.execute("select count(*) from entity").fetchone()[0]
    recipe_total = con.execute("select count(*) from recipe").fetchone()[0]
    page_total = con.execute("select count(*) from page").fetchone()[0]
    con.close()
    return {
        "versions": VERSIONS,
        "entity_counts": counts,
        "stats": {
            "entities": entity_total,
            "recipes": recipe_total,
            "pages": page_total,
        },
    }


@router.get("/api/mc/search")
def search(
    q: str = Query(..., min_length=1, description="搜索词"),
    limit: int = Query(5, ge=1, le=20),
) -> dict:
    """全文检索 Wiki 页面。"""
    con = _conn()
    try:
        rows = con.execute(
            "select p.title, p.content, bm25(page_fts) as score"
            " from page_fts join page p on p.id = page_fts.rowid"
            " where page_fts match ? order by score limit ?",
            (q, limit),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        con.close()
        raise HTTPException(status_code=400, detail=f"检索语法错误: {exc}") from exc
    con.close()
    return {
        "query": q,
        "results": [
            {
                "title": r["title"],
                "snippet": _strip_wiki(r["content"], 300),
                "score": round(r["score"], 2),
            }
            for r in rows
        ],
    }


@router.get("/api/mc/page/{title}")
def get_page(title: str) -> dict:
    """读取 Wiki 页面全文（自动跟随重定向）。"""
    con = _conn()
    row = con.execute("select title, content from page where title = ?", (title,)).fetchone()
    if not row:
        r2 = con.execute("select target from redirect where title = ?", (title,)).fetchone()
        if r2:
            row = con.execute(
                "select title, content from page where title = ?", (r2["target"],)
            ).fetchone()
    con.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"页面不存在: {title}")
    return {
        "title": row["title"],
        "text": _strip_wiki(row["content"], 4000),
        "raw_length": len(row["content"]),
    }


@router.get("/api/mc/entity/{entity_id}")
def get_entity(entity_id: str) -> dict:
    """查询实体（物品/方块）详情，含图标、各版本存在性、合成表。"""
    con = _conn()
    row = con.execute(
        "select * from entity where id = ? or name_zh = ? or name_en = ?",
        (entity_id, entity_id, entity_id),
    ).fetchone()
    if not row:
        # 模糊匹配
        row = con.execute(
            "select * from entity where id like ? or name_zh like ?"
            " order by length(id) limit 1",
            (f"%{entity_id}%", f"%{entity_id}%"),
        ).fetchone()
    if not row:
        con.close()
        raise HTTPException(status_code=404, detail=f"实体不存在: {entity_id}")

    eid = row["id"]
    versions = [
        r["version"]
        for r in con.execute(
            "select version from entity_version where entity_id = ? order by version", (eid,)
        )
    ]
    con.close()

    return {
        "id": eid,
        "name_zh": row["name_zh"],
        "name_en": row["name_en"],
        "type": row["type"],
        "icon_url": f"/api/mc/icon/{row['icon_file']}" if row["icon_file"] else None,
        "wiki_page": row["wiki_page"],
        "first_version": row["first_version"],
        "last_version": row["last_version"],
        "versions": versions,
    }


@router.get("/api/mc/recipe")
def get_recipe(
    output: str = Query(..., description="产物 ID、中文名或英文名"),
    version: str | None = Query(None, description="限定版本，留空返回所有版本"),
) -> dict:
    """查询合成表。"""
    con = _conn()
    # 先解析成实体 id
    row = con.execute(
        "select id, name_zh from entity where id = ? or name_zh = ? or name_en = ?",
        (output, output, output),
    ).fetchone()
    if not row:
        row = con.execute(
            "select id, name_zh from entity where id like ? or name_zh like ?"
            " order by length(id) limit 1",
            (f"%{output}%", f"%{output}%"),
        ).fetchone()
    if not row:
        con.close()
        raise HTTPException(status_code=404, detail=f"找不到实体: {output}")

    eid = row["id"]
    sql = "select version, recipe_type, shape_json, ingredients_json, result_count from recipe where entity_id = ?"
    params: list = [eid]
    if version:
        sql += " and version = ?"
        params.append(version)
    recs = con.execute(sql + " order by version", params).fetchall()

    # 图标映射（给材料用）
    icons: dict[str, str] = {}
    all_mats = set()
    for r in recs:
        if r["shape_json"]:
            for rowm in json.loads(r["shape_json"]):
                for m in rowm:
                    if m:
                        all_mats.add(m)
        if r["ingredients_json"]:
            for m in json.loads(r["ingredients_json"]):
                if m:
                    all_mats.add(m)
    if all_mats:
        placeholders = ",".join("?" * len(all_mats))
        for r in con.execute(
            f"select id, name_zh, icon_file from entity where id in ({placeholders})",
            tuple(all_mats),
        ):
            if r["icon_file"]:
                icons[r["id"]] = f"/api/mc/icon/{r['icon_file']}"
    con.close()

    return {
        "output_id": eid,
        "output_name": row["name_zh"],
        "recipes": [
            {
                "version": r["version"],
                "type": r["recipe_type"],
                "shape": json.loads(r["shape_json"]) if r["shape_json"] else None,
                "ingredients": json.loads(r["ingredients_json"]) if r["ingredients_json"] else None,
                "result_count": r["result_count"],
            }
            for r in recs
        ],
        "material_icons": icons,
    }


@router.get("/api/mc/version-diff")
def version_diff(
    from_version: str = Query(..., alias="from"),
    to_version: str = Query(..., alias="to"),
    limit: int = Query(100, ge=1, le=1000),
) -> dict:
    """对比两个版本的新增内容。"""
    if from_version not in VERSIONS or to_version not in VERSIONS:
        raise HTTPException(status_code=400, detail="版本不在支持列表")
    con = _conn()
    old = {
        r["entity_id"]
        for r in con.execute(
            "select entity_id from entity_version where version = ?", (from_version,)
        )
    }
    new_rows = con.execute(
        "select ev.entity_id, e.name_zh, e.type, e.icon_file"
        " from entity_version ev join entity e on e.id = ev.entity_id"
        " where ev.version = ?",
        (to_version,),
    ).fetchall()
    con.close()

    added = []
    for r in new_rows:
        if r["entity_id"] in old:
            continue
        added.append(
            {
                "id": r["entity_id"],
                "name_zh": r["name_zh"],
                "type": r["type"],
                "icon_url": f"/api/mc/icon/{r['icon_file']}" if r["icon_file"] else None,
            }
        )
    added.sort(key=lambda x: x["name_zh"] or x["id"])
    return {
        "from": from_version,
        "to": to_version,
        "added_count": len(added),
        "added": added[:limit],
    }


@router.get("/api/mc/icon/{filename}")
def get_icon(filename: str):
    """返回物品/方块图标。"""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    path = ICON_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"图标不存在: {filename}")
    return FileResponse(path, media_type="image/png")


@router.get("/api/mc/stats")
def stats() -> dict:
    """数据概况。"""
    con = _conn()
    result = {}
    for table in ("entity", "entity_version", "recipe", "version_change", "page"):
        result[table] = con.execute(f"select count(*) from {table}").fetchone()[0]
    result["with_icon"] = con.execute(
        "select count(*) from entity where icon_file is not null"
    ).fetchone()[0]
    result["with_zh"] = con.execute(
        "select count(*) from entity where name_zh is not null"
    ).fetchone()[0]
    con.close()
    return result

# ── 对话问答 ──

from pydantic import BaseModel  # noqa: E402


class ChatRequest(BaseModel):
    query: str
    version: str | None = None


@router.post("/api/mc/chat")
def mc_chat_endpoint(request: ChatRequest) -> dict:
    """对话式问答：意图路由 + 数据组装 + LLM 润色。"""
    q = (request.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query 不能为空")
    return mc_chat.answer(q)
