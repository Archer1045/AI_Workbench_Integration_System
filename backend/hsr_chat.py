"""崩铁对话问答：意图路由 + 实体提取 + 数据组装。"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

import jieba

import llm

DB_PATH = __import__("pathlib").Path(r"D:\AI\hsr-data\hsr_assistant.sqlite")

SKILL_WORDS = ("技能", "战技", "终结技", "天赋", "普攻", "秘技")
RANK_WORDS = ("星魂", "命座")
MATERIAL_WORDS = ("材料", "素材", "晋阶", "突破", "需要什么")
LIST_WORDS = ("有哪些", "推荐", "列举", "列表", "谁")

_CHAR_CACHE: list[dict[str, Any]] | None = None


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _load_chars() -> list[dict[str, Any]]:
    global _CHAR_CACHE
    if _CHAR_CACHE is not None:
        return _CHAR_CACHE
    con = _conn()
    rows = [
        dict(r)
        for r in con.execute(
            "select id, name, path_zh, element_zh, rarity from character order by length(name) desc"
        )
    ]
    con.close()
    for c in rows:
        if c["name"]:
            jieba.add_word(c["name"], freq=200000, tag="nz")
    _CHAR_CACHE = rows
    return rows


def _find_chars(q: str) -> list[dict]:
    """找角色，同名不同命途会全部返回（如三月七有存护/巡猎两版）。"""
    chars = _load_chars()
    words = set(jieba.lcut(q))

    hits = [c for c in chars if c["name"] and c["name"] in words]
    if not hits:
        hits = [c for c in chars if c["name"] and c["name"] in q]
    if not hits:
        # 简称：问句里的词是角色名的子串
        candidates = [w for w in words if len(w) >= 2 and not w.isdigit()]
        seen = set()
        for c in chars:
            name = c["name"] or ""
            if not name:
                continue
            for w in candidates:
                if w in name and c["id"] not in seen:
                    hits.append(c)
                    seen.add(c["id"])
                    break

    # 星级高的优先
    hits.sort(key=lambda c: (-c["rarity"], len(c["name"] or "")))
    return hits[:6]


def classify_intent(q: str, chars: list[dict]) -> str:
    if any(w in q for w in LIST_WORDS):
        return "list"
    if any(w in q for w in RANK_WORDS):
        return "rank"
    if any(w in q for w in MATERIAL_WORDS):
        return "material"
    if any(w in q for w in SKILL_WORDS):
        return "skill"
    if chars:
        return "character"
    return "search"


def _char_payload(con: sqlite3.Connection, cid: str) -> dict:
    row = con.execute("select * from character where id = ?", (cid,)).fetchone()
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
    materials = [
        {"promotion": r["promotion"], "name": r["material_name"], "amount": r["amount"]}
        for r in con.execute(
            "select promotion, material_name, amount from character_material"
            " where char_id = ? order by promotion, material_id",
            (cid,),
        )
    ]
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


SYSTEM_PROMPT = (
    "你是「崩坏：星穹铁道」助手。用户会问角色属性、技能、星魂、晋阶材料等问题。\n"
    "规则：\n"
    "1. 只根据下面提供的资料回答，不要编造资料里没有的内容。\n"
    "2. 如果资料不足，直接说「资料里没有这部分」。\n"
    "3. 回答用中文，简洁，2-4 句话。\n"
    "4. 不要输出 Markdown 表格或代码块。"
)


def prepare(q: str) -> tuple[dict, str]:
    con = _conn()
    try:
        chars = _find_chars(q)
        intent = classify_intent(q, chars)

        data: dict[str, Any] = {"intent": intent, "query": q}
        lines: list[str] = []

        if intent == "list":
            ctx, payload = _handle_list(con, q)
            data.update(payload)
            lines.append(ctx)
        elif chars:
            target = chars[0]
            payload = _char_payload(con, target["id"])
            data["character"] = payload
            if len(chars) > 1:
                data["candidates"] = [
                    {"id": c["id"], "name": c["name"], "path": c["path_zh"], "rarity": c["rarity"]}
                    for c in chars
                ]

            lines.append(
                f"角色：{payload['name']}，{payload['path']}，{payload['element']}，{payload['rarity']} 星"
            )
            s = payload["stats"]
            lines.append(f"满级属性：攻击 {s['atk']}、生命 {s['hp']}、防御 {s['def']}、速度 {s['spd']}")

            if intent in ("skill", "character"):
                for sk in payload["skills"][:6]:
                    if not sk["name"]:
                        continue
                    lines.append(f"[{sk['type']}] {sk['name']}：{sk['simple_desc']}")
            if intent == "rank":
                for rk in payload["ranks"][:6]:
                    lines.append(f"星魂 {rk['index']}「{rk['name']}」：{rk['desc'][:60]}")
            if intent == "material":
                by_promo: dict[int, list[str]] = {}
                for m in payload["materials"]:
                    by_promo.setdefault(m["promotion"], []).append(
                        f"{m['name']}x{m['amount']}"
                    )
                for promo, mats in sorted(by_promo.items()):
                    lines.append(f"晋阶 {promo}：{'、'.join(mats)}")
        else:
            rows = con.execute(
                "select id, name, path_zh, rarity from character where name like ? limit 5",
                (f"%{q}%",),
            ).fetchall()
            if rows:
                data["suggestions"] = [dict(r) for r in rows]
                lines.append(f"没直接匹配到角色，但找到这些：{'、'.join(r['name'] for r in rows)}")
    finally:
        con.close()

    return data, "\n".join(x for x in lines if x)


def _handle_list(con: sqlite3.Connection, q: str) -> tuple[str, dict]:
    rarity = None
    m = re.search(r"([1-5])星", q)
    if m:
        rarity = int(m.group(1))

    PATH_MAP = {
        "毁灭": "Warrior", "巡猎": "Rogue", "智识": "Mage", "同谐": "Shaman",
        "虚无": "Warlock", "存护": "Knight", "丰饶": "Priest", "记忆": "Memory",
    }
    path_key = None
    for zh, en in PATH_MAP.items():
        if zh in q:
            path_key = en
            break

    sql = "select id, name, path_zh, element_zh, rarity from character where 1=1"
    params: list = []
    if rarity is not None:
        sql += " and rarity = ?"
        params.append(rarity)
    if path_key:
        sql += " and path = ?"
        params.append(path_key)
    sql += " order by name limit 30"
    rows = con.execute(sql, params).fetchall()

    label_parts = []
    if rarity:
        label_parts.append(f"{rarity} 星")
    if path_key:
        label_parts.append(path_key)
    label = "".join(label_parts) or "角色"

    return (
        f"{label}共 {len(rows)} 个：{'、'.join(r['name'] for r in rows[:15])}",
        {
            "list_label": label,
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
        },
    )


def build_messages(q: str, context: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"资料：\n{context}\n\n问题：{q}"},
    ]


def fallback_text(context: str) -> str:
    return context or "资料里没有找到相关内容。可以试试角色名，比如「三月七」「希儿」。"


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
