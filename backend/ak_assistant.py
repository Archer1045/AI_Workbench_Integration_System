"""明日方舟知识助手：查询接口。

数据来源：D:\\AI\\ak-data\\ak_assistant.sqlite（游戏数据）+ avatars（头像）
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

import ak_chat
import llm
from fastapi.responses import FileResponse, StreamingResponse

router = APIRouter()

DATA_DIR = Path(r"D:\AI\ak-data")
DB_PATH = DATA_DIR / "ak_assistant.sqlite"
AVATAR_DIR = DATA_DIR / "avatars"


def _conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail=f"方舟数据库不存在: {DB_PATH}")
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


@router.get("/api/ak/stats")
def ak_stats() -> dict:
    con = _conn()
    out = {}
    for table in ("operator", "operator_skill", "operator_talent", "item", "stage"):
        out[table] = con.execute(f"select count(*) from {table}").fetchone()[0]
    out["avatars"] = len(list(AVATAR_DIR.glob("*.png"))) if AVATAR_DIR.exists() else 0
    con.close()
    return out


@router.get("/api/ak/search")
def ak_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    """搜索干员（中文名/英文名/ID 模糊匹配）。"""
    con = _conn()
    rows = con.execute(
        "select id, name, name_en, rarity, profession_zh, nation_zh, tags"
        " from operator"
        " where name like ? or name_en like ? or id like ?"
        " order by rarity desc, name limit ?",
        (f"%{q}%", f"%{q}%", f"%{q}%", limit),
    ).fetchall()
    con.close()
    return {
        "query": q,
        "results": [
            {
                "id": r["id"],
                "name": r["name"],
                "name_en": r["name_en"],
                "rarity": r["rarity"],
                "profession": r["profession_zh"],
                "nation": r["nation_zh"],
                "tags": r["tags"].split(",") if r["tags"] else [],
                "avatar": f"/api/ak/avatar/{r['name']}" if r["name"] else None,
            }
            for r in rows
        ],
    }


@router.get("/api/ak/operator/{name}")
def ak_operator(name: str) -> dict:
    """干员详情：属性、技能、天赋。"""
    con = _conn()
    row = con.execute(
        "select * from operator where name = ? or id = ? or name_en = ?",
        (name, name, name),
    ).fetchone()
    if not row:
        con.close()
        raise HTTPException(status_code=404, detail=f"干员不存在: {name}")

    op = dict(row)
    op_id = op["id"]

    skills = [
        dict(r)
        for r in con.execute(
            "select skill_id, skill_index from operator_skill where operator_id = ? order by skill_index",
            (op_id,),
        )
    ]
    talents = [
        dict(r)
        for r in con.execute(
            "select talent_index, name, description, unlock_phase"
            " from operator_talent where operator_id = ? order by talent_index",
            (op_id,),
        )
    ]

    # 材料清单（2026-11-09 补）
    KIND_LABELS = {"evolve": "精英化", "skill": "技能升级", "mastery": "专精"}
    grouped: dict[str, dict[int, list[dict]]] = {}
    for r in con.execute(
        "select kind, stage, item_name, count from operator_material"
        " where operator_id = ? order by kind, stage",
        (op_id,),
    ):
        grouped.setdefault(r["kind"], {}).setdefault(r["stage"], []).append(
            {"name": r["item_name"], "count": r["count"]}
        )
    materials = [
        {
            "kind": kind,
            "label": KIND_LABELS.get(kind, kind),
            "stages": [
                {"stage": stage, "materials": mats}
                for stage, mats in sorted(stages.items())
            ],
        }
        for kind, stages in grouped.items()
        if stages
    ]

    con.close()

    return {
        "id": op_id,
        "name": op["name"],
        "name_en": op["name_en"],
        "rarity": op["rarity"],
        "profession": op["profession_zh"],
        "sub_profession": op["sub_profession"],
        "nation": op["nation_zh"],
        "position": "远程" if op["position"] == "RANGED" else "近战",
        "tags": op["tags"].split(",") if op["tags"] else [],
        "description": op["description"],
        "usage": op["usage"],
        "obtain": op["obtain"],
        "avatar": f"/api/ak/avatar/{op['name']}" if op["name"] else None,
        "stats": {
            "hp": op["hp"],
            "atk": op["atk"],
            "def": op["def"],
            "res": op["res"],
            "cost": op["cost"],
            "block": op["block"],
            "atk_interval": op["atk_interval"],
        },
        "skills": skills,
        "materials": materials,
        "talents": talents,
    }


@router.get("/api/ak/avatar/{name}")
def ak_avatar(name: str):
    """返回干员头像。"""
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="非法名称")
    path = AVATAR_DIR / f"{name}.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"头像不存在: {name}")
    return FileResponse(path, media_type="image/png")


@router.get("/api/ak/item")
def ak_item(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    """搜索物品/材料。"""
    con = _conn()
    rows = con.execute(
        "select id, name, rarity, item_type, usage, obtain_approach from item"
        " where name like ? or id like ? order by rarity desc, name limit ?",
        (f"%{q}%", f"%{q}%", limit),
    ).fetchall()
    con.close()
    return {
        "query": q,
        "results": [
            {
                "id": r["id"],
                "name": r["name"],
                "rarity": r["rarity"],
                "type": r["item_type"],
                "usage": r["usage"],
                "obtain": r["obtain_approach"],
            }
            for r in rows
        ],
    }


@router.get("/api/ak/stage")
def ak_stage(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    """搜索关卡。"""
    con = _conn()
    rows = con.execute(
        "select id, code, name, stage_type, ap_cost from stage"
        " where code like ? or name like ? or id like ? limit ?",
        (f"%{q}%", f"%{q}%", f"%{q}%", limit),
    ).fetchall()
    con.close()
    return {
        "query": q,
        "results": [
            {
                "id": r["id"],
                "code": r["code"],
                "name": r["name"],
                "type": r["stage_type"],
                "ap_cost": r["ap_cost"],
            }
            for r in rows
        ],
    }


@router.get("/api/ak/operators")
def ak_operators(
    profession: str | None = Query(None, description="职业中文名，如「近卫」"),
    rarity: int | None = Query(None, ge=1, le=6),
    nation: str | None = Query(None, description="阵营中文名，如「罗德岛」"),
    position: str | None = Query(None, description="近战 / 远程"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """按职业/星级/阵营/站位列出干员。"""
    con = _conn()
    where = " where 1=1"
    params: list = []
    if profession:
        where += " and profession_zh = ?"
        params.append(profession)
    if rarity:
        where += " and rarity = ?"
        params.append(rarity)
    if nation:
        where += " and nation_zh = ?"
        params.append(nation)
    if position:
        where += " and position = ?"
        params.append("RANGED" if position == "远程" else "MELEE")

    total = con.execute(f"select count(*) from operator{where}", params).fetchone()[0]

    sql = f"select id, name, rarity, profession_zh, nation_zh, position from operator{where}"
    sql += " order by rarity desc, name limit ? offset ?"
    rows = con.execute(sql, [*params, limit, offset]).fetchall()
    con.close()
    return {
        "total": total,
        "returned": len(rows),
        "offset": offset,
        "operators": [
            {
                "id": r["id"],
                "name": r["name"],
                "rarity": r["rarity"],
                "profession": r["profession_zh"],
                "nation": r["nation_zh"],
                "position": "远程" if r["position"] == "RANGED" else "近战",
                "avatar": f"/api/ak/avatar/{r['name']}",
            }
            for r in rows
        ],
    }


@router.get("/api/ak/filters")
def ak_filters() -> dict:
    """筛选项：职业、阵营、站位，以及各组合的数量。"""
    con = _conn()
    professions = [
        {"name": r["profession_zh"], "count": r["n"]}
        for r in con.execute(
            "select profession_zh, count(*) as n from operator"
            " where profession_zh != '' group by profession_zh order by n desc"
        )
    ]
    nations = [
        {"name": r["nation_zh"], "count": r["n"]}
        for r in con.execute(
            "select nation_zh, count(*) as n from operator"
            " where nation_zh != '' group by nation_zh order by n desc"
        )
    ]
    rarities = [
        {"value": r["rarity"], "count": r["n"]}
        for r in con.execute(
            "select rarity, count(*) as n from operator group by rarity order by rarity desc"
        )
    ]
    positions = [
        {"name": "远程" if r["position"] == "RANGED" else "近战", "count": r["n"]}
        for r in con.execute("select position, count(*) as n from operator group by position")
    ]
    con.close()
    return {
        "professions": professions,
        "nations": nations,
        "rarities": rarities,
        "positions": positions,
    }

# ── 对话问答 ──

from pydantic import BaseModel  # noqa: E402


class AkChatRequest(BaseModel):
    query: str


@router.post("/api/ak/chat")
def ak_chat_endpoint(request: AkChatRequest) -> dict:
    """对话式问答：意图路由 + 实体提取 + LLM 润色。"""
    q = (request.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query 不能为空")
    return ak_chat.answer(q)

# ── 流式对话（SSE） ──

import json as _json  # noqa: E402


def _sse(payload: dict) -> str:
    return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/api/ak/chat/stream")
def ak_chat_stream(request: AkChatRequest):
    """流式对话：先返回数据（meta），再逐字返回文字（delta）。"""
    q = (request.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query 不能为空")

    def generate():
        try:
            data, context = ak_chat.prepare(q)
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)[:200]})
            return

        # 先发数据，前端可以立刻渲染干员卡
        meta = {k: v for k, v in data.items() if not k.startswith("_")}
        yield _sse({"type": "meta", **meta})

        if not context:
            yield _sse({"type": "delta", "content": ak_chat.fallback_text(context)})
            yield _sse({"type": "done"})
            return

        if not llm.is_available():
            yield _sse({"type": "delta", "content": ak_chat.fallback_text(context)})
            yield _sse({"type": "done"})
            return

        try:
            messages = ak_chat.build_messages(q, context)
            for kind, chunk in llm.stream_chat(
                messages, temperature=0.3, max_tokens=400, timeout=180
            ):
                if kind == "answer" and chunk:
                    yield _sse({"type": "delta", "content": chunk})
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)[:200]})

        yield _sse({"type": "done"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

# ── 材料清单（2026-11-09） ──

KIND_LABELS = {
    "evolve": "精英化",
    "skill": "技能升级",
    "mastery": "专精",
}


@router.get("/api/ak/materials/{name}")
def ak_materials(name: str) -> dict:
    """查干员的材料清单：精英化 + 技能升级 + 专精。"""
    con = _conn()
    try:
        row = con.execute(
            "select id, name, rarity, profession_zh from operator where name = ? or id = ? limit 1",
            (name, name),
        ).fetchone()
        if not row:
            row = con.execute(
                "select id, name, rarity, profession_zh from operator where name like ? limit 1",
                (f"%{name}%",),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"干员不存在: {name}")

        op_id = row["id"]
        records = con.execute(
            "select kind, stage, item_id, item_name, count from operator_material"
            " where operator_id = ? order by kind, stage",
            (op_id,),
        ).fetchall()
    finally:
        con.close()

    # 按类型分组
    grouped: dict[str, dict[int, list[dict]]] = {}
    for r in records:
        kind = r["kind"]
        stage = r["stage"]
        grouped.setdefault(kind, {}).setdefault(stage, []).append(
            {"id": r["item_id"], "name": r["item_name"], "count": r["count"]}
        )

    sections = []
    for kind in ("evolve", "skill", "mastery"):
        stages = grouped.get(kind) or {}
        if not stages:
            continue
        sections.append(
            {
                "kind": kind,
                "label": KIND_LABELS.get(kind, kind),
                "stages": [
                    {"stage": s, "materials": stages[s]}
                    for s in sorted(stages)
                ],
            }
        )

    return {
        "id": op_id,
        "name": row["name"],
        "rarity": row["rarity"],
        "profession": row["profession_zh"],
        "sections": sections,
    }
