"""总 Agent 接口：统一对话入口。"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import agent_capabilities
import agent_router
import llm

router = APIRouter()


class AgentChatRequest(BaseModel):
    query: str
    capability_id: str = ""


@router.get("/api/agent/capabilities")
def list_capabilities() -> dict:
    """列出所有能力包。"""
    caps = agent_capabilities.build_capabilities()
    return {
        "capabilities": [
            {
                "id": cap.capability_id,
                "name": cap.display_name,
                "keywords": list(cap.keywords),
            }
            for cap in caps
        ]
    }


@router.post("/api/agent/route")
def route_only(request: AgentChatRequest) -> dict:
    """只做路由，不执行（前端可用于显示能力指示）。"""
    q = (request.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query 不能为空")
    result = agent_router.route(q)
    return {
        "capability_id": result.capability_id,
        "display_name": result.display_name,
        "confidence": round(result.confidence, 2),
        "needs_clarify": result.needs_clarify,
        "clarify_question": result.clarify_question,
        "candidates": result.candidates,
    }


@router.post("/api/agent/chat")
def agent_chat(request: AgentChatRequest) -> dict:
    """统一对话（非流式）。"""
    q = (request.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query 不能为空")
    return agent_router.execute(q, request.capability_id)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/api/agent/chat/stream")
def agent_chat_stream(request: AgentChatRequest):
    """统一对话（流式）。"""
    q = (request.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query 不能为空")

    def generate():
        # 1. 先路由
        try:
            route_result = agent_router.route(q)
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)[:200]})
            return

        if route_result.needs_clarify:
            yield _sse(
                {
                    "type": "meta",
                    "capability_id": "",
                    "display_name": "",
                    "needs_clarify": True,
                    "candidates": route_result.candidates,
                }
            )
            yield _sse({"type": "delta", "content": route_result.clarify_question})
            yield _sse({"type": "done"})
            return

        # 2. 告知前端选中了哪个能力
        yield _sse(
            {
                "type": "meta",
                "capability_id": route_result.capability_id,
                "display_name": route_result.display_name,
                "confidence": round(route_result.confidence, 2),
                "needs_clarify": False,
            }
        )

        # 3. 执行能力（复用各游戏的流式端点）
        cap_id = route_result.capability_id
        stream_path = {
            "game:minecraft": "/api/mc/chat/stream",
            "game:arknights": "/api/ak/chat/stream",
            "game:fgo": "/api/fgo/chat/stream",
            "game:hsr": "/api/hsr/chat/stream",
            "game:azur": "/api/azur/chat/stream",
        }.get(cap_id)

        if stream_path:
            # 转发现有游戏的 SSE
            import requests
            from fastapi import Request  # noqa: F401

            try:
                resp = requests.post(
                    "http://127.0.0.1:8500" + stream_path,
                    json={"query": q},
                    stream=True,
                    timeout=300,
                )
                for line in resp.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data: "):
                        continue
                    try:
                        evt = json.loads(line[6:])
                    except Exception:
                        continue
                    # 把各游戏自己的 meta 转成通用 meta（带能力信息）
                    if evt.get("type") == "meta":
                        evt.setdefault("capability_id", cap_id)
                        evt.setdefault("display_name", route_result.display_name)
                    yield _sse(evt)
            except Exception as exc:
                yield _sse({"type": "error", "message": str(exc)[:200]})
            yield _sse({"type": "done"})
            return

        # 提示词能力：没有流式实现，走非流式后整段返回
        try:
            result = agent_router.execute(q, cap_id)
            text = result.get("text") or ""
            if text:
                yield _sse({"type": "delta", "content": text})
            if result.get("error"):
                yield _sse({"type": "error", "message": result["error"]})
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)[:200]})
        yield _sse({"type": "done"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
