"""明日方舟对话问答：意图路由 + 实体提取 + 数据组装。

设计原则：
1. 数据全部来自本地库，LLM 只负责把数据说成人话。
2. 用 jieba + 实体词典提取干员名/技能名，不靠整句匹配。
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

import jieba

import llm

DB_PATH = __import__("pathlib").Path(r"D:\AI\ak-data\ak_assistant.sqlite")

# 意图关键词
SKILL_WORDS = ("技能", "几技能", "什么效果", "效果")
TALENT_WORDS = ("天赋",)
STATS_WORDS = ("属性", "面板", "攻击力", "生命", "防御", "数据", "多少")
MATERIAL_WORDS = ("材料", "素材", "精二", "精一", "专精", "需要什么")
LIST_WORDS = ("有哪些", "推荐", "列举", "列表", "谁")

# 中文数字
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6}

_OPERATOR_CACHE: list[dict[str, Any]] | None = None
_SKILL_CACHE: list[dict[str, Any]] | None = None
_JIEBA_READY = False


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _load_entities() -> tuple[list[dict], list[dict]]:
    """加载干员和技能词典（进程内一次）。"""
    global _OPERATOR_CACHE, _SKILL_CACHE, _JIEBA_READY
    if _OPERATOR_CACHE is not None:
        return _OPERATOR_CACHE, _SKILL_CACHE  # type: ignore[return-value]

    con = _conn()
    ops = [dict(r) for r in con.execute(
        "select id, name, name_en, rarity, profession_zh, nation_zh from operator order by length(name) desc"
    )]
    skills = [dict(r) for r in con.execute(
        "select id, name from skill order by length(name) desc"
    )]
    con.close()

    for o in ops:
        if o["name"]:
            jieba.add_word(o["name"], freq=200000, tag="nz")
        if o["name_en"]:
            jieba.add_word(o["name_en"], freq=100000, tag="nz")
    for s in skills:
        if s["name"] and len(s["name"]) >= 2:
            jieba.add_word(s["name"], freq=150000, tag="nz")
    _JIEBA_READY = True

    _OPERATOR_CACHE = ops
    _SKILL_CACHE = skills
    return ops, skills


def _find_operator(q: str) -> dict | None:
    """从问句里找干员（长名优先）。"""
    ops, _ = _load_entities()
    words = set(jieba.lcut(q))
    # 先按分词结果精确匹配
    for o in ops:
        if o["name"] and o["name"] in words:
            return o
    for o in ops:
        if o["name_en"] and o["name_en"] in words:
            return o
    # 再做子串兜底（长名优先）
    for o in ops:
        if o["name"] and o["name"] in q:
            return o
    return None


def _find_skill(q: str) -> dict | None:
    """从问句里找技能名。"""
    _, skills = _load_entities()
    for s in skills:
        if s["name"] and s["name"] in q:
            return s
    return None


def _skill_index(q: str) -> int | None:
    """解析「3技能」「三技能」「第二个技能」。"""
    m = re.search(r"第?([0-9一二三四五六])技能", q)
    if m:
        return CN_NUM.get(m.group(1))
    return None


def classify_intent(q: str, op: dict | None, skill: dict | None) -> str:
    if any(w in q for w in LIST_WORDS) and not op:
        return "list"
    if skill or (op and any(w in q for w in SKILL_WORDS)):
        return "skill"
    if op and any(w in q for w in TALENT_WORDS):
        return "talent"
    if op and any(w in q for w in MATERIAL_WORDS):
        return "material"
    if op:
        return "operator"
    return "search"


def _op_payload(con: sqlite3.Connection, op: dict) -> dict:
    row = con.execute(
        "select * from operator where id = ?", (op["id"],)
    ).fetchone()
    talents = [
        {
            "name": r["name"],
            "description": re.sub(r"<[^>]+>", "", r["description"] or ""),
        }
        for r in con.execute(
            "select name, description from operator_talent where operator_id = ? order by talent_index",
            (op["id"],),
        )
    ]
    return {
        "id": row["id"],
        "name": row["name"],
        "name_en": row["name_en"],
        "rarity": row["rarity"],
        "profession": row["profession_zh"],
        "nation": row["nation_zh"],
        "position": "远程" if row["position"] == "RANGED" else "近战",
        "tags": row["tags"].split(",") if row["tags"] else [],
        "description": row["description"],
        "avatar": f"/api/ak/avatar/{row['name']}",
        "stats": {
            "hp": row["hp"],
            "atk": row["atk"],
            "def": row["def"],
            "res": row["res"],
            "cost": row["cost"],
            "block": row["block"],
        },
        "talents": talents,
    }


def _op_skills(con: sqlite3.Connection, op_id: str) -> list[dict]:
    rows = con.execute(
        "select s.id, s.name, s.sp_cost, s.init_sp, s.duration, s.description"
        " from operator_skill os join skill s on s.id = os.skill_id"
        " where os.operator_id = ? order by os.skill_index",
        (op_id,),
    ).fetchall()
    return [dict(r) for r in rows]


SYSTEM_PROMPT = (
    "你是「明日方舟」助手。用户会问干员属性、技能效果、天赋、素材等问题。\n"
    "规则：\n"
    "1. 只根据下面提供的资料回答，不要编造资料里没有的内容。\n"
    "2. 如果资料不足，直接说「资料里没有这部分」。\n"
    "3. 回答用中文，简洁，2-4 句话。\n"
    "4. 不要输出 Markdown 表格或代码块。"
)


def answer(q: str) -> dict:
    con = _conn()
    try:
        op = _find_operator(q)
        skill = _find_skill(q)
        intent = classify_intent(q, op, skill)

        data: dict[str, Any] = {"intent": intent, "query": q}
        lines: list[str] = []

        if intent == "list":
            data.update(_handle_list(con, q))
            lines.append(data.pop("_context", ""))
        elif intent == "skill" and op:
            idx = _skill_index(q)
            skills = _op_skills(con, op["id"])
            data["operator"] = _op_payload(con, op)
            data["skills"] = skills
            if idx and 1 <= idx <= len(skills):
                target = skills[idx - 1]
                data["focus_skill"] = target
                lines.append(f"干员：{op['name']}")
                lines.append(
                    f"第 {idx} 个技能：{target['name']}，技力 {target['sp_cost']}，"
                    f"初始 {target['init_sp']}，持续 {target['duration']} 秒"
                )
                lines.append(f"效果：{target['description']}")
            else:
                lines.append(f"干员：{op['name']}，共 {len(skills)} 个技能")
                for i, s in enumerate(skills, 1):
                    lines.append(f"  技能 {i}：{s['name']}（技力 {s['sp_cost']}）{s['description']}")
        elif intent == "talent" and op:
            payload = _op_payload(con, op)
            data["operator"] = payload
            lines.append(f"干员：{op['name']}")
            for t in payload["talents"]:
                lines.append(f"天赋「{t['name']}」：{t['description']}")
        elif intent == "material" and op:
            payload = _op_payload(con, op)
            data["operator"] = payload
            lines.append(f"干员：{op['name']}，{op['rarity']} 星 {op['profession_zh']}")
            lines.append(f"资料里暂时没有{op['name']}的升级材料清单，只有基础属性和技能。")
        elif op:
            payload = _op_payload(con, op)
            data["operator"] = payload
            lines.append(
                f"干员：{op['name']}，{op['rarity']} 星 {op['profession_zh']}，"
                f"{payload['nation'] or '未知阵营'}"
            )
            lines.append(f"特性：{payload['description']}")
            s = payload["stats"]
            lines.append(
                f"满级属性：生命 {s['hp']}、攻击 {s['atk']}、防御 {s['def']}、"
                f"法抗 {s['res']}、部署 {s['cost']}、阻挡 {s['block']}"
            )
            for t in payload["talents"]:
                lines.append(f"天赋「{t['name']}」：{t['description']}")
        else:
            # 兜底：全文搜索干员
            rows = con.execute(
                "select name, rarity, profession_zh from operator where name like ? limit 5",
                (f"%{q}%",),
            ).fetchall()
            if rows:
                data["suggestions"] = [dict(r) for r in rows]
                lines.append(f"没直接匹配到干员，但找到这些相关的：{'、'.join(r['name'] for r in rows)}")
    finally:
        con.close()

    context = "\n".join(x for x in lines if x)
    data["_context_len"] = len(context)

    text = ""
    if llm.is_available() and context:
        try:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"资料：\n{context}\n\n问题：{q}"},
            ]
            text = llm.chat(messages, temperature=0.3, max_tokens=400, timeout=90, think=False).strip()
        except Exception as exc:
            data["llm_error"] = str(exc)[:200]

    if not text:
        text = context or "资料里没有找到相关内容。可以试试干员名，比如「银灰」「能天使」。"

    data["text"] = text
    return data


def _handle_list(con: sqlite3.Connection, q: str) -> dict:
    """处理「有哪些 6 星近卫」这类列表查询。"""
    rarity = None
    m = re.search(r"([0-9一二三四五六])星", q)
    if m:
        rarity = CN_NUM.get(m.group(1))

    profession = None
    for p in ("先锋", "近卫", "重装", "狙击", "术师", "医疗", "辅助", "特种"):
        if p in q:
            profession = p
            break

    sql = "select id, name, rarity, profession_zh from operator where 1=1"
    params: list = []
    if rarity:
        sql += " and rarity = ?"
        params.append(rarity)
    if profession:
        sql += " and profession_zh = ?"
        params.append(profession)
    sql += " order by name limit 30"
    rows = con.execute(sql, params).fetchall()

    names = [r["name"] for r in rows]
    label_parts = []
    if rarity:
        label_parts.append(f"{rarity} 星")
    if profession:
        label_parts.append(profession)
    label = "".join(label_parts) or "干员"

    return {
        "list_label": label,
        "operators": [
            {
                "id": r["id"],
                "name": r["name"],
                "rarity": r["rarity"],
                "profession": r["profession_zh"],
                "avatar": f"/api/ak/avatar/{r['name']}",
            }
            for r in rows
        ],
        "_context": f"{label}共 {len(names)} 个：{'、'.join(names[:20])}",
    }
