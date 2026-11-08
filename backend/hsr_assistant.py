"""崩坏：星穹铁道知识助手：查询接口。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

import hsr_chat
import llm
from fastapi.responses import FileResponse, StreamingResponse

router = APIRouter()

DATA_DIR = Path(r"D:\AI\hsr-data")
DB_PATH = DATA_DIR / "hsr_assistant.sqlite"
ICON_DIR = DATA_DIR / "icons"


def _conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail=f"崩铁数据库不存在: {DB_PATH}")
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


@router.get("/api/hsr/stats")
def hsr_stats() -> dict:
    con = _conn()
    out = {}
    for table in ("character", "character_skill", "character_rank", "character_material"):
        out[table] = con.execute(f"select count(*) from {table}").fetchone()[0]
    out["icons"] = len(list(ICON_DIR.glob("*.png"))) if ICON_DIR.exists() else 0
    con.close()
    return out


@router.get("/api/hsr/search")
def hsr_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    con = _conn()
    rows = con.execute(
        "select id, name, path_zh, element_zh, rarity, atk_max, hp_max from character"
        " where name like ? or tag like ?"
        " order by rarity desc, name limit ?",
        (f"%{q}%", f"%{q}%", limit),
    ).fetchall()
    con.close()
    return {
        "query": q,
        "results": [
            {
                "id": r["id"],
                "name": r["name"],
                "path": r["path_zh"],
                "element": r["element_zh"],
                "rarity": r["rarity"],
                "atk_max": r["atk_max"],
                "hp_max": r["hp_max"],
                "icon": f"/api/hsr/icon/{r['id']}",
            }
            for r in rows
        ],
    }


@router.get("/api/hsr/character/{char_id}")
def hsr_character(char_id: str) -> dict:
    con = _conn()
    row = con.execute("select * from character where id = ? or name = ?", (char_id, char_id)).fetchone()
    if not row:
        # 按名字兜底
        row = con.execute(
            "select * from character where name like ? limit 1", (f"%{char_id}%",)
        ).fetchone()
    if not row:
        con.close()
        raise HTTPException(status_code=404, detail=f"角色不存在: {char_id}")

    cid = row["id"]
    skills = [
        {
            "name": r["name"],
            "type": r["type_text"],
            "effect": r["effect_text"],
            "simple_desc": r["simple_desc"],
            "desc": r["desc"],
        }
        for r in con.execute(
            "select * from character_skill where char_id = ? order by skill_id", (cid,)
        )
    ]
    ranks = [
        {"index": r["rank_index"], "name": r["name"], "desc": r["desc"]}
        for r in con.execute(
            "select * from character_rank where char_id = ? order by rank_index", (cid,)
        )
    ]
    materials = []
    for r in con.execute(
        "select promotion, material_name, amount from character_material"
        " where char_id = ? order by promotion, material_id",
        (cid,),
    ):
        materials.append(
            {"promotion": r["promotion"], "name": r["material_name"], "amount": r["amount"]}
        )
    con.close()

    return {
        "id": cid,
        "name": row["name"],
        "rarity": row["rarity"],
        "path": row["path_zh"],
        "element": row["element_zh"],
        "icon": f"/api/hsr/icon/{cid}",
        "stats": {
            "atk": row["atk_max"],
            "hp": row["hp_max"],
            "def": row["def_max"],
            "spd": row["spd_max"],
        },
        "skills": skills,
        "ranks": ranks,
        "materials": materials,
    }


@router.get("/api/hsr/icon/{char_id}")
def hsr_icon(char_id: str):
    if "/" in char_id or "\\" in char_id or ".." in char_id:
        raise HTTPException(status_code=400, detail="非法 ID")
    path = ICON_DIR / f"{char_id}.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"图标不存在: {char_id}")
    return FileResponse(path, media_type="image/png")


@router.get("/api/hsr/characters")
def hsr_characters(
    path: str | None = Query(None, description="命途英文名，如 Warrior"),
    element: str | None = Query(None, description="元素英文名，如 Ice"),
    rarity: int | None = Query(None, ge=1, le=5),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    con = _conn()
    sql = "select id, name, path_zh, element_zh, rarity from character where 1=1"
    params: list = []
    if path:
        sql += " and path = ?"
        params.append(path)
    if element:
        sql += " and element = ?"
        params.append(element)
    if rarity is not None:
        sql += " and rarity = ?"
        params.append(rarity)
    sql += " order by rarity desc, name limit ?"
    params.append(limit)
    rows = con.execute(sql, params).fetchall()
    con.close()
    return {
        "total": len(rows),
        "characters": [
            {
                "id": r["id"],
                "name": r["name"],
                "path": r["path_zh"],
                "element": r["element_zh"],
                "rarity": r["rarity"],
                "icon": f"/api/hsr/icon/{r['id']}",
            }
            for r in rows
        ],
    }

# ── 对话问答 ──

from pydantic import BaseModel  # noqa: E402


class HsrChatRequest(BaseModel):
    query: str


@router.post("/api/hsr/chat")
def hsr_chat_endpoint(request: HsrChatRequest) -> dict:
    q = (request.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query 不能为空")
    return hsr_chat.answer(q)


def _hsr_sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/api/hsr/chat/stream")
def hsr_chat_stream(request: HsrChatRequest):
    q = (request.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query 不能为空")

    def generate():
        try:
            data, context = hsr_chat.prepare(q)
        except Exception as exc:
            yield _hsr_sse({"type": "error", "message": str(exc)[:200]})
            return

        meta = {k: v for k, v in data.items() if not k.startswith("_") and k != "text"}
        yield _hsr_sse({"type": "meta", **meta})

        if data.get("intent") == "list" or not context or not llm.is_available():
            yield _hsr_sse({"type": "delta", "content": hsr_chat.fallback_text(context)})
            yield _hsr_sse({"type": "done"})
            return

        try:
            messages = hsr_chat.build_messages(q, context)
            for kind, chunk in llm.stream_chat(messages, temperature=0.3, max_tokens=400, timeout=180):
                if kind == "answer" and chunk:
                    yield _hsr_sse({"type": "delta", "content": chunk})
        except Exception as exc:
            yield _hsr_sse({"type": "error", "message": str(exc)[:200]})

        yield _hsr_sse({"type": "done"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
