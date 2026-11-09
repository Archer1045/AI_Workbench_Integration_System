"""碧蓝航线助手：查询接口。

数据来源：
- D:\\AI\\azur-data\\azur_assistant.sqlite（舰船/技能/装备/皮肤）
- D:\\AI\\azur-data\\icons（船坞图标，文件名 = painting 字段）
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

import azur_chat
import llm
from fastapi.responses import FileResponse, StreamingResponse

router = APIRouter()

DATA_DIR = Path(r"D:\AI\azur-data")
DB_PATH = DATA_DIR / "azur_assistant.sqlite"
ICON_DIR = DATA_DIR / "icons"

# attrs 数组索引 -> 中文属性名（通过企业/拉菲/胡德反推）
ATTR_NAMES = {
    0: "耐久",
    1: "炮击",
    2: "雷击",
    3: "防空",
    4: "航空",
    5: "装填",
    7: "命中",
    8: "机动",
    9: "航速",
    10: "幸运",
    11: "反潜",
}

# 满级等级（碧蓝航线满级 125，成长值按 124 级增量算）
MAX_LEVEL_OFFSET = 124
# 成长值缩放（实测：企业 2566 + 27540×124/1000 = 5981，与实际相符）
GROWTH_SCALE = 1000

# 舰种
SHIP_TYPES = [
    "驱逐", "轻巡", "重巡", "战巡", "战列", "轻航", "航母",
    "潜艇", "重炮", "维修", "潜航", "导驱", "导巡", "超巡",
]


def _conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail=f"碧蓝航线数据库不存在: {DB_PATH}")
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _parse_attrs(attrs_json: str, growth_json: str) -> tuple[dict, dict]:
    """把 attrs 数组转成带名字的字典，并算满级值。"""
    try:
        attrs = json.loads(attrs_json or "[]")
    except Exception:
        attrs = []
    try:
        growth = json.loads(growth_json or "[]")
    except Exception:
        growth = []

    base: dict[str, float] = {}
    maxed: dict[str, float] = {}
    for idx, name in ATTR_NAMES.items():
        if idx >= len(attrs):
            continue
        base_v = attrs[idx] or 0
        grow_v = growth[idx] if idx < len(growth) else 0
        base[name] = base_v
        # 满级值 = base + growth × 124 / 1000（实测公式）
        maxed[name] = round(base_v + (grow_v or 0) * MAX_LEVEL_OFFSET / GROWTH_SCALE, 1)
    return base, maxed


@router.get("/api/azur/stats")
def azur_stats() -> dict:
    con = _conn()
    out = {}
    for table in ("ship", "ship_skill", "equip", "ship_skin"):
        out[table] = con.execute(f"select count(*) from {table}").fetchone()[0]
    out["icons"] = len(list(ICON_DIR.glob("*.png"))) if ICON_DIR.exists() else 0
    con.close()
    return out


@router.get("/api/azur/search")
def azur_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    con = _conn()
    rows = con.execute(
        "select id, name, english_name, type_zh, nationality, star, rarity, painting"
        " from ship where name like ? or english_name like ?"
        " order by star desc, name limit ?",
        (f"%{q}%", f"%{q}%", limit),
    ).fetchall()
    con.close()
    return {
        "query": q,
        "results": [
            {
                "id": r["id"],
                "name": r["name"],
                "english_name": r["english_name"],
                "type": r["type_zh"],
                "star": r["star"],
                "rarity": r["rarity"],
                "icon": f"/api/azur/icon/{r['painting']}" if r["painting"] else None,
            }
            for r in rows
        ],
    }


@router.get("/api/azur/ship/{name}")
def azur_ship(name: str) -> dict:
    con = _conn()
    row = con.execute(
        "select * from ship where name = ? or english_name = ? or id = ? limit 1",
        (name, name, name),
    ).fetchone()
    if not row:
        # 模糊兜底
        row = con.execute(
            "select * from ship where name like ? order by star desc limit 1",
            (f"%{name}%",),
        ).fetchone()
    if not row:
        con.close()
        raise HTTPException(status_code=404, detail=f"舰船不存在: {name}")

    base_attrs, max_attrs = _parse_attrs(row["attrs"], row["attrs_growth"])

    # 该舰船组的全部皮肤
    group = row["id"][:5] if len(row["id"]) >= 5 else row["id"]
    skins = [
        {
            "id": s["id"],
            "name": s["name"],
            "painting": s["painting"],
            "icon": f"/api/azur/icon/{s['painting']}" if s["painting"] else None,
        }
        for s in con.execute(
            "select id, name, painting from ship_skin where ship_group = ?",
            (group,),
        )
    ]
    con.close()

    return {
        "id": row["id"],
        "name": row["name"],
        "english_name": row["english_name"],
        "type": row["type_zh"],
        "star": row["star"],
        "rarity": row["rarity"],
        "nationality": row["nationality"],
        "icon": f"/api/azur/icon/{row['painting']}" if row["painting"] else None,
        "painting": row["painting"],
        "attrs": base_attrs,
        "attrs_max": max_attrs,
        "skins": skins,
    }


@router.get("/api/azur/icon/{painting}")
def azur_icon(painting: str):
    if "/" in painting or "\\" in painting or ".." in painting:
        raise HTTPException(status_code=400, detail="非法文件名")
    path = ICON_DIR / f"{painting}.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"图标不存在: {painting}")
    return FileResponse(path, media_type="image/png")


@router.get("/api/azur/ships")
def azur_ships(
    ship_type: str | None = Query(None, description="舰种中文，如 航母"),
    star: int | None = Query(None, ge=1, le=6),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    con = _conn()
    sql = "select id, name, type_zh, star, rarity, painting from ship where 1=1"
    params: list = []
    if ship_type:
        sql += " and type_zh = ?"
        params.append(ship_type)
    if star is not None:
        sql += " and star = ?"
        params.append(star)
    sql += " order by star desc, name limit ?"
    params.append(limit)
    rows = con.execute(sql, params).fetchall()
    con.close()
    return {
        "total": len(rows),
        "ships": [
            {
                "id": r["id"],
                "name": r["name"],
                "type": r["type_zh"],
                "star": r["star"],
                "rarity": r["rarity"],
                "icon": f"/api/azur/icon/{r['painting']}" if r["painting"] else None,
            }
            for r in rows
        ],
    }


@router.get("/api/azur/equips")
def azur_equips(
    q: str = Query("", description="装备名关键词"),
    limit: int = Query(30, ge=1, le=200),
) -> dict:
    con = _conn()
    if q:
        rows = con.execute(
            "select id, name, type, rarity, descrip from equip where name like ?"
            " order by rarity desc, name limit ?",
            (f"%{q}%", limit),
        ).fetchall()
    else:
        rows = con.execute(
            "select id, name, type, rarity, descrip from equip"
            " order by rarity desc, name limit ?",
            (limit,),
        ).fetchall()
    con.close()
    return {
        "total": len(rows),
        "equips": [
            {
                "id": r["id"],
                "name": r["name"],
                "type": r["type"],
                "rarity": r["rarity"],
                "descrip": r["descrip"],
            }
            for r in rows
        ],
    }


@router.get("/api/azur/skills")
def azur_skills(
    q: str = Query("", description="技能名关键词"),
    limit: int = Query(30, ge=1, le=200),
) -> dict:
    con = _conn()
    if q:
        rows = con.execute(
            "select skill_id, skill_name, skill_desc, cooldown from ship_skill"
            " where skill_name like ? or skill_desc like ?"
            " order by cooldown limit ?",
            (f"%{q}%", f"%{q}%", limit),
        ).fetchall()
    else:
        rows = con.execute(
            "select skill_id, skill_name, skill_desc, cooldown from ship_skill"
            " order by cooldown limit ?",
            (limit,),
        ).fetchall()
    con.close()
    return {
        "total": len(rows),
        "skills": [
            {
                "id": r["skill_id"],
                "name": r["skill_name"],
                "desc": r["skill_desc"],
                "cooldown": r["cooldown"],
            }
            for r in rows
        ],
    }

# ── 对话问答 ──

from pydantic import BaseModel  # noqa: E402


class AzurChatRequest(BaseModel):
    query: str


@router.post("/api/azur/chat")
def azur_chat_endpoint(request: AzurChatRequest) -> dict:
    q = (request.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query 不能为空")
    return azur_chat.answer(q)


def _azur_sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/api/azur/chat/stream")
def azur_chat_stream(request: AzurChatRequest):
    q = (request.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query 不能为空")

    def generate():
        try:
            data, context = azur_chat.prepare(q)
        except Exception as exc:
            yield _azur_sse({"type": "error", "message": str(exc)[:200]})
            return

        meta = {k: v for k, v in data.items() if not k.startswith("_") and k != "text"}
        yield _azur_sse({"type": "meta", **meta})

        if data.get("intent") == "list" or not context or not llm.is_available():
            yield _azur_sse({"type": "delta", "content": azur_chat.fallback_text(context)})
            yield _azur_sse({"type": "done"})
            return

        try:
            messages = azur_chat.build_messages(q, context)
            for kind, chunk in llm.stream_chat(messages, temperature=0.3, max_tokens=400, timeout=180):
                if kind == "answer" and chunk:
                    yield _azur_sse({"type": "delta", "content": chunk})
        except Exception as exc:
            yield _azur_sse({"type": "error", "message": str(exc)[:200]})

        yield _azur_sse({"type": "done"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
