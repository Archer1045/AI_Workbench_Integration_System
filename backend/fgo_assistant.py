"""FGO 知识助手：查询接口。

数据来源：D:\\AI\\fgo-data\\fgo_assistant.sqlite + faces（头像）
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

import fgo_chat
import llm
from fastapi.responses import FileResponse, StreamingResponse

router = APIRouter()

DATA_DIR = Path(r"D:\AI\fgo-data")
DB_PATH = DATA_DIR / "fgo_assistant.sqlite"
FACE_DIR = DATA_DIR / "faces"


def _conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail=f"FGO 数据库不存在: {DB_PATH}")
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


@router.get("/api/fgo/stats")
def fgo_stats() -> dict:
    con = _conn()
    out = {}
    for table in ("servant", "servant_skill", "servant_np"):
        out[table] = con.execute(f"select count(*) from {table}").fetchone()[0]
    out["faces"] = len(list(FACE_DIR.glob("*.png"))) if FACE_DIR.exists() else 0
    con.close()
    return out


@router.get("/api/fgo/search")
def fgo_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    """搜索从者（中文名/原名）。"""
    con = _conn()
    rows = con.execute(
        "select id, name, class_zh, rarity, atk_max, hp_max from servant"
        " where name like ? or original_name like ?"
        " order by rarity desc, collection_no limit ?",
        (f"%{q}%", f"%{q}%", limit),
    ).fetchall()
    con.close()
    return {
        "query": q,
        "results": [
            {
                "id": r["id"],
                "name": r["name"],
                "class_name": r["class_zh"],
                "rarity": r["rarity"],
                "atk_max": r["atk_max"],
                "hp_max": r["hp_max"],
                "face": f"/api/fgo/face/{r['id']}",
            }
            for r in rows
        ],
    }


@router.get("/api/fgo/servant/{servant_id}")
def fgo_servant(servant_id: int) -> dict:
    """从者详情：属性、技能、宝具。"""
    con = _conn()
    row = con.execute("select * from servant where id = ?", (servant_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(status_code=404, detail=f"从者不存在: {servant_id}")

    skills = [
        {
            "index": r["skill_index"],
            "name": r["name"],
            "detail": r["detail"],
            "cool_down": r["cool_down"],
        }
        for r in con.execute(
            "select * from servant_skill where servant_id = ? order by skill_index",
            (servant_id,),
        )
    ]
    nps = [
        {
            "index": r["np_index"],
            "name": r["name"],
            "rank": r["rank"],
            "card": r["card"],
            "detail": r["detail"],
        }
        for r in con.execute(
            "select * from servant_np where servant_id = ? order by np_index",
            (servant_id,),
        )
    ]
    con.close()

    return {
        "id": row["id"],
        "name": row["name"],
        "original_name": row["original_name"],
        "class_name": row["class_zh"],
        "rarity": row["rarity"],
        "cost": row["cost"],
        "lv_max": row["lv_max"],
        "atk_max": row["atk_max"],
        "hp_max": row["hp_max"],
        "gender": row["gender"],
        "attribute": row["attribute"],
        "face": f"/api/fgo/face/{row['id']}",
        "skills": skills,
        "noble_phantasms": nps,
    }


@router.get("/api/fgo/face/{servant_id}")
def fgo_face(servant_id: int):
    """返回从者头像。"""
    path = FACE_DIR / f"{servant_id}.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"头像不存在: {servant_id}")
    return FileResponse(path, media_type="image/png")


@router.get("/api/fgo/servants")
def fgo_servants(
    class_name: str | None = Query(None, description="职阶英文名，如 saber"),
    rarity: int | None = Query(None, ge=0, le=5),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """按职阶/星级列出从者。"""
    con = _conn()
    sql = "select id, name, class_name, class_zh, rarity from servant where 1=1"
    params: list = []
    if class_name:
        sql += " and class_name = ?"
        params.append(class_name)
    if rarity is not None:
        sql += " and rarity = ?"
        params.append(rarity)
    sql += " order by rarity desc, collection_no limit ?"
    params.append(limit)
    rows = con.execute(sql, params).fetchall()
    con.close()
    return {
        "total": len(rows),
        "servants": [
            {
                "id": r["id"],
                "name": r["name"],
                "class_name": r["class_zh"],
                "rarity": r["rarity"],
                "face": f"/api/fgo/face/{r['id']}",
            }
            for r in rows
        ],
    }

# ── 对话问答 ──

from pydantic import BaseModel  # noqa: E402


class FgoChatRequest(BaseModel):
    query: str


@router.post("/api/fgo/chat")
def fgo_chat_endpoint(request: FgoChatRequest) -> dict:
    q = (request.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query 不能为空")
    return fgo_chat.answer(q)


def _fgo_sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/api/fgo/chat/stream")
def fgo_chat_stream(request: FgoChatRequest):
    q = (request.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query 不能为空")

    def generate():
        try:
            data, context = fgo_chat.prepare(q)
        except Exception as exc:
            yield _fgo_sse({"type": "error", "message": str(exc)[:200]})
            return

        meta = {k: v for k, v in data.items() if not k.startswith("_") and k != "text"}
        yield _fgo_sse({"type": "meta", **meta})

        if not context or not llm.is_available():
            yield _fgo_sse({"type": "delta", "content": fgo_chat.fallback_text(context)})
            yield _fgo_sse({"type": "done"})
            return

        try:
            messages = fgo_chat.build_messages(q, context)
            for kind, chunk in llm.stream_chat(messages, temperature=0.3, max_tokens=400, timeout=180):
                if kind == "answer" and chunk:
                    yield _fgo_sse({"type": "delta", "content": chunk})
        except Exception as exc:
            yield _fgo_sse({"type": "error", "message": str(exc)[:200]})

        yield _fgo_sse({"type": "done"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
