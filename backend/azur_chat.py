"""碧蓝航线对话问答：意图路由 + 实体提取 + 数据组装。"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

import jieba

import llm

DB_PATH = __import__("pathlib").Path(r"D:\AI\azur-data\azur_assistant.sqlite")

SKILL_WORDS = ("技能", "弹幕", "效果")
EQUIP_WORDS = ("装备", "武器", "炮", "鱼雷", "飞机", "设备")
STATS_WORDS = ("属性", "面板", "耐久", "炮击", "雷击", "防空", "航空", "数据", "多少")
LIST_WORDS = ("有哪些", "有什么", "推荐", "列举", "列表", "谁", "全部")

ATTR_ORDER = ["耐久", "炮击", "雷击", "防空", "航空", "装填", "命中", "机动", "航速", "反潜"]

_SHIP_CACHE: list[dict[str, Any]] | None = None


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _load_ships() -> list[dict[str, Any]]:
    global _SHIP_CACHE
    if _SHIP_CACHE is not None:
        return _SHIP_CACHE
    con = _conn()
    rows = [
        dict(r)
        for r in con.execute(
            "select id, name, english_name, type_zh, star, rarity, painting from ship"
            " order by length(name) desc"
        )
    ]
    con.close()
    for s in rows:
        if s["name"]:
            jieba.add_word(s["name"], freq=200000, tag="nz")
    _SHIP_CACHE = rows
    return rows


def _find_ships(q: str) -> list[dict]:
    """找舰船。支持简称和别名。"""
    ships = _load_ships()
    words = set(jieba.lcut(q))

    # 1. 分词精确命中（最可靠）
    hits = [s for s in ships if s["name"] and s["name"] in words]
    if hits:
        hits.sort(key=lambda s: (-s["star"], len(s["name"] or "")))
        return hits[:6]

    # 2. 问句包含完整舰船名
    hits = [s for s in ships if s["name"] and s["name"] in q]
    if hits:
        hits.sort(key=lambda s: (-s["star"], len(s["name"] or "")))
        return hits[:6]

    # 3. 子串兜底：要求词长度 >= 3，避免「莉雅」这类 2 字碎片误命中
    #    （「阿尔托莉雅」会被 jieba 拆出「莉雅」，而碧蓝有「贝莉雅」）
    candidates = [w for w in words if len(w) >= 3 and not w.isdigit()]
    for s in ships:
        name = s["name"] or ""
        if not name:
            continue
        for w in candidates:
            if w in name:
                hits.append(s)
                break

    hits.sort(key=lambda s: (-s["star"], len(s["name"] or "")))
    return hits[:6]


def classify_intent(q: str, ships: list[dict]) -> str:
    if any(w in q for w in LIST_WORDS):
        return "list"
    if any(w in q for w in SKILL_WORDS):
        return "skill"
    if any(w in q for w in EQUIP_WORDS):
        return "equip"
    if any(w in q for w in STATS_WORDS):
        return "stats"
    if ships:
        return "ship"
    return "search"


def _parse_attrs(attrs_json: str, growth_json: str) -> dict[str, float]:
    try:
        attrs = json.loads(attrs_json or "[]")
    except Exception:
        attrs = []
    try:
        growth = json.loads(growth_json or "[]")
    except Exception:
        growth = []

    index = {0: "耐久", 1: "炮击", 2: "雷击", 3: "防空", 4: "航空", 5: "装填",
             7: "命中", 8: "机动", 9: "航速", 10: "幸运", 11: "反潜"}
    out: dict[str, float] = {}
    for idx, name in index.items():
        if idx >= len(attrs):
            continue
        base_v = attrs[idx] or 0
        grow_v = growth[idx] if idx < len(growth) else 0
        out[name] = round(base_v + (grow_v or 0) * 124 / 1000, 1)
    return out


def _ship_payload(con: sqlite3.Connection, ship: dict) -> dict:
    row = con.execute("select * from ship where id = ?", (ship["id"],)).fetchone()
    if not row:
        return {}
    attrs = _parse_attrs(row["attrs"], row["attrs_growth"])

    group = row["id"][:5] if len(row["id"]) >= 5 else row["id"]
    skins = [
        {"id": s["id"], "name": s["name"], "painting": s["painting"]}
        for s in con.execute(
            "select id, name, painting from ship_skin where ship_group = ?", (group,)
        )
    ]

    return {
        "id": row["id"],
        "name": row["name"],
        "english_name": row["english_name"],
        "type": row["type_zh"],
        "star": row["star"],
        "rarity": row["rarity"],
        "icon": f"/api/azur/icon/{row['painting']}" if row["painting"] else None,
        "attrs": attrs,
        "skins": skins,
    }


SYSTEM_PROMPT = (
    "你是「碧蓝航线」助手。用户会问舰船属性、技能、装备等问题。\n"
    "规则：\n"
    "1. 只根据下面提供的资料回答，不要编造资料里没有的内容。\n"
    "2. 如果资料不足，直接说「资料里没有这部分」。\n"
    "3. 回答用中文，简洁，2-4 句话。\n"
    "4. 不要输出 Markdown 表格或代码块。"
)


def prepare(q: str) -> tuple[dict, str]:
    con = _conn()
    try:
        ships = _find_ships(q)
        intent = classify_intent(q, ships)

        data: dict[str, Any] = {"intent": intent, "query": q}
        lines: list[str] = []

        if intent == "list":
            ctx, payload = _handle_list(con, q)
            data.update(payload)
            lines.append(ctx)
        elif ships:
            target = ships[0]
            payload = _ship_payload(con, target)
            data["ship"] = payload
            if len(ships) > 1:
                data["candidates"] = [
                    {"id": s["id"], "name": s["name"], "type": s["type_zh"], "star": s["star"]}
                    for s in ships
                ]

            lines.append(f"舰船：{payload['name']}，{payload['type']}，{payload['star']} 星")
            attrs = payload.get("attrs") or {}
            top = [(k, attrs[k]) for k in ATTR_ORDER if k in attrs and attrs[k] > 0]
            if top:
                lines.append("满级属性：" + "、".join(f"{k} {v:.0f}" for k, v in top))

            if intent == "skill":
                skills = con.execute(
                    "select skill_name, skill_desc from ship_skill_link where ship_id = ?",
                    (payload["id"],),
                ).fetchall()
                if skills:
                    lines.append("技能：")
                    for r in skills:
                        lines.append(f"· {r['skill_name']}：{r['skill_desc']}")
                else:
                    lines.append("这个舰船没有配置技能资料")
            if intent == "equip":
                rows = con.execute(
                    "select name, rarity, descrip from equip order by rarity desc limit 10"
                ).fetchall()
                if rows:
                    lines.append("高稀有度装备示例：" + "、".join(r["name"] for r in rows[:6]))
            if intent == "stats":
                lines.append(f"皮肤数量：{len(payload.get('skins') or [])}")
        else:
            rows = con.execute(
                "select id, name, type_zh, star from ship where name like ? limit 5",
                (f"%{q}%",),
            ).fetchall()
            if rows:
                data["suggestions"] = [dict(r) for r in rows]
                lines.append(f"没直接匹配到舰船，但找到这些：{'、'.join(r['name'] for r in rows)}")
    finally:
        con.close()

    return data, "\n".join(x for x in lines if x)


def _handle_list(con: sqlite3.Connection, q: str) -> tuple[str, dict]:
    star = None
    m = re.search(r"([1-6])星", q)
    if m:
        star = int(m.group(1))

    TYPE_MAP = {
        "驱逐": "驱逐", "轻巡": "轻巡", "重巡": "重巡", "战巡": "战巡",
        "战列": "战列", "轻航": "轻航", "航母": "航母", "潜艇": "潜艇",
    }
    ship_type = None
    for key in TYPE_MAP:
        if key in q:
            ship_type = TYPE_MAP[key]
            break

    sql = "select id, name, type_zh, star, rarity, painting from ship where 1=1"
    params: list = []
    if star is not None:
        sql += " and star = ?"
        params.append(star)
    if ship_type:
        sql += " and type_zh = ?"
        params.append(ship_type)
    sql += " order by star desc, name limit 30"
    rows = con.execute(sql, params).fetchall()

    label_parts = []
    if star:
        label_parts.append(f"{star} 星")
    if ship_type:
        label_parts.append(ship_type)
    label = "".join(label_parts) or "舰船"

    return (
        f"{label}共 {len(rows)} 艘：{'、'.join(r['name'] for r in rows[:15])}",
        {
            "list_label": label,
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
        },
    )


def build_messages(q: str, context: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"资料：\n{context}\n\n问题：{q}"},
    ]


def fallback_text(context: str) -> str:
    return context or "资料里没有找到相关内容。可以试试舰船名，比如「企业」「拉菲」。"


def answer(q: str) -> dict:
    data, context = prepare(q)
    if data.get("intent") == "list" and context:
        data["text"] = context
        return data

    text = ""
    if llm.is_available() and context:
        try:
            text = llm.chat(
                build_messages(q, context),
                temperature=0.3,
                max_tokens=400,
                timeout=90,
                think=False,
            ).strip()
        except Exception as exc:
            data["llm_error"] = str(exc)[:200]
    data["text"] = text or fallback_text(context)
    return data
