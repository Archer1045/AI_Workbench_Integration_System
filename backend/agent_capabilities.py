"""总 Agent 的能力包抽象。

设计参考 `记录/提示词Agent整合改造方案_2026-11-07.md`：
- 单 Agent + 能力包，不做多 Agent 编排
- 每个能力包暴露 can_handle（置信度）和 handle（执行）
- 游戏能力复用现有 *_chat.prepare()，零重构
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class CapabilityResult:
    """能力执行结果。"""
    capability_id: str
    display_name: str
    text: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class Capability(Protocol):
    """能力包协议。"""

    capability_id: str
    display_name: str
    keywords: tuple[str, ...]

    def can_handle(self, query: str) -> float:
        """返回 0-1 的置信度。"""
        ...

    def handle(self, query: str) -> CapabilityResult:
        """执行查询。"""
        ...


class GameCapability:
    """游戏知识能力包（包装现有 *_chat 模块）。"""

    def __init__(
        self,
        capability_id: str,
        display_name: str,
        keywords: tuple[str, ...],
        chat_module: Any,
        detect_fn: Any,
    ) -> None:
        self.capability_id = capability_id
        self.display_name = display_name
        self.keywords = keywords
        self._chat = chat_module
        self._detect = detect_fn

    def _has_entity(self, query: str) -> bool:
        """轻量实体检测（不跑完整查询）。"""
        try:
            return bool(self._detect(query))
        except Exception:
            return False

    def can_handle(self, query: str) -> float:
        lowered = query.lower()
        # 1. 明确提到游戏名 -> 最高优先级（压过实体误命中）
        for keyword in self.keywords:
            if keyword.lower() in lowered:
                return 0.98
        # 2. 命中该游戏的实体（角色/物品名）
        if self._has_entity(query):
            return 0.85
        return 0.0

    def handle(self, query: str) -> CapabilityResult:
        try:
            data, context = self._chat.prepare(query)
            text = data.get("text") or ""
            if not text:
                # prepare 不生成润色文本，走 answer 拿完整回复
                full = self._chat.answer(query)
                return CapabilityResult(
                    capability_id=self.capability_id,
                    display_name=self.display_name,
                    text=full.get("text") or "",
                    data={k: v for k, v in full.items() if k != "text"},
                )
            return CapabilityResult(
                capability_id=self.capability_id,
                display_name=self.display_name,
                text=text,
                data={k: v for k, v in data.items() if k != "text"},
            )
        except Exception as exc:
            return CapabilityResult(
                capability_id=self.capability_id,
                display_name=self.display_name,
                text="",
                error=str(exc)[:200],
            )


class PromptCapability:
    """提示词能力包（复用 prompt_chat 的纯函数）。

    只在「问外观 / 要提示词 / 查 tag」时命中。
    命中角色名本身不算，否则会抢走游戏知识类问题（如「三月七的技能」）。
    """

    capability_id = "prompt"
    display_name = "提示词助手"
    keywords = (
        "提示词",
        "tag",
        "标签",
        "发色",
        "瞳色",
        "服装",
        "外观",
        "穿搭",
        "配色",
        "怎么画",
    )

    # 游戏知识类关键词：命中这些就不抢答
    _GAME_INTENT_WORDS = (
        "技能",
        "天赋",
        "属性",
        "宝具",
        "星魂",
        "命座",
        "材料",
        "素材",
        "掉率",
        "关卡",
        "配方",
        "怎么合成",
        "有什么用",
        "是什么",
    )

    def can_handle(self, query: str) -> float:
        lowered = query.lower()

        # 明确问外观/提示词 -> 高置信
        keyword_hits = [kw for kw in self.keywords if kw.lower() in lowered]
        if keyword_hits:
            return 0.9

        # 问游戏知识 -> 不抢答
        if any(word in query for word in self._GAME_INTENT_WORDS):
            return 0.0

        # 只提到角色名/作品名，没问外观 -> 低置信（让游戏包优先）
        try:
            import prompt_chat_logic
            import prompt_chat_work

            if prompt_chat_work.detect_work(query):
                return 0.4
            if prompt_chat_logic.detect_character(query):
                return 0.35
        except Exception:
            pass
        return 0.0

    def handle(self, query: str) -> CapabilityResult:
        try:
            import requests

            resp = requests.post(
                "http://127.0.0.1:8500/api/prompt-agent/chat",
                json={"messages": [{"role": "user", "content": query}]},
                timeout=120,
            )
            if resp.status_code != 200:
                return CapabilityResult(
                    capability_id=self.capability_id,
                    display_name=self.display_name,
                    text="",
                    error=f"HTTP {resp.status_code}",
                )
            data = resp.json()
            return CapabilityResult(
                capability_id=self.capability_id,
                display_name=self.display_name,
                text=str(data.get("reply") or ""),
                data={
                    "prompt": data.get("prompt") or "",
                    "tags": data.get("tags") or [],
                    "tool_calls": data.get("tool_calls") or [],
                },
            )
        except Exception as exc:
            return CapabilityResult(
                capability_id=self.capability_id,
                display_name=self.display_name,
                text="",
                error=str(exc)[:200],
            )


def _mc_detect(query: str) -> bool:
    """MC 实体检测（需要连接）。"""
    import mc_chat

    con = mc_chat._conn()
    try:
        return bool(mc_chat._find_entities(query, con))
    finally:
        try:
            con.close()
        except Exception:
            pass


def build_capabilities() -> list[Any]:
    """构造全部能力包。"""
    import ak_chat
    import azur_chat
    import fgo_chat
    import hsr_chat
    import mc_chat

    return [
        GameCapability(
            "game:minecraft",
            "我的世界",
            ("我的世界", "minecraft", "MC"),
            mc_chat,
            _mc_detect,
        ),
        GameCapability(
            "game:arknights",
            "明日方舟",
            ("明日方舟", "方舟", "arknights", "舟游"),
            ak_chat,
            ak_chat._find_operator,
        ),
        GameCapability(
            "game:fgo",
            "FGO",
            ("fgo", "命运冠位指定", "从者", "英灵"),
            fgo_chat,
            fgo_chat._find_servants,
        ),
        GameCapability(
            "game:hsr",
            "星穹铁道",
            ("星穹铁道", "崩铁", "星铁", "honkai star rail", "星穹"),
            hsr_chat,
            hsr_chat._find_chars,
        ),
        GameCapability(
            "game:azur",
            "碧蓝航线",
            (
                "碧蓝航线",
                "碧蓝",
                "azur lane",
                "舰b",
                "舰B",
                # 舰种词：没提游戏名也能识别
                "航母",
                "战列",
                "战巡",
                "驱逐",
                "轻巡",
                "重巡",
                "潜艇",
                "舰船",
                "舰娘",
            ),
            azur_chat,
            azur_chat._find_ships,
        ),
        PromptCapability(),
    ]
