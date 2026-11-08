"""我的世界对话问答：意图路由 + 数据组装 + LLM 润色。

设计原则：
1. 数据全部来自本地库，LLM 只负责把数据说成人话，不允许编造。
2. 意图用规则优先，命中不了走 Wiki 全文检索，不轻易调 LLM 分类。
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import jieba

import llm

DATA_DIR = Path(r"D:\AI\mc-data")
DB_PATH = DATA_DIR / "mc_assistant.sqlite"

VERSIONS = ["1.7.10", "1.11", "1.13", "1.16", "1.20", "1.21"]

# 意图关键词
RECIPE_WORDS = ("怎么合成", "怎么制作", "怎么做", "配方", "合成表", "需要什么材料", "用什么做")
DIFF_WORDS = ("新增", "加了什么", "加了哪些", "多了什么", "区别", "差异", "对比", "变化")
GUIDE_WORDS = ("怎么获得", "怎么得到", "在哪找", "哪里挖", "怎么挖", "有什么用", "干什么用")

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


def _strip_wiki(text: str, limit: int = 1200) -> str:
    t = text or ""
    for pattern, repl in _STRIP_PATTERNS:
        t = pattern.sub(repl, t)
    return t.strip()[:limit]


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _extract_version(q: str) -> str | None:
    m = re.search(r"1\.(?:7\.10|11|12|13|14|15|16|17|18|19|20|21)", q)
    if m:
        v = m.group(0)
        if v in VERSIONS:
            return v
    return None


# 实体词典缓存（进程内一次加载）
_ENTITY_CACHE: list[dict[str, Any]] | None = None
_ENTITY_BY_NAME: dict[str, dict[str, Any]] = {}
_JIEBA_READY = False


def _load_entities() -> list[dict[str, Any]]:
    """加载实体清单并注入 jieba 词典（只做一次）。"""
    global _ENTITY_CACHE, _ENTITY_BY_NAME, _JIEBA_READY
    if _ENTITY_CACHE is not None:
        return _ENTITY_CACHE

    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select id, name_zh, name_en, type, icon_file, first_version from entity"
        " where name_zh is not null"
    ).fetchall()
    con.close()

    _ENTITY_CACHE = [dict(r) for r in rows]
    for e in _ENTITY_CACHE:
        name = e["name_zh"]
        if name:
            _ENTITY_BY_NAME[name] = e
            # 名字长的权重高，避免被切成更短的词
            if not _JIEBA_READY:
                jieba.add_word(name, freq=100000, tag="nz")
        if not _JIEBA_READY:
            jieba.add_word(e["id"], freq=50000, tag="nz")
    _JIEBA_READY = True

    return _ENTITY_CACHE


def _find_entities(q: str, con: sqlite3.Connection, limit: int = 6) -> list[dict[str, Any]]:
    """从问句里找候选实体。

    策略（三级）：
    1. jieba 分词后精确命中实体名
    2. 分词结果的词作为实体名的子串（如「下界合金」→「下界合金锭」）
    3. 兜底：问句本身包含完整实体名
    """
    entities = _load_entities()
    seen: set[str] = set()
    found: list[dict[str, Any]] = []

    def _push(entity: dict, matched_by: str) -> None:
        if entity["id"] in seen or len(found) >= limit:
            return
        seen.add(entity["id"])
        found.append({**entity, "_matched_by": matched_by})

    # 第一级：jieba 分词精确命中
    words = [w.strip() for w in jieba.lcut(q) if w.strip()]
    for w in words:
        e = _ENTITY_BY_NAME.get(w)
        if e:
            _push(e, w)
    if found:
        return found

    # 第二级：相邻词组合后做子串匹配（长组合优先，避免「下界」误命中「下界岩」）
    def _substring_hits(token: str) -> int:
        before = len(found)
        for e in entities:
            if e["name_zh"] and token in e["name_zh"]:
                _push(e, token)
            if len(found) >= limit:
                break
        return len(found) - before

    # 先试 3 词、2 词组合，再退回单词
    for span in (3, 2, 1):
        for i in range(len(words) - span + 1):
            token = "".join(words[i : i + span])
            if len(token) < 2:
                continue
            if _substring_hits(token) > 0:
                return found
    return found

    # 第三级：问句里出现完整实体名（长名优先）
    if not found:
        for e in sorted(entities, key=lambda x: -len(x["name_zh"] or "")):
            if e["name_zh"] and e["name_zh"] in q:
                _push(e, "substring")
                if len(found) >= limit:
                    break

    return found


def classify_intent(q: str, entities: list[dict]) -> str:
    """规则优先的意图分类。"""
    has_version = _extract_version(q) is not None
    entity = entities[0] if entities else None

    # 多个候选且问句里没有完整实体名 → 先澄清
    if len(entities) > 1:
        full_hit = any(
            e.get("name_zh") and e["name_zh"] in q for e in entities
        )
        if not full_hit:
            return "clarify"

    if any(w in q for w in DIFF_WORDS) and has_version:
        return "version_diff"
    if any(w in q for w in RECIPE_WORDS) and entity:
        return "recipe"
    if any(w in q for w in GUIDE_WORDS) and entity:
        return "guide"
    if entity:
        return "entity"
    if any(w in q for w in DIFF_WORDS):
        return "version_diff"
    return "wiki"


def _get_recipes(con: sqlite3.Connection, entity_id: str) -> list[dict]:
    rows = con.execute(
        "select version, recipe_type, shape_json, ingredients_json, result_count"
        " from recipe where entity_id = ? order by version",
        (entity_id,),
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "version": r["version"],
                "type": r["recipe_type"],
                "shape": json.loads(r["shape_json"]) if r["shape_json"] else None,
                "ingredients": json.loads(r["ingredients_json"]) if r["ingredients_json"] else None,
                "result_count": r["result_count"],
            }
        )
    return out


def _material_names(con: sqlite3.Connection, ids: set[str]) -> dict[str, str]:
    """材料 id -> 中文名（缺失时回退到英文名）。"""
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    result: dict[str, str] = {}
    for r in con.execute(
        f"select id, name_zh, name_en from entity where id in ({ph})", tuple(ids)
    ):
        result[r["id"]] = r["name_zh"] or r["name_en"] or r["id"]
    for i in ids:
        result.setdefault(i, i)
    return result


def _material_icons(con: sqlite3.Connection, materials: set[str]) -> dict[str, str]:
    if not materials:
        return {}
    ph = ",".join("?" * len(materials))
    result: dict[str, str] = {}
    for r in con.execute(
        f"select id, icon_file from entity where id in ({ph})", tuple(materials)
    ):
        if r["icon_file"]:
            result[r["id"]] = f"/api/mc/icon/{r['icon_file']}"
    return result


def _search_wiki(con: sqlite3.Connection, q: str, limit: int = 3) -> list[dict]:
    try:
        rows = con.execute(
            "select p.title, p.content, bm25(page_fts) as score"
            " from page_fts join page p on p.id = page_fts.rowid"
            " where page_fts match ? order by score limit ?",
            (q, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [
        {"title": r["title"], "text": _strip_wiki(r["content"], 1000)} for r in rows
    ]


def _version_diff(con: sqlite3.Connection, frm: str, to: str, limit: int = 30) -> dict:
    if frm not in VERSIONS or to not in VERSIONS:
        frm, to = "1.7.10", "1.21"
    old = {
        r["entity_id"]
        for r in con.execute(
            "select entity_id from entity_version where version = ?", (frm,)
        )
    }
    rows = con.execute(
        "select ev.entity_id, e.name_zh, e.type, e.icon_file"
        " from entity_version ev join entity e on e.id = ev.entity_id"
        " where ev.version = ?",
        (to,),
    ).fetchall()
    added = [
        {
            "id": r["entity_id"],
            "name_zh": r["name_zh"],
            "type": r["type"],
            "icon_url": f"/api/mc/icon/{r['icon_file']}" if r["icon_file"] else None,
        }
        for r in rows
        if r["entity_id"] not in old
    ]
    added.sort(key=lambda x: x["name_zh"] or x["id"])
    return {"from": frm, "to": to, "total": len(added), "items": added[:limit]}


def _build_context(intent: str, q: str, con: sqlite3.Connection, entity: dict | None) -> tuple[str, dict]:
    """组装给 LLM 的上下文，返回（上下文文本，结构化数据）。"""
    data: dict[str, Any] = {"intent": intent}
    lines: list[str] = []

    if intent == "recipe" and entity:
        recipes = _get_recipes(con, entity["id"])
        data["entity"] = _entity_payload(entity)
        data["recipes"] = recipes[:6]
        mats = set()
        for r in recipes:
            if r["shape"]:
                for row in r["shape"]:
                    for m in row:
                        if m:
                            mats.add(m)
            if r["ingredients"]:
                for m in r["ingredients"]:
                    if m:
                        mats.add(m)
        data["material_icons"] = _material_icons(con, mats)
        names = _material_names(con, mats)
        lines.append(f"物品：{entity['name_zh'] or entity['name_en']}（{entity['id']}）")
        lines.append(f"配方数量：{len(recipes)}")
        for r in recipes[:4]:
            if r["shape"]:
                grid = " / ".join(
                    " ".join(names.get(m, m) if m else "空" for m in row) for row in r["shape"]
                )
                lines.append(
                    f"[{r['version']}] 有序合成（逐行）：{grid} → 产出 {r['result_count']} 个"
                )
            else:
                mats_txt = "、".join(names.get(m, m) for m in r["ingredients"] if m)
                lines.append(
                    f"[{r['version']}] 无序合成：{mats_txt} → 产出 {r['result_count']} 个"
                )

    elif intent == "version_diff":
        frm = _extract_version(q) or "1.7.10"
        to = "1.21"
        if frm == "1.21":
            frm = "1.7.10"
        diff = _version_diff(con, frm, to)
        data["diff"] = diff
        lines.append(f"版本 {frm} → {to} 新增 {diff['total']} 个物品/方块")
        sample = [x["name_zh"] or x["id"] for x in diff["items"][:20]]
        lines.append(f"新增样例（共 {diff['total']} 个，以下为前 20 个）：{'、'.join(sample)}")

    elif intent in ("entity", "guide") and entity:
        data["entity"] = _entity_payload(entity)
        recipes = _get_recipes(con, entity["id"])
        data["recipes"] = recipes[:3]
        mats = set()
        for r in recipes[:3]:
            if r["shape"]:
                for row in r["shape"]:
                    for m in row:
                        if m:
                            mats.add(m)
            if r["ingredients"]:
                for m in r["ingredients"]:
                    if m:
                        mats.add(m)
        data["material_icons"] = _material_icons(con, mats)

        lines.append(f"物品：{entity['name_zh'] or entity['name_en']}（{entity['id']}）")
        lines.append(f"首次出现版本：{entity['first_version']}")
        # 取 Wiki 正文
        page_title = entity["name_zh"] or entity["name_en"]
        page = con.execute(
            "select title, content from page where title = ?", (page_title,)
        ).fetchone()
        if not page:
            found = _search_wiki(con, page_title, 1)
            if found:
                lines.append(f"Wiki 页面「{found[0]['title']}」内容摘录：")
                lines.append(found[0]["text"][:800])
                data["wiki_title"] = found[0]["title"]
        else:
            text = _strip_wiki(page["content"], 1000)
            lines.append(f"Wiki 页面「{page['title']}」内容摘录：")
            lines.append(text[:800])
            data["wiki_title"] = page["title"]

    else:
        found = _search_wiki(con, q, 3)
        data["wiki_results"] = [{"title": x["title"], "snippet": x["text"][:200]} for x in found]
        if found:
            lines.append("Wiki 检索结果：")
            for x in found:
                lines.append(f"【{x['title']}】{x['text'][:400]}")

    return "\n".join(lines), data


def _entity_payload(entity: dict) -> dict:
    return {
        "id": entity["id"],
        "name_zh": entity.get("name_zh"),
        "name_en": entity.get("name_en"),
        "type": entity.get("type"),
        "icon_url": f"/api/mc/icon/{entity['icon_file']}" if entity.get("icon_file") else None,
        "first_version": entity.get("first_version"),
    }


SYSTEM_PROMPT = (
    "你是「我的世界」助手。用户玩过 1.7.10，现在想了解新版本内容。\n"
    "规则：\n"
    "1. 只根据下面提供的资料回答，不要编造资料里没有的内容。\n"
    "2. 如果资料不足，直接说「资料里没有这部分」。\n"
    "3. 回答用中文，简洁，2-4 句话，不要罗列大段清单（清单由界面单独展示）。\n"
    "4. 不要输出 Markdown 表格或代码块。"
)


def prepare(q: str) -> tuple[dict, str]:
    """第一步：查数据、组装上下文。返回 (data, context)。

    若需要澄清，data 里带 clarify 标记，context 为空。
    """
    con = _conn()
    try:
        entities = _find_entities(q, con)
        intent = classify_intent(q, entities)
        entity = entities[0] if entities else None

        # 需要澄清：直接把候选返回，不走 LLM
        if intent == "clarify":
            names = "、".join(e["name_zh"] or e["name_en"] for e in entities[:6])
            return (
                {
                    "intent": "clarify",
                    "query": q,
                    "text": f"「{q}」在资料里对应多个条目：{names}。你想查哪一个？",
                    "candidates": [
                        {
                            "id": e["id"],
                            "name_zh": e["name_zh"],
                            "name_en": e["name_en"],
                            "type": e["type"],
                            "icon_url": f"/api/mc/icon/{e['icon_file']}"
                            if e.get("icon_file")
                            else None,
                        }
                        for e in entities[:6]
                    ],
                },
                "",
            )

        context, data = _build_context(intent, q, con, entity)
        data["query"] = q
        return data, context
    finally:
        try:
            con.close()
        except Exception:
            pass


def build_messages(q: str, context: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"资料：\n{context}\n\n问题：{q}"},
    ]


def answer(q: str) -> dict:
    """非流式：一次性返回完整回复。"""
    data, context = prepare(q)

    # clarify 分支已经带了 text
    if data.get("intent") == "clarify":
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
    if not text:
        text = _fallback_text(data["intent"], data)

    data["text"] = text
    return data


def _fallback_text(intent: str, data: dict) -> str:
    if intent == "recipe" and data.get("recipes"):
        return f"找到 {len(data['recipes'])} 条配方，见下方合成表。"
    if intent == "version_diff" and data.get("diff"):
        return f"新增 {data['diff']['total']} 个物品/方块，见下方列表。"
    if data.get("entity"):
        e = data["entity"]
        return f"{e['name_zh'] or e['name_en']}，首次出现在 {e['first_version']}。"
    wiki = data.get("wiki_results") or []
    if wiki:
        titles = "、".join(x["title"] for x in wiki[:3])
        return f"资料里没有直接对应的条目，但相关页面有：{titles}。可以换个更具体的名字再问。"
    return "资料里没有找到相关内容。可以试试更具体的物品名，比如「下界合金锭」而不是「下界合金」。"

PLAN_SYSTEM_PROMPT = """你是「我的世界」攻略规划助手。根据用户的目标，生成一张 Mermaid 流程图。

规则：
1. 只输出 Mermaid 代码，不要任何解释、不要 Markdown 代码块标记。
2. 使用 `graph LR` 或 `graph TD`。
3. 节点文字用中文，简短（不超过 10 字）。
4. 节点 id 用数字，如 A1、A2，避免特殊字符。
5. 步骤控制在 6-12 个，符合真实游戏流程。
6. 涉及具体物品时用中文名。

示例输出：
graph LR
  A1[出生] --> A2[砍树]
  A2 --> A3[木镐]
  A3 --> A4[石镐]
  A4 --> A5[铁矿]
  A5 --> A6[铁镐]
"""

# 常见目标的兜底模板（LLM 不可用时使用）
PLAN_TEMPLATES = {
    "生存": """graph LR
  A1[出生] --> A2[砍树]
  A2 --> A3[工作台+木镐]
  A3 --> A4[挖石头]
  A4 --> A5[石镐石剑]
  A5 --> A6[找铁矿]
  A6 --> A7[烧铁]
  A7 --> A8[铁镐铁甲]
  A8 --> A9[挖钻石]
  A9 --> A10[钻石装备]
  A10 --> A11[去下界]
  A11 --> A12[打烈焰人]
  A12 --> A13[找要塞]
  A13 --> A14[末地传送门]
  A14 --> A15[击败末影龙]""",
    "钻石": """graph LR
  A1[准备铁镐] --> A2[挖到 Y=-59]
  A2 --> A3[找钻石矿]
  A3 --> A4[铁镐开挖]
  A4 --> A5[钻石]
  A5 --> A6[钻石装备]
  A6 --> A7[做附魔台]
  A7 --> A8[附魔]""",
    "下界": """graph LR
  A1[挖黑曜石] --> A2[做打火石]
  A2 --> A3[搭传送门]
  A3 --> A4[进入下界]
  A4 --> A5[找堡垒遗迹]
  A5 --> A6[打烈焰人]
  A6 --> A7[拿烈焰棒]
  A7 --> A8[合成烈焰粉]""",
    "末影龙": """graph LR
  A1[钻石装备] --> A2[进下界]
  A2 --> A3[打烈焰人]
  A3 --> A4[烈焰粉+末影珍珠]
  A4 --> A5[合成末影之眼]
  A5 --> A6[找到要塞]
  A6 --> A7[激活末地门]
  A7 --> A8[进末地]
  A8 --> A9[炸水晶]
  A9 --> A10[击败末影龙]""",
    "附魔": """graph LR
  A1[挖钻石] --> A2[做附魔台]
  A2 --> A3[做书架]
  A3 --> A4[摆满15个书架]
  A4 --> A5[攒经验]
  A5 --> A6[附魔装备]""",
    "村民": """graph LR
  A1[找村庄] --> A2[做床和工作台]
  A2 --> A3[安置村民]
  A3 --> A4[放讲台]
  A4 --> A5[刷图书管理员]
  A5 --> A6[换经验修补]""",
    "刷怪": """graph LR
  A1[选刷怪点] --> A2[挖刷怪塔]
  A2 --> A3[做水流]
  A3 --> A4[做掉落通道]
  A4 --> A5[挂机刷经验]""",
    "农业": """graph LR
  A1[找水边] --> A2[锄地]
  A2 --> A3[种小麦]
  A3 --> A4[等成熟]
  A4 --> A5[收割]
  A5 --> A6[做面包]""",
}


def _pick_template(goal: str) -> str | None:
    for key, tpl in PLAN_TEMPLATES.items():
        if key in goal:
            return tpl
    return None



def build_plan(goal: str) -> dict:
    """根据目标生成 Mermaid 流程图。模板优先，未命中再走 LLM。"""
    goal = (goal or "").strip()
    if not goal:
        return {"goal": "", "diagram": "", "source": "none", "text": "请说明你想规划什么目标。"}

    # 优先匹配模板（秒出）
    tpl = _pick_template(goal)
    if tpl:
        return {
            "goal": goal,
            "diagram": tpl,
            "source": "template",
            "text": f"已为「{goal}」生成规划图。",
        }

    # 模板没覆盖才走 LLM
    if llm.is_available():
        try:
            messages = [
                {"role": "system", "content": PLAN_SYSTEM_PROMPT},
                {"role": "user", "content": f"目标：{goal}"},
            ]
            raw = llm.chat(
                messages, temperature=0.4, max_tokens=400, timeout=180, think=False
            )
            raw = raw.strip()
            raw = re.sub(r"^```(?:mermaid)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            if "graph " in raw:
                return {
                    "goal": goal,
                    "diagram": raw,
                    "source": "llm",
                    "text": f"已为「{goal}」生成规划图。",
                }
        except Exception as exc:
            print(f"[mc_chat] 规划图 LLM 失败: {str(exc)[:100]}")

    return {
        "goal": goal,
        "diagram": "",
        "source": "none",
        "text": (
            f"暂时无法为「{goal}」生成规划图。"
            "可以试试「生存路线」「钻石流程」「下界准备」「末影龙」「附魔」「村民」「刷怪」「农业」这些目标。"
        ),
    }
