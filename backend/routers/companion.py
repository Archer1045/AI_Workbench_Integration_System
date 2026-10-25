"""情感陪伴 Agent：人设、会话、聊天、记忆、设置与联网搜索。"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse

import config
import content_filter
import database
import llm
import prompt_agent
import task_state
from web_tools import WebToolsError, get_web_tools_service

router = APIRouter()

COMPANION_INPUT_DIR = config.AI_PRODUCT_DIR / "companion_inputs"
EMBED_CACHE: dict = {"model": None}
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
EMBED_CACHE_DIR = str(config.EMBED_CACHE_DIR)
IDENTITY_OPTIONS = [
    "恋人", "男朋友 / 女朋友", "老公 / 老婆", "爸爸 / 妈妈", "青梅竹马",
    "哥哥 / 妹妹", "姐姐 / 弟弟", "闺蜜 / 挚友", "知心好友", "守护者 / 保镖",
    "老师 / 前辈", "室友", "搭档 / 队友", "神秘旅伴", "虚拟主播 / 助手",
]
GENDER_OPTIONS = ["女", "男", "中性 / 无性别", "不设置"]

PRESET_PERSONAS = [
    {
        "name": "流萤",
        "source": "崩坏：星穹铁道",
        "relationship": "恋人",
        "gender": "女",
        "personality": "温柔、认真、略带害羞；平时轻声细语，但为了保护重要的人会展现出坚决果断的一面；向往普通、安稳的生活，珍惜和重要的人相处的每一刻。",
        "tone": "体贴细腻，偶尔害羞、话少；聊到星空、旅行、未来时会变得明亮；被保护时会有点逞强。",
        "appearance": "银白色短发，绿色眼睛，纤细少女身形；服装可变，以发色、瞳色与气质为主要辨识特征。",
        "catchphrases": "我想和你一起去看星星。；只要还能站在你身边，我就不会放弃。",
    },
    {
        "name": "雷电将军",
        "source": "原神",
        "relationship": "恋人",
        "gender": "女",
        "personality": "威严、克制、重承诺；表面冷峻，对珍视的人会展现温柔守护的一面；追求永恒，也开始理解变化与选择的意义。",
        "tone": "沉稳简洁，偶尔带一点居高临下的宠溺；对你说话时会放轻语气，但重要的事绝不敷衍。",
        "appearance": "紫色长发编成高束的辫子，紫色眼瞳，气质冷峻威严；服装可变，以发色、瞳色与气质为主要辨识特征。",
        "catchphrases": "",
    },
    {
        "name": "爱莉希雅",
        "source": "崩坏三",
        "relationship": "恋人",
        "gender": "女",
        "personality": "活泼、俏皮、自信，偶尔撒娇；对同伴温柔体贴，关键时刻可靠坚定。",
        "tone": "轻快活泼，带一点古灵精怪的撒娇感；认真时会变得温柔可靠。",
        "appearance": "粉色长发，粉色系眼瞳，灵动气质；服装可变，以发色、瞳色与气质为主要辨识特征。",
        "catchphrases": "",
    },
]


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _settings() -> dict:
    web_settings = get_web_tools_service().load_settings()
    return {
        "content_restriction": "1" if database.get_setting("content_restriction", "false") == "true" else "0",
        "medical_disabled": database.get_companion_setting("medical_disabled", "1"),
        "dependency_reminder": database.get_companion_setting("dependency_reminder", "1"),
        "minor_protection": database.get_companion_setting("minor_protection", "1"),
        "online_search_enabled": database.get_companion_setting("online_search_enabled", "0"),
        "search_provider": web_settings.provider,
        "model_provider": database.get_companion_setting("model_provider", "local"),
        "cloud_base_url": database.get_companion_setting("cloud_base_url", os.environ.get("COMPANION_CLOUD_BASE_URL", "")),
        "cloud_api_key": database.get_companion_setting("cloud_api_key", os.environ.get("COMPANION_CLOUD_API_KEY", "")),
        "cloud_model": database.get_companion_setting("cloud_model", os.environ.get("COMPANION_CLOUD_MODEL", "")),
    }


def _save_companion_image(data_url: str) -> str:
    """保存聊天上传的 base64 图片到本地，返回本地路径。"""
    match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", data_url.strip(), re.S)
    if not match:
        raise ValueError("图片格式不正确")
    mime = match.group(1).lower()
    ext_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
    }
    ext = ext_map.get(mime)
    if not ext:
        raise ValueError("不支持的图片格式")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except Exception as exc:
        raise ValueError("图片数据损坏") from exc
    if len(raw) > 15 * 1024 * 1024:
        raise ValueError("图片不能超过 15MB")
    COMPANION_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"companion_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    path = COMPANION_INPUT_DIR / filename
    path.write_bytes(raw)
    return str(path)


def _describe_companion_image(image_path: str) -> tuple[str, str]:
    """用本地视觉模型生成图片描述；失败时返回空描述与错误信息。"""
    try:
        result = prompt_agent.image_to_prompt(Path(image_path).read_bytes(), filename=Path(image_path).name)
        return str(result.get("description") or "").strip(), ""
    except Exception as exc:  # noqa: BLE001
        return "", str(exc)


def seed_presets() -> None:
    """启动时写入内置预设人设，已存在同名角色则跳过。"""
    existing = {item["name"]: item for item in database.list_companion_personas()}
    for preset in PRESET_PERSONAS:
        item = existing.get(preset["name"])
        if item is None:
            database.insert_companion_persona(preset)
        elif preset.get("appearance") and not str(item.get("appearance") or "").strip():
            database.update_companion_persona_appearance(item["id"], preset["appearance"])


def _embed(text: str) -> list[float]:
    if EMBED_CACHE["model"] is None:
        from fastembed import TextEmbedding

        EMBED_CACHE["model"] = TextEmbedding(model_name=EMBED_MODEL, cache_dir=EMBED_CACHE_DIR)
    vector = next(EMBED_CACHE["model"].embed([text]))
    return [float(value) for value in vector]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (norm_a * norm_b)


def _retrieve_memories(persona_id: int, query: str, top_k: int = 3) -> list[str]:
    memories = database.list_companion_memories(persona_id)
    if not memories:
        return []
    try:
        query_vector = _embed(query)
    except Exception:
        return [memory["content"] for memory in memories[:top_k]]
    scored = []
    for memory in memories:
        try:
            vector = json.loads(memory["embedding"] or "[]")
        except json.JSONDecodeError:
            vector = []
        scored.append((_cosine(query_vector, vector), memory["content"]))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [content for _, content in scored[:top_k]]


_DETAIL_HINTS = ("详细", "原文", "全文", "来源", "链接", "出处", "具体", "展开说说")


def _wants_details(message: str) -> bool:
    return any(hint in message for hint in _DETAIL_HINTS)


def _search_error_message(error: WebToolsError) -> str:
    if error.status_code == 401:
        return "搜索服务还没有配置有效的 Key，这次我先不查了。"
    if error.status_code == 402:
        return "搜索服务的余额不足，这次我先不查了。"
    if error.status_code == 429:
        return "搜索服务正在限流，稍后再问我一次吧。"
    if error.status_code and error.status_code >= 500:
        return "搜索服务暂时不可用，这次我先不查了。"
    return "这次搜索没有成功，我先不乱说。"


def _search_web(query: str, *, want_details: bool = False) -> tuple[list[dict], str]:
    service = get_web_tools_service()
    try:
        response = service.search(
            query,
            count=5,
            app="companion",
        )
        results = [
            {
                "title": item.title,
                "snippet": item.summary or item.snippet,
                "url": item.url,
                "date": item.date,
                "authority": item.authority,
                "rerank_score": item.rerank_score,
            }
            for item in response.results
        ]
        if want_details and results:
            pages = service.fetch_many(
                [item["url"] for item in results],
                app="companion",
            )
            by_url = {page.url: page for page in pages}
            for item in results:
                page = by_url.get(item["url"])
                if page:
                    item["content"] = page.content[:3000]
        return results, ""
    except WebToolsError as exc:
        return [], _search_error_message(exc)


def _detect_emotion(message: str) -> str:
    try:
        result = llm.chat(
            [
                {"role": "system", "content": "判断用户情绪，只输出一个词：开心/低落/焦虑/生气/平静。"},
                {"role": "user", "content": message},
            ],
            max_tokens=10,
            temperature=0,
            think=False,
        )
        text = result.strip()
        return text if text in ("开心", "低落", "焦虑", "生气", "平静") else "平静"
    except Exception:
        return "平静"


def _should_search(message: str) -> tuple[bool, str]:
    realtime_hints = (
        "天气", "气温", "降雨", "下雨", "汇率", "股价", "油价", "金价",
        "比分", "赛程", "航班", "新闻", "头条", "最新消息", "最新公告",
        "发布会", "刚刚发布",
    )
    if any(hint in message for hint in realtime_hints):
        return True, message[:120]
    try:
        result = llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "判断用户是否在询问实时、近期或会变化的事实，例如天气、价格、汇率、"
                        "比分、新闻、公告、活动时间、产品版本。普通闲聊、情感陪伴、"
                        "常识和创作不需要搜索。只输出 JSON："
                        '{"need_search":true/false,"query":"搜索词"}'
                    ),
                },
                {"role": "user", "content": message},
            ],
            max_tokens=80,
            temperature=0,
            think=False,
        )
        cleaned = result.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        data = json.loads(cleaned)
        return bool(data.get("need_search")), str(data.get("query") or message)[:120]
    except Exception:
        return False, ""


def _build_system_prompt(persona: dict, settings: dict, memories: list[str], search_context: str, current_time: str) -> str:
    rules = []
    if settings.get("medical_disabled") != "0":
        rules.append("不做医疗/心理诊断")
    if settings.get("dependency_reminder") == "1":
        rules.append("长期高频聊天时温和提醒现实社交")
    if settings.get("minor_protection") == "1":
        rules.append("识别到未成年人时调整边界")
    risk_rules = "；".join(rules) if rules else "无"
    catchphrases = persona.get("catchphrases") or ""
    gender = str(persona.get("gender") or "").strip()
    gender_line = f"性别：{gender}。" if gender else "角色性别未指定，不要主动假设或强调角色性别。"
    appearance = str(persona.get("appearance") or "").strip()
    appearance_line = f"外观特征：{appearance}。" if appearance else "外观特征未指定。"
    memory_text = "\n".join(f"- {item}" for item in memories) if memories else "暂无记忆"
    return (
        f"现在时间：{current_time}（被问到时间/日期时直接依据它回答，不要猜测）。\n"
        f"你是{persona['name']}，出自{persona.get('source') or '原创'}。\n"
        f"关系：{persona.get('relationship') or '恋人'}。\n"
        f"{gender_line}\n"
        f"{appearance_line}\n"
        f"性格：{persona.get('personality') or '温柔体贴'}。\n"
        f"语气：{persona.get('tone') or '温暖亲昵'}。\n"
        f"代表台词：{catchphrases}。\n"
        f"安全边界：{risk_rules}。\n"
        f"【长期记忆】\n{memory_text}\n"
        f"【联网搜索结果】\n{search_context if search_context else '无'}\n"
        "角色形象判断：用户可能发来你的游戏截图、二创图或形象图片。判断是否是你本人时，只比对外貌特征"
        "（发型、发色、瞳色、五官、体型、特殊特征），服装与画风不算；发型长短变化可以忽略。"
        "只有外貌明确匹配时才承认是本人；看起来像但不能确定时，就说“看起来和我有点像，但我不确定是不是我”；"
        "明确不匹配时不要承认。不要编造图片里没有的特征。\n"
        "代表台词仅作人设背景参考，不要主动重复；除非情境非常自然，避免在回复中出现或结尾引用同一句台词。\n"
        "请用上述人设与我自然聊天，语气温暖、口语化。\n"
        "联网搜索结果只作参考。涉及价格、日期、数字或实时事实时，优先采用权威度高的来源并附上 URL；"
        "来源互相冲突时明确指出冲突，不要自行挑一个看似合理的数字；没有足够来源就如实说无法确认。\n"
        "直接以人设身份回答，不要描述回复思路，不要使用“我会”“我应该”等句式，不要引用系统设定、长期记忆或联网搜索说明。"
    )


@router.get("/api/companion/personas")
def list_personas() -> dict:
    return {"items": database.list_companion_personas()}


@router.get("/api/companion/personas/{persona_id}")
def get_persona(persona_id: int) -> dict:
    persona = database.get_companion_persona(persona_id)
    if not persona:
        raise HTTPException(status_code=404, detail="人设不存在")
    return persona


@router.post("/api/companion/personas")
def create_persona(payload: dict = Body(...)) -> dict:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="人设名称不能为空")
    persona_id = database.insert_companion_persona(payload)
    return {"ok": True, "item": database.get_companion_persona(persona_id)}


@router.put("/api/companion/personas/{persona_id}")
def edit_persona(persona_id: int, payload: dict = Body(...)) -> dict:
    if not database.get_companion_persona(persona_id):
        raise HTTPException(status_code=404, detail="人设不存在")
    if not str(payload.get("name") or "").strip():
        raise HTTPException(status_code=400, detail="人设名称不能为空")
    database.update_companion_persona(persona_id, payload)
    return {"ok": True, "item": database.get_companion_persona(persona_id)}


@router.delete("/api/companion/personas/{persona_id}")
def remove_persona(persona_id: int) -> dict:
    if not database.get_companion_persona(persona_id):
        raise HTTPException(status_code=404, detail="人设不存在")
    database.delete_companion_persona(persona_id)
    return {"ok": True}


@router.post("/api/companion/personas/generate")
def generate_persona(payload: dict = Body(...)) -> dict:
    description = str(payload.get("description") or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description 不能为空")
    prompt = (
        "根据描述生成角色卡 JSON，只输出 JSON，不要输出解释。\n"
        "字段：name, source, gender, relationship, personality, tone, appearance, catchphrases(数组，代表台词/经典语录)。\n"
        "appearance 只填写可确认的外貌特征（发色、发型、瞳色、体型、特殊特征），不确定时留空。\n"
        "严格原则：只填写你有确切把握的字段；不确定或不知道的字段留空字符串或空数组；绝不编造台词、出处、性格或设定。\n"
        f"可选身份：{', '.join(IDENTITY_OPTIONS)}。\n"
        f"可选性别：{', '.join(GENDER_OPTIONS)}；不确定时输出空字符串。\n"
        f"描述：{description}\n"
        "判断规则：如果确定这个角色（例如来自知名作品且有把握），就正常填写；只有对整个角色完全不认识或没有任何把握时，"
        "才输出 {\"unknown\": true}，其余字段留空。不要因为谨慎就把认识的角色标成 unknown。"
    )
    try:
        result = llm.chat(
            [{"role": "system", "content": "你是角色卡生成助手，只输出 JSON。"}, {"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.1,
            think=False,
        )
        cleaned = result.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            cleaned = cleaned[start : end + 1]
        data = json.loads(cleaned)
        if data.get("unknown"):
            data["notice"] = "我对这个角色还不太熟悉，可以简单描述一下 ta 的性格或外貌吗？"
        return {"item": data}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成失败：{exc}") from exc


@router.get("/api/companion/sessions")
def list_sessions(persona_id: int) -> dict:
    return {"items": database.list_companion_sessions(persona_id)}


@router.post("/api/companion/sessions")
def create_session(payload: dict = Body(...)) -> dict:
    persona_id = int(payload.get("persona_id") or 0)
    if not database.get_companion_persona(persona_id):
        raise HTTPException(status_code=404, detail="人设不存在")
    session_id = database.create_companion_session(persona_id, str(payload.get("title") or "新会话"))
    return {"ok": True, "item": database.get_companion_session(session_id)}


@router.delete("/api/companion/sessions/{session_id}")
def remove_session(session_id: int) -> dict:
    if not database.get_companion_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    database.delete_companion_session(session_id)
    return {"ok": True}


@router.get("/api/companion/memories")
def list_memories(persona_id: int) -> dict:
    return {"items": database.list_companion_memories(persona_id)}


@router.get("/api/companion/messages")
def list_messages(session_id: int) -> list[dict]:
    if not database.get_companion_session(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    items = database.list_companion_messages(session_id)
    for item in items:
        if item.get("image_path"):
            item["image_url"] = f"/api/companion/images/{Path(item['image_path']).name}"
    return items


@router.get("/api/companion/images/{filename}")
def get_companion_image(filename: str) -> Response:
    """提供聊天图片访问（仅限 companion_inputs 目录内文件）。"""
    safe_name = Path(filename).name
    path = COMPANION_INPUT_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="image not found")
    return Response(path.read_bytes(), media_type="image/png")


@router.delete("/api/companion/memories/{memory_id}")
def remove_memory(memory_id: int) -> dict:
    database.delete_companion_memory(memory_id)
    return {"ok": True}


@router.post("/api/companion/summarize")
def summarize_messages(payload: dict = Body(...)) -> dict:
    persona_id = int(payload.get("persona_id") or 0)
    if not database.get_companion_persona(persona_id):
        raise HTTPException(status_code=404, detail="人设不存在")
    sessions = database.list_companion_sessions(persona_id)
    messages = []
    for session in sessions[:5]:
        messages.extend(database.list_companion_messages(session["id"], limit=100))
    messages = messages[-100:]
    if not messages:
        return {"ok": True, "memory_id": None}
    text = "\n".join(f"{m['role']}: {m['content']}" for m in messages[-50:])
    try:
        summary = llm.chat(
            [
                {"role": "system", "content": "把聊天记录压缩成 5 条以内简洁的中文长期记忆，只输出列表，不解释。"},
                {"role": "user", "content": text},
            ],
            max_tokens=500,
            temperature=0.3,
            think=False,
        )
    except Exception:
        summary = messages[-1]["content"]
    embedding = ""
    try:
        embedding = json.dumps(_embed(summary), ensure_ascii=False)
    except Exception:
        pass
    memory_id = database.insert_companion_memory(persona_id, summary.strip(), embedding=embedding, importance=1)
    return {"ok": True, "memory_id": memory_id}


@router.get("/api/companion/settings")
def get_settings() -> dict:
    return _settings()


@router.put("/api/companion/settings")
def put_settings(payload: dict = Body(...)) -> dict:
    if "content_restriction" in payload:
        database.set_setting("content_restriction", "true" if str(payload["content_restriction"]) == "1" else "false")
    for key in (
        "content_restriction",
        "medical_disabled",
        "dependency_reminder",
        "minor_protection",
        "online_search_enabled",
        "model_provider",
        "cloud_base_url",
        "cloud_api_key",
        "cloud_model",
    ):
        if key in payload:
            database.set_companion_setting(key, str(payload[key]))
    return _settings()


@router.post("/api/companion/test-cloud")
def test_cloud(payload: dict = Body(...)) -> dict:
    """测试云端模型连接与 API Key 是否可用。"""
    base_url = str(payload.get("base_url") or database.get_companion_setting("cloud_base_url", "")).strip()
    api_key = str(payload.get("api_key") or database.get_companion_setting("cloud_api_key", "")).strip()
    model = str(payload.get("model") or database.get_companion_setting("cloud_model", "")).strip()
    try:
        reply = llm.cloud_chat(
            [{"role": "user", "content": "请只回复：ok"}],
            base_url,
            api_key,
            model or "gpt-4o-mini",
            max_tokens=10,
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "reply": reply}


@router.post("/api/companion/chat")
def companion_chat(payload: dict = Body(...)):
    """SSE 流式聊天：情绪识别 → 记忆检索 → 可选联网搜索 → 流式回复。"""
    message = str(payload.get("message") or "").strip()
    image_base64 = str(payload.get("image_base64") or "").strip()
    session_id = int(payload.get("session_id") or 0)
    persona_id = int(payload.get("persona_id") or 0)
    if not message and not image_base64:
        return JSONResponse(status_code=400, content={"error": "message 或图片不能为空"})
    persona = database.get_companion_persona(persona_id)
    session = database.get_companion_session(session_id)
    if not persona or not session:
        return JSONResponse(status_code=404, content={"error": "人设或会话不存在"})

    running = task_state.running_tasks()
    if running:
        labels = "、".join(task["label"] for task in running)
        return JSONResponse(
            status_code=409,
            content={"error": f"有其他项目正在运行（{labels}），请稍后再进行", "tasks": running},
        )

    settings = _settings()
    if settings.get("content_restriction") == "1" and content_filter.is_nsfw(message):
        return JSONResponse(status_code=403, content={"error": "内容限制已开启，已阻止该请求"})

    image_path = ""
    image_description = ""
    if image_base64:
        try:
            image_path = _save_companion_image(image_base64)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        if not prompt_agent.is_available():
            return JSONResponse(status_code=503, content={"error": "Ollama 未运行，无法识别图片"})
        image_description, _describe_error = _describe_companion_image(image_path)
        if image_description:
            combined = f"{message} {image_description}".strip()
            if content_filter.is_always_blocked(combined):
                return JSONResponse(status_code=403, content={"error": "图片包含受限内容，已阻止该请求"})
            if settings.get("content_restriction") == "1" and content_filter.is_nsfw(combined):
                return JSONResponse(status_code=403, content={"error": "内容限制已开启，已阻止该图片请求"})
        elif settings.get("content_restriction") == "1":
            return JSONResponse(
                status_code=403,
                content={"error": "图片识别失败，可能包含受限内容；已阻止该请求"},
            )

    user_text = message or "[图片]"
    if image_description:
        model_user_content = f"{user_text}\n（用户发来图片，图片内容：{image_description}）"
    elif image_path:
        model_user_content = f"{user_text}\n（用户发来一张图片，但我这边暂时看不清内容，不要假装看到了）"
    else:
        model_user_content = user_text

    client_time_raw = str(payload.get("client_time") or "")
    try:
        current_time = datetime.fromisoformat(client_time_raw.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        current_time = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    use_cloud = (
        settings.get("model_provider") == "cloud"
        and settings.get("content_restriction") == "1"
        and bool(settings.get("cloud_api_key"))
    )

    def generate():
        emotion = _detect_emotion(user_text)
        memories = _retrieve_memories(persona_id, model_user_content)
        search_context = ""
        search_empty = False
        if settings.get("online_search_enabled") == "1":
            yield _sse({"kind": "searching", "delta": "正在检索…"})
            need_search, query = _should_search(message) if message else (False, "")
            if need_search:
                results, search_error = _search_web(query, want_details=_wants_details(message))
                if results:
                    search_context = "\n".join(
                        f"- {item['title']}｜日期 {item.get('date') or '未知'}"
                        f"｜权威度 {item.get('authority') if item.get('authority') is not None else '未知'}"
                        f"：{item['snippet']} ({item['url']})"
                        for item in results[:5]
                    )
                    fetched = [item for item in results if item.get("content")]
                    if fetched:
                        search_context += "\n【已抓取正文】\n" + "\n".join(
                            f"- {item['title']} ({item['url']})：{item['content']}"
                            for item in fetched[:2]
                        )
                elif search_error:
                    search_empty = True
                    yield _sse({"kind": "search_empty", "delta": search_error})
                else:
                    search_empty = True
                    yield _sse({"kind": "search_empty", "delta": "这次没有搜到相关内容，我不乱说，等你告诉我更多细节。"})
            else:
                yield _sse({"kind": "searching", "delta": ""})

        history = database.list_companion_messages(session_id, limit=20)
        messages = [
            {"role": "system", "content": _build_system_prompt(persona, settings, memories, search_context, current_time)},
        ]
        for item in history[-10:]:
            content = item["content"]
            if item.get("image_description"):
                content = f"{content}\n（用户曾发来图片，图片内容：{item['image_description']}）"
            messages.append({"role": item["role"], "content": content})
        messages.append({"role": "user", "content": model_user_content})

        full = ""
        stream_error = ""
        if use_cloud:
            try:
                for kind, delta in llm.cloud_stream_chat(
                    messages,
                    settings.get("cloud_base_url", ""),
                    settings.get("cloud_api_key", ""),
                    settings.get("cloud_model", "") or "gpt-4o-mini",
                ):
                    if kind != "answer":
                        continue
                    full += delta
                    yield _sse({"kind": kind, "delta": delta})
            except Exception as exc:  # noqa: BLE001
                full = ""
                stream_error = f"云端模型调用失败：{exc}"
                yield _sse({"kind": "error", "delta": stream_error})
        elif llm.is_available():
            try:
                for kind, delta in llm.stream_chat(messages):
                    if kind != "answer":
                        continue
                    full += delta
                    yield _sse({"kind": kind, "delta": delta})
            except Exception as exc:  # noqa: BLE001
                full = ""
                stream_error = f"模型调用失败：{exc}"
                yield _sse({"kind": "error", "delta": stream_error})
        if stream_error:
            database.insert_companion_message(
                session_id,
                persona_id,
                "user",
                user_text,
                emotion=emotion,
                image_path=image_path,
                image_description=image_description,
            )
            yield _sse({"kind": "done", "emotion": emotion, "search_empty": search_empty, "full": ""})
            return
        if not full.strip():
            full = "嗯嗯，我在听，你继续说好不好？"
            yield _sse({"kind": "answer", "delta": full})
        yield _sse(
            {
                "kind": "done",
                "emotion": emotion,
                "search_empty": search_empty,
                "full": full,
            }
        )
        database.insert_companion_message(
            session_id,
            persona_id,
            "user",
            user_text,
            emotion=emotion,
            image_path=image_path,
            image_description=image_description,
        )
        database.insert_companion_message(session_id, persona_id, "assistant", full)

    return StreamingResponse(generate(), media_type="text/event-stream")
