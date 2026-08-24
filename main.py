"""骑手招聘助手 AI 工作台：统一入口（Agent + 绘画）。"""
from __future__ import annotations

import argparse
import base64
import json
import socket
import sys
import threading
import time
import uuid
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from openpyxl import Workbook

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
AI_PRODUCT_DIR = ROOT / "AIproduct"
AI_PRODUCT_DIR.mkdir(parents=True, exist_ok=True)
for path in (str(ROOT / "rag_knowledge_base"), str(ROOT / "agent")):
    if path not in sys.path:
        sys.path.insert(0, path)

import llm  # noqa: E402
import database  # noqa: E402
import prompt_agent  # noqa: E402
import services  # noqa: E402
from agent import RecruitmentAgent  # noqa: E402
from comfy_worker import generate, list_loras  # noqa: E402
from retrieve import retrieve  # noqa: E402

database.init_db()

INDEX_HTML = (HERE / "static" / "index.html").read_text(encoding="utf-8")
FALLBACK_AGENT = RecruitmentAgent()
CHAT_SESSIONS: dict[str, list[dict]] = {}
LOCK = threading.Lock()

SYSTEM_PROMPT = (
    "你是一名外卖骑手招聘助手，负责在北京地区招聘外卖骑手。"
    "回答要自然、口语化，像真人招聘沟通一样，不要像机器人。"
    "思考过程尽量简短，快速给出答案。"
    "优先使用【知识库内容】里的信息回答；知识库没有的信息不要编造，可以引导候选人加微信细聊。"
    "回复控制在 200 字以内。"
)

_TRANSLATE_CACHE: dict[str, str] = {}


def translate_text(text: str) -> str:
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


def build_excel(kind: str, rows: list[dict]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = kind
    if rows:
        headers = list(rows[0].keys())
        worksheet.append(headers)
        for row in rows:
            worksheet.append([row.get(header, "") for header in headers])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def build_context(results: list[dict]) -> str:
    lines = []
    for index, item in enumerate(results[:4], 1):
        lines.append(f"[{index}] {item['title']}\n{item['content']}")
    return "\n\n".join(lines)


def chat_reply(message: str, session_id: str) -> tuple[str, str]:
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


class Handler(BaseHTTPRequestHandler):
    server_version = "RiderStudio/1.0"

    def _sse(self, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False)
        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _send(self, status: int, payload, content_type: str = "application/json; charset=utf-8") -> None:
        if isinstance(payload, (dict, list)):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        elif isinstance(payload, str):
            body = payload.encode("utf-8")
        else:
            body = payload
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, INDEX_HTML, "text/html; charset=utf-8")
        elif path == "/health":
            self._send(200, {"ok": True, "services": services.status(), "model": llm.MODEL})
        elif path == "/api/services":
            self._send(200, services.status())
        elif path == "/api/loras":
            self._send(200, {"loras": list_loras()})
        elif path == "/api/records":
            query = parse_qs(urlparse(self.path).query)
            kind = query.get("kind", ["agent"])[0]
            if kind not in database.available_kinds():
                self._send(404, {"error": "unknown kind"})
                return
            date_from = query.get("date_from", [""])[0] or None
            date_to = query.get("date_to", [""])[0] or None
            try:
                page = max(1, int(query.get("page", ["1"])[0]))
                page_size = int(query.get("page_size", ["10"])[0])
            except ValueError:
                self._send(400, {"error": "page 参数无效"})
                return
            self._send(200, database.query_records(kind, date_from, date_to, page, page_size))
            return
        elif path.startswith("/api/export/"):
            kind = path.split("/api/export/", 1)[1].split("/", 1)[0]
            if kind not in database.available_kinds():
                self._send(404, {"error": "unknown kind"})
                return
            query = parse_qs(urlparse(self.path).query)
            date_from = query.get("date_from", [""])[0] or None
            date_to = query.get("date_to", [""])[0] or None
            data = build_excel(kind, database.export_records(kind, date_from, date_to))
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", f'attachment; filename="{kind}_records.xlsx"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
            return
        elif path.startswith("/api/images/"):
            filename = path.split("/api/images/", 1)[1]
            safe_name = Path(filename).name
            file_path = AI_PRODUCT_DIR / safe_name
            if file_path.exists():
                self._send(200, file_path.read_bytes(), "image/png")
            else:
                self._send(404, {"error": "image not found"})
        else:
            self._send(404, {"error": "Not Found"})

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if path == "/api/chat/stream":
                message = str(payload.get("message") or "").strip()
                if not message:
                    self._send(400, {"error": "message 不能为空"})
                    return
                session_id = str(payload.get("session_id") or uuid.uuid4().hex)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                try:
                    with LOCK:
                        session = CHAT_SESSIONS.setdefault(session_id, [])
                        results = retrieve(message, top_k=4, mode="hybrid")
                        context = build_context(results)
                        messages = (
                            [{"role": "system", "content": SYSTEM_PROMPT}]
                            + session[-10:]
                            + [
                                {
                                    "role": "user",
                                    "content": f"【知识库内容】\n{context}\n\n【候选人问题】\n{message}",
                                }
                            ]
                        )
                    full = ""
                    source = "llm"
                    if llm.is_available():
                        try:
                            for kind, delta in llm.stream_chat(messages):
                                full += delta
                                self._sse({"kind": kind, "delta": delta})
                            if not full.strip():
                                raise RuntimeError("empty stream")
                        except Exception:
                            full = ""
                    if not full:
                        source = "fallback"
                        full, _ = FALLBACK_AGENT.respond(message, session_id=session_id)
                        self._sse({"kind": "answer", "delta": full})
                    self._sse({"kind": "done", "source": source, "session_id": session_id, "full": full})
                    with LOCK:
                        session.append({"role": "user", "content": message})
                        session.append({"role": "assistant", "content": full})
                        if len(session) > 20:
                            del session[: len(session) - 20]
                    top_score = max((item.get("score") or 0) for item in results) if results else None
                    database.insert_agent_message(session_id, "user", message)
                    database.insert_agent_message(session_id, "assistant", full, retrieval_score=top_score, source=source)
                except Exception as exc:  # noqa: BLE001
                    self._sse({"kind": "error", "error": str(exc)})
                return
            if path == "/api/chat":
                message = str(payload.get("message") or "").strip()
                if not message:
                    self._send(400, {"error": "message 不能为空"})
                    return
                session_id = str(payload.get("session_id") or uuid.uuid4().hex)
                reply, source = chat_reply(message, session_id)
                self._send(200, {"reply": reply, "source": source, "session_id": session_id})
                return
            if path == "/api/translate":
                text = str(payload.get("text") or "").strip()
                if not text or not llm.is_available():
                    self._send(200, {"translation": ""})
                    return
                self._send(200, {"translation": translate_text(text)})
                return
            if path == "/api/prompt/from-text":
                text = str(payload.get("text") or "").strip()
                if not text:
                    self._send(400, {"error": "text 不能为空"})
                    return
                if not prompt_agent.is_available():
                    self._send(503, {"error": "Ollama 未启动"})
                    return
                started_at = database.now_iso()
                started_ts = time.time()
                try:
                    prompt = prompt_agent.text_to_prompt(text)
                    database.insert_prompt_record(
                        "text", text, None, None, prompt, prompt_agent.TEXT_MODEL, "success",
                        started_at, database.now_iso(), round(time.time() - started_ts, 2),
                    )
                    self._send(200, {"prompt": prompt, "source_text": text})
                except Exception as exc:  # noqa: BLE001
                    database.insert_prompt_record(
                        "text", text, None, None, None, prompt_agent.TEXT_MODEL, "error",
                        started_at, database.now_iso(), round(time.time() - started_ts, 2),
                    )
                    raise
                return
            if path == "/api/prompt/from-image":
                data = str(payload.get("image_base64") or "")
                filename = str(payload.get("filename") or "image.png")
                if "," in data:
                    data = data.split(",", 1)[1]
                try:
                    image_bytes = base64.b64decode(data)
                except Exception as exc:  # noqa: BLE001
                    self._send(400, {"error": f"图片编码无效: {exc}"})
                    return
                if not image_bytes:
                    self._send(400, {"error": "图片为空"})
                    return
                if not prompt_agent.is_available():
                    self._send(503, {"error": "Ollama 未启动"})
                    return
                prompt_inputs = AI_PRODUCT_DIR / "prompt_inputs"
                prompt_inputs.mkdir(parents=True, exist_ok=True)
                safe_name = Path(filename).name
                saved_image = prompt_inputs / f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_name}"
                saved_image.write_bytes(image_bytes)
                started_at = database.now_iso()
                started_ts = time.time()
                try:
                    result = prompt_agent.image_to_prompt(image_bytes, filename)
                    database.insert_prompt_record(
                        "image", None, str(saved_image), result.get("description"),
                        result.get("prompt"), prompt_agent.VLM_MODEL, "success",
                        started_at, database.now_iso(), round(time.time() - started_ts, 2),
                    )
                    self._send(200, result)
                except Exception as exc:  # noqa: BLE001
                    database.insert_prompt_record(
                        "image", None, str(saved_image), None, None, prompt_agent.VLM_MODEL, "error",
                        started_at, database.now_iso(), round(time.time() - started_ts, 2),
                    )
                    raise
                return
            if path == "/api/services/start":
                ok, message = services.start(str(payload.get("name") or ""))
                self._send(200, {"ok": ok, "message": message, "services": services.status()})
                return
            if path == "/api/services/stop":
                ok, message = services.stop(str(payload.get("name") or ""))
                self._send(200, {"ok": ok, "message": message, "services": services.status()})
                return
            if path == "/api/draw":
                prompt = str(payload.get("prompt") or "").strip()
                if not prompt:
                    self._send(400, {"error": "prompt 不能为空"})
                    return
                negative_prompt = str(payload.get("negative_prompt") or "")
                width = int(payload.get("width", 1080))
                height = int(payload.get("height", 1920))
                steps = int(payload.get("steps", 18))
                cfg = float(payload.get("cfg", 1.0))
                loras = payload.get("loras") or []
                lora_turbo = any("anima-turbo" in str(name) for name in loras)
                lora_high = any("high-contrast" in str(name) for name in loras)
                record_id = database.insert_draw_start(
                    prompt,
                    translate_text(prompt),
                    negative_prompt,
                    translate_text(negative_prompt),
                    width,
                    height,
                    steps,
                    cfg,
                    lora_turbo,
                    lora_high,
                )
                started_ts = time.time()
                try:
                    result = generate(
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                        width=width,
                        height=height,
                        steps=steps,
                        cfg=cfg,
                        loras=loras,
                    )
                    database.finish_draw(
                        record_id,
                        round(time.time() - started_ts, 2),
                        result.get("saved_path"),
                        result.get("image_url"),
                        result.get("seed"),
                        "success",
                    )
                    self._send(200, result)
                except Exception as exc:  # noqa: BLE001
                    database.finish_draw(
                        record_id,
                        round(time.time() - started_ts, 2),
                        None,
                        None,
                        None,
                        "error",
                        str(exc),
                    )
                    raise
                return
            self._send(404, {"error": "Not Found"})
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": str(exc)})

    def log_message(self, format, *args):  # noqa: A002
        print(f"[{self.log_date_time_string()}] {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="骑手招聘助手 AI 工作台")
    parser.add_argument("--port", type=int, default=8500)
    args = parser.parse_args()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1)
        try:
            probe.connect(("127.0.0.1", args.port))
            print(f"端口 {args.port} 已被占用，工作台可能已在运行，请先停止旧实例。")
            sys.exit(1)
        except OSError:
            pass
    try:
        server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    except OSError:
        print(f"端口 {args.port} 已被占用，工作台可能已在运行，请先停止旧实例。")
        sys.exit(1)
    print(f"骑手招聘助手 AI 工作台: http://localhost:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
