"""招聘 Agent 对话与提示词翻译接口。"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse, StreamingResponse

import database
import config
import content_filter
import llm
from agent import RecruitmentAgent
from retrieve import retrieve

router = APIRouter()

# 规则回退 Agent 和对话会话缓存
FALLBACK_AGENT = RecruitmentAgent()
CHAT_SESSIONS: dict[str, list[dict]] = {}
LOCK = threading.Lock()
_TRANSLATE_CACHE: dict[str, str] = {}
_TAG_CACHE: dict[str, str] = {}

R18_TAG_DICTIONARY = {
    "nude": "裸体",
    "naked": "裸体",
    "breast": "胸部",
    "breasts": "胸部",
    "nipple": "乳头",
    "nipples": "乳头",
    "areola": "乳晕",
    "penis": "阴茎",
    "penis inside vagina": "阴茎插入阴道",
    "vagina": "阴道",
    "pussy": "阴部",
    "sex": "性交",
    "sexual": "性爱",
    "intercourse": "性交",
    "masturbation": "自慰",
    "masturbating": "自慰",
    "orgasm": "高潮",
    "cum": "射精",
    "cum in pussy": "内射",
    "cum inside": "内射",
    "cowgirl position": "骑乘位",
    "reverse cowgirl position": "反向骑乘位",
    "missionary position": "传教士体位",
    "doggystyle": "后入式",
    "from behind": "背后位",
    "blowjob": "口交",
    "fellatio": "口交",
    "cunnilingus": "舔阴",
    "anal": "肛交",
    "anal sex": "肛交",
    "handjob": "手交",
    "breast play": "胸部抚摸",
    "fondling": "抚摸",
    "spread legs": "张开双腿",
    "lingerie": "蕾丝内衣",
    "lace bra": "蕾丝胸罩",
    "bra": "胸罩",
    "panties": "内裤",
    "underwear": "内衣",
    "thighhighs": "长筒袜",
    "fishnets": "渔网袜",
    "stockings": "丝袜",
    "high heels": "高跟鞋",
    "nsfw": "限制级",
    "explicit": "露骨",
    "hentai": "色情",
}


def _local_tag_translation(text: str) -> str:
    """本地词典优先翻译，全部命中才返回结果。"""
    tags = [tag.strip() for tag in text.split(",") if tag.strip()]
    translated: list[str] = []
    for tag in tags:
        key = tag.replace("_", " ").strip().lower()
        translated.append(R18_TAG_DICTIONARY.get(key, ""))
    if translated and all(translated):
        return "，".join(translated)
    return ""


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
    local = _local_tag_translation(text)
    if local:
        _TRANSLATE_CACHE[text] = local
        return local
    result = ""
    model = config.R18_MODEL if content_filter.is_nsfw(text) else None
    if llm.is_available():
        for _ in range(2):
            try:
                result = llm.chat(
                    [
                        {
                            "role": "system",
                            "content": "你是绘图提示词翻译助手。把英文绘图提示词翻译成简洁中文，保留关键风格词，只输出翻译结果。"
                            "如果包含成人/R18标签（如 nude、sex、penis、vagina 等），如实翻译，不拒绝、不省略、不委婉。",
                        },
                        {"role": "user", "content": text},
                    ],
                    max_tokens=400,
                    temperature=0.3,
                    think=False,
                    model=model,
                )
                if result.strip():
                    break
            except Exception:
                result = ""
            time.sleep(0.5)
    if not result.strip():
        result = text
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


@router.get("/api/chat/sessions")
def list_agent_sessions() -> dict:
    """招聘 Agent 会话列表。"""
    return {"items": database.list_agent_sessions()}


@router.post("/api/chat/sessions")
def create_agent_session() -> dict:
    """新建招聘 Agent 会话。"""
    return {"session_id": uuid.uuid4().hex}


@router.get("/api/chat/messages")
def get_agent_messages(session_id: str = Query(...)) -> dict:
    """读取招聘 Agent 会话消息。"""
    return {"items": database.list_agent_messages(session_id)}


@router.delete("/api/chat/sessions/{session_id}")
def delete_agent_session(session_id: str) -> dict:
    """删除招聘 Agent 会话。"""
    database.delete_agent_session(session_id)
    return {"ok": True}


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
    if not text:
        return {"translation": ""}
    local = _local_tag_translation(text)
    if local:
        return {"translation": local}
    if not llm.is_available():
        return {"translation": ""}
    return {"translation": translate_text(text)}


def _parse_tag_translations(text: str) -> list[dict]:
    """解析大模型返回的标签翻译 JSON。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict) and item.get("tag")]
    except Exception:
        pass
    pattern = re.compile(r'\{\s*"tag"\s*:\s*"([^"]+)"\s*,\s*"translation"\s*:\s*"([^"]+)"\s*\}')
    return [{"tag": match.group(1), "translation": match.group(2)} for match in pattern.finditer(cleaned)]


@router.post("/api/translate/tags")
def translate_tags(payload: dict = Body(...)):
    """逐条翻译提示词标签，返回标签与中文的映射列表。"""
    text = str(payload.get("text") or "").strip()
    tags = [tag.strip() for tag in text.split(",") if tag.strip()] if text else []
    return {"items": translate_tag_list(tags)}


def translate_tag_list(tags: list[str]) -> list[dict]:
    """翻译标签列表，带缓存和 JSON 解析容错。"""
    if not tags:
        return []
    missing = [tag for tag in tags if tag not in _TAG_CACHE]
    for tag in missing:
        key = tag.replace("_", " ").strip().lower()
        if key in R18_TAG_DICTIONARY:
            _TAG_CACHE[tag] = R18_TAG_DICTIONARY[key]
    missing = [tag for tag in missing if tag not in _TAG_CACHE]
    if missing and llm.is_available():
        result = ""
        model = config.R18_MODEL if any(content_filter.is_nsfw(tag) for tag in missing) else None
        for _ in range(2):
            try:
                result = llm.chat(
                    [
                        {"role": "system", "content": "你是标签翻译助手，只输出 JSON 数组。涉及成人/R18标签时如实翻译，不拒绝、不省略、不委婉。"},
                        {
                            "role": "user",
                            "content": (
                                "逐条翻译以下英文绘图标签为简洁中文，只返回 JSON 数组，"
                                '格式：[{"tag":"英文","translation":"中文"}]。\n'
                                + "\n".join(missing)
                            ),
                        },
                    ],
                    max_tokens=1000,
                    temperature=0.2,
                    think=False,
                    model=model,
                )
                if result.strip():
                    break
            except Exception:
                result = ""
        for item in _parse_tag_translations(result):
            _TAG_CACHE[item["tag"]] = item["translation"]
    for tag in missing:
        _TAG_CACHE.setdefault(tag, tag)
    return [{"tag": tag, "translation": _TAG_CACHE.get(tag, "")} for tag in tags]
