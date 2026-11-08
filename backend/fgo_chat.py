"""FGO 对话问答：意图路由 + 实体提取 + 数据组装。"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

import jieba

import llm

DB_PATH = __import__("pathlib").Path(r"D:\AI\fgo-data\fgo_assistant.sqlite")

SKILL_WORDS = ("技能",)
NP_WORDS = ("宝具", "大招", "宝具本")
STATS_WORDS = ("属性", "面板", "攻击", "生命", "数据", "多少")
LIST_WORDS = ("有哪些", "推荐", "列举", "列表", "谁")

CARD_ZH = {"Arts": "蓝卡", "Buster": "红卡", "Quick": "绿卡"}

_SERVANT_CACHE: list[dict[str, Any]] | None = None


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _load_servants() -> list[dict[str, Any]]:
    global _SERVANT_CACHE
    if _SERVANT_CACHE is not None:
        return _SERVANT_CACHE

    con = _conn()
    rows = [
        dict(r)
        for r in con.execute(
            "select id, collection_no, name, original_name, class_name, class_zh, rarity from servant"
            " order by length(name) desc"
        )
    ]
    con.close()

    for s in rows:
        if s["name"]:
            jieba.add_word(s["name"], freq=200000, tag="nz")
        if s["original_name"] and s["original_name"] != s["name"]:
            jieba.add_word(s["original_name"], freq=100000, tag="nz")

    _SERVANT_CACHE = rows
    return rows


def _find_servants(q: str) -> list[dict]:
    """找从者。支持简称（「阿尔托莉雅」→「阿尔托莉雅·潘德拉贡」）。

    同名不同职阶会全部返回（如阿尔托莉雅有 4 个职阶）。
    """
    servants = _load_servants()
    words = set(jieba.lcut(q))

    # 1. 分词精确命中
    hits = [s for s in servants if s["name"] and s["name"] in words]
    if hits:
        hits.sort(key=lambda s: (s.get("collection_no") or 9999, len(s["name"] or "")))
        return hits

    # 2. 问句包含完整从者名
    hits = [s for s in servants if s["name"] and s["name"] in q]
    if hits:
        hits.sort(key=lambda s: (s.get("collection_no") or 9999, len(s["name"] or "")))
        return hits

    # 3. 简称：问句里的词是从者名的子串（词长 >= 2）
    candidates = [w for w in words if len(w) >= 2 and not w.isdigit()]
    hits = []
    seen = set()
    for s in servants:
        name = s["name"] or ""
        if not name or s["id"] in seen:
            continue
        for w in candidates:
            if w in name:
                hits.append(s)
                seen.add(s["id"])
                break

    # 4. 从者名前缀匹配（「阿尔托莉雅」是「阿尔托莉雅·潘德拉贡」的前缀）
    if not hits:
        for s in servants:
            name = s["name"] or ""
            if not name:
                continue
            for w in candidates:
                if name.startswith(w):
                    hits.append(s)
                    seen.add(s["id"])
                    break

    # 名字短的优先（「阿尔托莉雅·潘德拉贡」排在「阿尔托莉雅·潘德拉贡〔圣诞Alter〕」前面）
    hits.sort(key=lambda s: (s.get("collection_no") or 9999, len(s["name"] or "")))
    return hits[:8]


def classify_intent(q: str, servants: list[dict]) -> str:
    # 列表查询优先：问「有哪些」「推荐」时不按单个从者处理
    if any(w in q for w in LIST_WORDS):
        return "list"
    if any(w in q for w in NP_WORDS):
        return "np"
    if any(w in q for w in SKILL_WORDS):
        return "skill"
    if servants:
        return "servant"
    return "search"


def _servant_payload(con: sqlite3.Connection, sid: int) -> dict:
    row = con.execute("select * from servant where id = ?", (sid,)).fetchone()
    skills = [
        {"name": r["name"], "detail": r["detail"]}
        for r in con.execute(
            "select name, detail from servant_skill where servant_id = ? order by skill_index",
            (sid,),
        )
    ]
    nps = [
        {"name": r["name"], "rank": r["rank"], "card": r["card"], "detail": r["detail"]}
        for r in con.execute(
            "select name, rank, card, detail from servant_np where servant_id = ? order by np_index",
            (sid,),
        )
    ]
    return {
        "id": row["id"],
        "name": row["name"],
        "original_name": row["original_name"],
        "class_name": row["class_zh"],
        "rarity": row["rarity"],
        "atk_max": row["atk_max"],
        "hp_max": row["hp_max"],
        "cost": row["cost"],
        "face": f"/api/fgo/face/{row['id']}",
        "skills": skills,
        "noble_phantasms": nps,
    }


SYSTEM_PROMPT = (
    "你是「Fate/Grand Order」助手。用户会问从者属性、技能、宝具等问题。\n"
    "规则：\n"
    "1. 只根据下面提供的资料回答，不要编造资料里没有的内容。\n"
    "2. 如果资料不足，直接说「资料里没有这部分」。\n"
    "3. 回答用中文，简洁，2-4 句话。\n"
    "4. 不要输出 Markdown 表格或代码块。"
)


def prepare(q: str) -> tuple[dict, str]:
    """查数据、组装上下文。"""
    con = _conn()
    try:
        servants = _find_servants(q)
        intent = classify_intent(q, servants)

        data: dict[str, Any] = {"intent": intent, "query": q}
        lines: list[str] = []

        if intent == "list":
            ctx, payload = _handle_list(con, q)
            data.update(payload)
            lines.append(ctx)
        elif servants:
            # 同名多职阶时，选最匹配的（默认第一个）
            target = servants[0]
            payload = _servant_payload(con, target["id"])
            data["servant"] = payload
            data["candidates"] = [
                {"id": s["id"], "name": s["name"], "class_name": s["class_zh"], "rarity": s["rarity"]}
                for s in servants[:6]
            ] if len(servants) > 1 else None

            lines.append(
                f"从者：{payload['name']}，{payload['class_name']}，{payload['rarity']} 星"
            )
            lines.append(f"满级 ATK {payload['atk_max']}，HP {payload['hp_max']}，费用 {payload['cost']}")

            if intent in ("skill", "servant"):
                for i, sk in enumerate(payload["skills"][:4], 1):
                    lines.append(f"技能 {i}「{sk['name']}」：{sk['detail']}")
            if intent in ("np", "servant"):
                for np in payload["noble_phantasms"][:2]:
                    card = CARD_ZH.get(np["card"], np["card"])
                    lines.append(f"宝具「{np['name']}」（{np['rank']}，{card}）：{np['detail']}")
        else:
            rows = con.execute(
                "select id, name, class_zh, rarity from servant where name like ? limit 5",
                (f"%{q}%",),
            ).fetchall()
            if rows:
                data["suggestions"] = [dict(r) for r in rows]
                lines.append(f"没直接匹配到从者，但找到这些：{'、'.join(r['name'] for r in rows)}")
    finally:
        con.close()

    return data, "\n".join(x for x in lines if x)


def _handle_list(con: sqlite3.Connection, q: str) -> tuple[str, dict]:
    rarity = None
    m = re.search(r"([0-5])星", q)
    if m:
        rarity = int(m.group(1))

    class_key = None
    for zh, en in (
        ("剑士", "saber"), ("弓兵", "archer"), ("枪兵", "lancer"), ("骑兵", "rider"),
        ("术师", "caster"), ("暗杀者", "assassin"), ("狂战士", "berserker"),
        ("裁定者", "ruler"), ("复仇者", "avenger"), ("降临者", "foreigner"),
    ):
        if zh in q:
            class_key = en
            break

    sql = "select id, name, class_zh, rarity from servant where 1=1"
    params: list = []
    if rarity is not None:
        sql += " and rarity = ?"
        params.append(rarity)
    if class_key:
        sql += " and class_name = ?"
        params.append(class_key)
    sql += " order by collection_no limit 30"
    rows = con.execute(sql, params).fetchall()

    label_parts = []
    if rarity:
        label_parts.append(f"{rarity} 星")
    if class_key:
        label_parts.append(class_key)
    label = "".join(label_parts) or "从者"

    return (
        f"{label}共 {len(rows)} 个：{'、'.join(r['name'] for r in rows[:15])}",
        {
            "list_label": label,
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
        },
    )


def build_messages(q: str, context: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"资料：\n{context}\n\n问题：{q}"},
    ]


def fallback_text(context: str) -> str:
    return context or "资料里没有找到相关内容。可以试试从者名，比如「阿尔托莉雅」。"


def answer(q: str) -> dict:
    data, context = prepare(q)
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
    # 列表查询直接返回整理好的文本，不让 LLM 自由发挥
    if data.get("intent") == "list" and context:
        data["text"] = context
        return data

    data["text"] = text or fallback_text(context)
    return data
