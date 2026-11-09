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
# 掉落查询（2026-11-09，数据源企鹅物流）
DROP_WORDS = ("掉", "刷", "关卡", "哪刷", "去哪", "在哪", "掉落", "理智")
# 活动查询（2026-11-09）
ACTIVITY_WORDS = ("活动", "最近开", "新活动", "什么活动", "活动关卡")

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
    # 再做子串兜底（长名优先）。
    # 单字名（如「阿」）只在上面的分词精确匹配阶段算，
    # 否则「阿尔托莉雅」会被单字「阿」误命中。
    for o in ops:
        name = o["name"] or ""
        if len(name) >= 2 and name in q:
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


LEVEL_PATTERNS = [
    (r"专三|专精三|专3", 10),
    (r"专二|专精二|专2", 9),
    (r"专一|专精一|专1", 8),
    (r"([1-7])级", None),  # 动态取数字
]


def _parse_skill_level(q: str) -> int | None:
    """解析「专三」「专一」「7级」，默认返回 None（表示满级）。"""
    for pattern, level in LEVEL_PATTERNS:
        m = re.search(pattern, q)
        if not m:
            continue
        if level is None:
            return int(m.group(1))
        return level
    return None


def _mentions_activity(q: str) -> bool:
    """检查问句里是否提到已知活动名。"""
    try:
        con = _conn()
        try:
            rows = con.execute(
                "select zone_name from zone where zone_type in ('ACTIVITY', 'ACTIVITY_PERMANENT')"
            ).fetchall()
        finally:
            con.close()
    except Exception:
        return False

    for r in rows:
        name = r["zone_name"] or ""
        if not name:
            continue
        base = name.split("・")[0]
        if base and len(base) >= 2 and base in q:
            return True
    return False


def classify_intent(q: str, op: dict | None, skill: dict | None) -> str:
    # 活动查询最优先：命中「活动」词，或问句里含已知活动名
    if any(w in q for w in ACTIVITY_WORDS) or _mentions_activity(q):
        return "activity"
    # 掉落查询：命中「刷/掉/关卡」等词，且不是问某个干员的材料
    if any(w in q for w in DROP_WORDS) and not (op and any(w in q for w in MATERIAL_WORDS)):
        return "drop"
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

    # 材料清单（2026-11-09 补）
    kind_labels = {"evolve": "精英化", "skill": "技能升级", "mastery": "专精"}
    grouped: dict[str, dict[int, list[dict]]] = {}
    for r in con.execute(
        "select kind, stage, item_name, count from operator_material"
        " where operator_id = ? order by kind, stage",
        (op["id"],),
    ):
        grouped.setdefault(r["kind"], {}).setdefault(r["stage"], []).append(
            {"name": r["item_name"], "count": r["count"]}
        )
    materials = [
        {
            "kind": kind,
            "label": kind_labels.get(kind, kind),
            "stages": [
                {"stage": stage, "materials": mats}
                for stage, mats in sorted(stages.items())
            ],
        }
        for kind, stages in grouped.items()
        if stages
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
        "materials": materials,
    }


def _op_skills(con: sqlite3.Connection, op_id: str) -> list[dict]:
    rows = con.execute(
        "select s.id, s.name, s.sp_cost, s.init_sp, s.duration, s.description"
        " from operator_skill os join skill s on s.id = os.skill_id"
        " where os.operator_id = ? order by os.skill_index",
        (op_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _skill_levels(con: sqlite3.Connection, skill_id: str) -> list[dict]:
    """取技能的全部等级数据。"""
    rows = con.execute(
        "select level, level_label, sp_cost, init_sp, duration, description"
        " from skill_level where skill_id = ? order by level",
        (skill_id,),
    ).fetchall()
    return [dict(r) for r in rows]


SYSTEM_PROMPT = (
    "你是「明日方舟」助手。用户会问干员属性、技能效果、天赋、素材等问题。\n"
    "规则：\n"
    "1. 只根据下面提供的资料回答，不要编造资料里没有的内容。\n"
    "2. 如果资料不足，直接说「资料里没有这部分」。\n"
    "3. 回答用中文，简洁，2-4 句话。\n"
    "3b. 如果资料里标了【最优】或有序号，必须从第 1 名开始回答，不要跳过。\n"
    "4. 不要输出 Markdown 表格或代码块。"
)


def prepare(q: str) -> tuple[dict, str]:
    """第一步：查数据、组装上下文。返回 (data, context)。"""
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
        elif intent == "activity":
            data.update(_handle_activity(con, q))
            lines.append(data.pop("_context", ""))
        elif intent == "drop":
            data.update(_handle_drop(con, q))
            lines.append(data.pop("_context", ""))
        elif intent == "skill" and op:
            idx = _skill_index(q)
            lv = _parse_skill_level(q)
            skills = _op_skills(con, op["id"])
            data["operator"] = _op_payload(con, op)
            data["skills"] = skills
            if idx and 1 <= idx <= len(skills):
                target = skills[idx - 1]
                levels = _skill_levels(con, target["id"])
                data["skill_levels"] = levels
                # 默认专三；用户指定了等级就用指定的
                use_level = lv or 10
                picked = next((x for x in levels if x["level"] == use_level), None) or (
                    levels[-1] if levels else None
                )
                if picked:
                    data["focus_skill"] = {
                        **target,
                        **picked,
                        "skill_index": idx,
                    }
                    lines.append(f"干员：{op['name']}")
                    lines.append(f"第 {idx} 个技能：{target['name']}")
                    lines.append(
                        f"{picked['level_label']} 的数值：技力 {picked['sp_cost']}，"
                        f"初始 {picked['init_sp']}，持续 {picked['duration']} 秒"
                    )
                    lines.append(f"效果：{picked['description']}")
                    # 附上各等级的攻击力变化，方便对比
                    if len(levels) > 1:
                        brief = "、".join(
                            f"{x['level_label']} {x['description'][:24]}" for x in levels
                        )
                        lines.append(f"各等级效果：{brief}")
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
            # 材料清单（2026-11-09 补）
            for sec in payload.get("materials") or []:
                for st in sec["stages"]:
                    mats = "、".join(f"{m['name']}x{m['count']}" for m in st["materials"])
                    stage_label = (
                        f"精{st['stage']}" if sec["kind"] == "evolve" else f"Lv{st['stage']}"
                    )
                    lines.append(f"{sec['label']} {stage_label}：{mats}")
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
    return data, context


def build_messages(q: str, context: str) -> list[dict]:
    """构造 LLM 消息。"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"资料：\n{context}\n\n问题：{q}"},
    ]


def fallback_text(context: str) -> str:
    return context or "资料里没有找到相关内容。可以试试干员名，比如「银灰」「能天使」。"


def answer(q: str) -> dict:
    """非流式：一次性返回完整回复。"""
    data, context = prepare(q)

    # 列表查询直接返回整理好的文本，不让 LLM 自由发挥
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

def _material_candidates(q: str) -> list[str]:
    """从问句里提取可能的材料名（去掉问句词）。"""
    # 先按 data 表里的材料名匹配
    con = _conn()
    try:
        names = [
            r["item_name"]
            for r in con.execute(
                "select distinct item_name from drop_rate where item_name != ''"
            )
        ]
    finally:
        con.close()

    hits = [n for n in names if n in q]
    # 长的优先（避免「装置」抢在「聚酸酯装置」前）
    hits.sort(key=len, reverse=True)
    return hits


def _handle_drop(con: sqlite3.Connection, q: str) -> dict:
    """掉落查询：材料 -> 关卡，按每理智收益排序。"""
    names = _material_candidates(q)

    if not names:
        # 没匹配到材料，给个提示
        return {
            "_context": (
                "没有从问题里识别出材料名。可以这样问：\n"
                "- 「固源岩在哪刷」\n"
                "- 「装置哪个关卡掉得多」"
            ),
        }

    target = names[0]
    rows = con.execute(
        "select stage_code, zone_name, ap_cost, quantity, times, drop_rate, per_ap"
        " from drop_rate where item_name = ? and per_ap is not null"
        " order by per_ap desc limit 10",
        (target,),
    ).fetchall()

    total = con.execute(
        "select count(*) from drop_rate where item_name = ? and per_ap is not null",
        (target,),
    ).fetchone()[0]

    if not rows:
        return {"_context": f"资料里没有「{target}」的掉落数据。"}

    line_parts = [f"材料「{target}」的掉落（共 {total} 个关卡，按每理智收益从高到低）："]
    for idx, r in enumerate(rows):
        tag = "【最优】" if idx == 0 else ""
        line_parts.append(
            f"{idx+1}. {tag}{r['stage_code']}（{r['zone_name']}，{r['ap_cost']} 理智）："
            f"期望 {r['drop_rate']:.2f} 个/次，每理智 {r['per_ap']:.4f} 个"
        )
    line_parts.append("回答时请按上面的顺序，先推荐第 1 名。")

    return {
        "_context": "\n".join(line_parts),
        "drops": {
            "item": target,
            "total_stages": total,
            "top": [
                {
                    "stage": r["stage_code"],
                    "zone": r["zone_name"],
                    "ap_cost": r["ap_cost"],
                    "expected": round(r["drop_rate"], 3),
                    "per_ap": round(r["per_ap"], 4),
                    "samples": r["times"],
                }
                for r in rows
            ],
        },
    }

def _act_number(zone_id: str) -> int:
    import re

    m = re.search(r"act(\d+)", zone_id or "")
    return int(m.group(1)) if m else -1


def _handle_activity(con: sqlite3.Connection, q: str) -> dict:
    """活动查询：列表 或 单个活动详情。"""
    # 先看问句里有没有具体活动名
    zone_rows = con.execute(
        "select zone_id, zone_name, stage_count, drop_count from zone"
        " where zone_type in ('ACTIVITY', 'ACTIVITY_PERMANENT')"
    ).fetchall()

    # 匹配活动名（问句里包含活动名的一段）
    target = None
    for r in zone_rows:
        name = r["zone_name"] or ""
        if not name:
            continue
        # 取活动名去掉「・复刻」等后缀的主体
        base = name.split("・")[0]
        if base and base in q:
            target = r
            break

    if target:
        # 单个活动详情
        zid = target["zone_id"]
        stages = con.execute(
            "select stage_code, ap_cost from stage_info where zone_id = ? order by stage_code",
            (zid,),
        ).fetchall()
        drops = con.execute(
            "select item_name, stage_code, ap_cost, drop_rate, per_ap from drop_rate"
            " where zone_id = ? and per_ap is not null order by per_ap desc limit 15",
            (zid,),
        ).fetchall()

        if not drops:
            return {
                "_context": (
                    f"活动「{target['zone_name']}」有 {len(stages)} 个关卡，"
                    f"但企鹅物流没有它的掉落数据（可能已过期）。"
                ),
                "activity": {
                    "name": target["zone_name"],
                    "stages": [{"code": s["stage_code"], "ap": s["ap_cost"]} for s in stages],
                    "has_data": False,
                },
            }

        parts = [f"活动「{target['zone_name']}」共 {len(stages)} 个关卡，掉落如下（按每理智收益）："]
        for d in drops:
            parts.append(
                f"{d['stage_code']}（{d['ap_cost']} 理智）：{d['item_name']} "
                f"期望 {d['drop_rate']:.2f} 个/次，每理智 {d['per_ap']:.4f} 个"
            )
        return {
            "_context": "\n".join(parts),
            "activity": {
                "name": target["zone_name"],
                "stages": [{"code": s["stage_code"], "ap": s["ap_cost"]} for s in stages],
                "has_data": True,
                "drops": [
                    {
                        "item": d["item_name"],
                        "stage": d["stage_code"],
                        "ap_cost": d["ap_cost"],
                        "expected": round(d["drop_rate"], 3),
                        "per_ap": round(d["per_ap"], 4),
                    }
                    for d in drops
                ],
            },
        }

    # 没有具体活动名 -> 列最近的活动
    items = [
        {
            "zone_id": r["zone_id"],
            "name": r["zone_name"],
            "act": _act_number(r["zone_id"]),
            "stages": r["stage_count"],
            "drops": r["drop_count"],
            "has_data": r["drop_count"] > 0,
        }
        for r in zone_rows
    ]
    items.sort(key=lambda x: (-x["act"], -x["drops"]))

    recent = items[:8]
    with_data = [x for x in items if x["has_data"]]

    parts = ["最近的活动："]
    for x in recent:
        mark = f"（{x['drops']} 条掉落数据）" if x["has_data"] else "（无掉落数据）"
        parts.append(f"act{x['act']} {x['name']}，{x['stages']} 个关卡{mark}")

    if with_data:
        cur = with_data[0]
        parts.append(f"\n当前有掉落数据的活动是「{cur['name']}」，可以问「{cur['name']}刷什么」。")

    return {
        "_context": "\n".join(parts),
        "activities": recent,
        "current_with_data": [x["name"] for x in with_data[:3]],
    }
