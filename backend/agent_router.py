"""总 Agent 三层路由。

第一层：关键词初筛（游戏名、能力关键词）
第二层：实体检测（角色名/物品名命中）
第三层：LLM 分类（仅在前两层都不确定时）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import agent_capabilities


@dataclass
class RouteResult:
    """路由结果。"""
    capability_id: str = ""
    display_name: str = ""
    confidence: float = 0.0
    candidates: list[dict[str, Any]] = field(default_factory=list)
    needs_clarify: bool = False
    clarify_question: str = ""


def route(query: str, *, threshold: float = 0.5) -> RouteResult:
    """三层路由。"""
    capabilities = agent_capabilities.build_capabilities()

    # 第一、二层：各能力包自己算置信度（内部已含关键词 + 实体检测）
    scored: list[tuple[float, Any]] = []
    for cap in capabilities:
        try:
            score = cap.can_handle(query)
        except Exception:
            score = 0.0
        if score > 0:
            scored.append((score, cap))

    if not scored:
        return RouteResult(
            needs_clarify=True,
            clarify_question=(
                "这个问题没识别出属于哪个游戏或哪个能力。\n"
                "可以试试：\n"
                "· 游戏问题直接问，如「钻石剑怎么合成」「银灰的天赋」\n"
                "· 提示词问题加「提示词」或问「XX 的瞳色」"
            ),
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    top_score, top_cap = scored[0]

    # 明确提到游戏名（0.95+）：直接采信，不因其他能力的实体误命中而澄清
    if top_score >= 0.95:
        return RouteResult(
            capability_id=top_cap.capability_id,
            display_name=top_cap.display_name,
            confidence=top_score,
        )

    # 唯一命中
    if len(scored) == 1 or top_score - scored[1][0] >= 0.12:
        return RouteResult(
            capability_id=top_cap.capability_id,
            display_name=top_cap.display_name,
            confidence=top_score,
        )

    # 多个能力分数接近：需要澄清
    candidates = [
        {
            "capability_id": cap.capability_id,
            "display_name": cap.display_name,
            "confidence": round(score, 2),
        }
        for score, cap in scored[:4]
    ]
    names = "、".join(c["display_name"] for c in candidates)
    return RouteResult(
        confidence=top_score,
        candidates=candidates,
        needs_clarify=True,
        clarify_question=f"这个问题可能属于多个范围（{names}），你想查哪个？",
    )


def execute(query: str, capability_id: str = "") -> dict[str, Any]:
    """执行查询。capability_id 为空时先路由。"""
    capabilities = agent_capabilities.build_capabilities()
    by_id = {cap.capability_id: cap for cap in capabilities}

    if capability_id and capability_id in by_id:
        cap = by_id[capability_id]
        result = cap.handle(query)
        return {
            "capability_id": result.capability_id,
            "display_name": result.display_name,
            "text": result.text,
            "data": result.data,
            "error": result.error,
            "routed": False,
        }

    route_result = route(query)
    if route_result.needs_clarify:
        return {
            "capability_id": "",
            "display_name": "",
            "text": route_result.clarify_question,
            "data": {},
            "error": "",
            "routed": True,
            "needs_clarify": True,
            "candidates": route_result.candidates,
        }

    cap = by_id[route_result.capability_id]
    result = cap.handle(query)
    return {
        "capability_id": result.capability_id,
        "display_name": result.display_name,
        "text": result.text,
        "data": result.data,
        "error": result.error,
        "routed": True,
        "confidence": route_result.confidence,
    }
