"""招聘 Agent 对话与提示词翻译接口。"""
from __future__ import annotations

import json
import threading
import time
import uuid

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse, StreamingResponse

import database
import llm
from agent import RecruitmentAgent
from retrieve import retrieve

router = APIRouter()

# 规则回退 Agent 和对话会话缓存
FALLBACK_AGENT = RecruitmentAgent()
CHAT_SESSIONS: dict[str, list[dict]] = {}
LOCK = threading.Lock()
_TRANSLATE_CACHE: dict[str, str] = {}

SYSTEM_PROMPT = (
    "你是一名外卖骑手招聘助手，负责在北京地区招聘外卖骑手。"
    "回答要自然、口语化，像真人招聘沟通一样，不要像机器人。"
    "思考过程尽量简短，快速给出答案。"
    "优先使用【知识库内容】里的信息回答；知识库没有的信息不要编造，可以引导候选人加微信细聊。"
    "回复控制在 200 字以内。"
)


def build_context(results: list[dict]) -> str:
    """把检索结果拼成给大模型的上下文文本。"""
    lines = []
    for index, item in enumerate(results[:4], 1):
        lines.append(f"[{index}] {item['title']}\n{item['content']}")
    return "\n\n".join(lines)


def translate_text(text: str) -> str:
    """翻译英文绘图提示词，带缓存和失败重试。"""
    if not text:
        return ""
    if text in _TRANSLATE_CACHE:
        return _TRANSLATE_CACHE[text]
    result = ""
    if llm.is_available():
        for _ in range(2):
            try:
                result = llm.chat(
                    [
                        {
                            "role": "system",
                            "content": "你是绘图提示词翻译助手。把英文绘图提示词翻译成简洁中文，保留关键风格词，只输出翻译结果。",
                        },
                        {"role": "user", "content": text},
                    ],
                    max_tokens=400,
                    temperature=0.3,
                    think=False,
                )
                if result.strip():
                    break
            except Exception:
                result = ""
            time.sleep(0.5)
    _TRANSLATE_CACHE[text] = result
    return result


def chat_reply(message: str, session_id: str) -> tuple[str, str]:
    """非流式对话：优先大模型，失败回退规则检索。"""
    with LOCK:
        session = CHAT_SESSIONS.setdefault(session_id, [])
        results = retrieve(message, top_k=4, mode="hybrid")
        context = build_context(results)
        top_score = max((item.get("score") or 0) for item in results) if results else None
        reply = ""
        source = "fallback"
        if llm.is_available():
            messages = (
                [{"role": "system", "content": SYSTEM_PROMPT}]
                + session[-10:]
                + [{"role": "user", "content": f"【知识库内容】\n{context}\n\n【候选人问题】\n{message}"}]
            )
            try:
                reply = llm.chat(messages)
                source = "llm"
            except Exception:
                reply = ""
        if not reply:
            reply, _ = FALLBACK_AGENT.respond(message, session_id=session_id)
            source = "fallback"
        session.append({"role": "user", "content": message})
        session.append({"role": "assistant", "content": reply})
        if len(session) > 20:
            del session[: len(session) - 20]
    database.insert_agent_message(session_id, "user", message)
    database.insert_agent_message(session_id, "assistant", reply, retrieval_score=top_score, source=source)
    return reply, source


def _sse(payload: dict) -> str:
    """把数据包序列化成 SSE 事件。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/api/chat")
def chat(payload: dict = Body(...)):
    """非流式对话接口，保留给简单调用场景。"""
    message = str(payload.get("message") or "").strip()
    if not message:
        return JSONResponse(status_code=400, content={"error": "message 不能为空"})
    session_id = str(payload.get("session_id") or uuid.uuid4().hex)
    reply, source = chat_reply(message, session_id)
    return {"reply": reply, "source": source, "session_id": session_id}


@router.post("/api/chat/stream")
def chat_stream(payload: dict = Body(...)):
    """流式对话接口：先输出思考过程，再输出正式回答。"""
    message = str(payload.get("message") or "").strip()
    if not message:
        return JSONResponse(status_code=400, content={"error": "message 不能为空"})
    session_id = str(payload.get("session_id") or uuid.uuid4().hex)

    def generate():
        with LOCK:
            session = CHAT_SESSIONS.setdefault(session_id, [])
            results = retrieve(message, top_k=4, mode="hybrid")
            context = build_context(results)
            messages = (
                [{"role": "system", "content": SYSTEM_PROMPT}]
                + session[-10:]
                + [{"role": "user", "content": f"【知识库内容】\n{context}\n\n【候选人问题】\n{message}"}]
            )
        full = ""
        source = "llm"
        if llm.is_available():
            try:
                for kind, delta in llm.stream_chat(messages):
                    full += delta
                    yield _sse({"kind": kind, "delta": delta})
                if not full.strip():
                    raise RuntimeError("empty stream")
            except Exception:
                full = ""
        if not full:
            source = "fallback"
            full, _ = FALLBACK_AGENT.respond(message, session_id=session_id)
            yield _sse({"kind": "answer", "delta": full})
        yield _sse({"kind": "done", "source": source, "session_id": session_id, "full": full})
        with LOCK:
            session.append({"role": "user", "content": message})
            session.append({"role": "assistant", "content": full})
            if len(session) > 20:
                del session[: len(session) - 20]
        top_score = max((item.get("score") or 0) for item in results) if results else None
        database.insert_agent_message(session_id, "user", message)
        database.insert_agent_message(session_id, "assistant", full, retrieval_score=top_score, source=source)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/api/translate")
def translate(payload: dict = Body(...)):
    """英文绘图提示词翻译接口。"""
    text = str(payload.get("text") or "").strip()
    if not text or not llm.is_available():
        return {"translation": ""}
    return {"translation": translate_text(text)}
