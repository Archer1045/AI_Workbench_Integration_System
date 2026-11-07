"""提示词 Agent 聊天逻辑：意图识别、数据查询、回复组织。"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

import config
import llm
import prompt_chat

# 与提示词无关但常见的话题，用于判断是否需要说明定位
OFF_TOPIC_HINTS = (
    "天气", "气温", "下雨", "股票", "汇率", "新闻", "几点", "日期",
    "讲个笑话", "你是谁", "你能做什么",
)


def _iter_character_names() -> list[tuple[str, str]]:
    con = sqlite3.connect(f"{config.DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select name, preset_id from character_appearance_presets"
        " where enabled = 1 and category = '角色' order by length(name) desc"
    ).fetchall()
    con.close()
    return [(r["name"], r["preset_id"]) for r in rows]


def detect_character(text: str) -> dict[str, Any] | None:
    """从自然语言里找出角色名并查询。长名优先，避免「企业」误命中。"""
    if not text:
        return None
    for name, preset_id in _iter_character_names():
        if name and name in text:
            found = prompt_chat.query_character(preset_id)
            if found:
                return found
    return None


def detect_outfit(text: str) -> dict[str, Any] | None:
    """识别服装关键词。"""
    for keyword in ("办公室", "职业", "校园", "校服", "哥特", "礼服", "泳装", "和服", "睡衣"):
        if keyword in text:
            outfit = prompt_chat.query_outfit(keyword)
            if outfit:
                return outfit
    return None


def is_off_topic(text: str) -> bool:
    return any(hint in text for hint in OFF_TOPIC_HINTS)


def build_reply(
    character: dict[str, Any] | None,
    outfit: dict[str, Any] | None,
    prompt: str,
) -> str:
    lines: list[str] = []
    if character:
        lines.append(f"查到了「{character['name']}」（{character['work']}）。")
        if character["appearance"]:
            lines.append("外貌：" + "、".join(character["appearance"][:8]))
    if outfit:
        lines.append(f"服装用「{outfit['name']}」：" + "、".join(outfit["tags"][:8]))
    if not lines:
        lines.append("没有匹配到具体角色，按你的描述直接拼了一版。")
    lines.append("提示词已拼好，可以直接应用到绘画页。")
    return "\n".join(lines)


def off_topic_reply(text: str) -> str:
    """处理与提示词无关的问题：说明定位，通用问题可以简短回答。"""
    base = "我主要负责提示词和角色资料这块。"
    if llm.is_available():
        try:
            answer = llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是绘图工作台的提示词助手。用户问的问题可能和绘图无关。"
                            "请用一两句简短回答；如果涉及实时信息（天气、股价、新闻）而你不确定，"
                            "就直说无法获取实时数据，不要编造。最后一句提示用户你可以帮他配提示词。"
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                max_tokens=200,
                temperature=0.5,
                think=False,
            )
            answer = (answer or "").strip()
            if answer:
                return base + "\n" + answer
        except Exception:
            pass
    return base + "\n这类实时信息我这边拿不到，你可以直接问我「配一个 XX 的提示词」。"
