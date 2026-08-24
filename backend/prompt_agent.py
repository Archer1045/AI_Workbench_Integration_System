"""图片反推与自然语言转绘画提示词。"""
from __future__ import annotations

import base64

import llm
import requests

OLLAMA_BASE = "http://127.0.0.1:11434"
VLM_MODEL = "qwen2.5vl:3b"
TEXT_MODEL = "qwen3:8b"


def is_available() -> bool:
    try:
        return requests.get(OLLAMA_BASE + "/api/tags", timeout=2).status_code == 200
    except Exception:
        return False


def image_to_prompt(image_bytes: bytes, filename: str = "image.png") -> dict:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    response = requests.post(
        OLLAMA_BASE + "/api/generate",
        json={
            "model": VLM_MODEL,
            "prompt": "请用中文详细描述这张图片的人物、服装、背景、画面构图、光线和整体风格。",
            "images": [encoded],
            "stream": False,
            "options": {"num_predict": 600},
        },
        timeout=180,
    )
    response.raise_for_status()
    description = response.json().get("response", "").strip()
    prompt = text_to_prompt(f"根据下面的图片描述生成英文 AI 绘画提示词：\n{description}")
    if not prompt:
        prompt = description
    return {"description": description, "prompt": prompt, "filename": filename}


def text_to_prompt(description: str) -> str:
    messages = [
        {
            "role": "system",
            "content": "你是 AI 绘画提示词生成器。根据用户描述生成英文 Danbooru 风格提示词，包含质量词、主体、服装、背景、镜头、光线等标签，用逗号分隔，只输出提示词。",
        },
        {"role": "user", "content": description},
    ]
    result = ""
    for _ in range(2):
        try:
            result = llm.chat(messages, temperature=0.7, max_tokens=800, timeout=120, think=False)
            if result.strip():
                break
        except Exception:
            result = ""
    return result.strip()
