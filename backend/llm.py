"""Ollama chat helper."""
from __future__ import annotations

import json

import requests

OLLAMA_BASE = "http://127.0.0.1:11434"
MODEL = "qwen3:8b"


def is_available() -> bool:
    try:
        return requests.get(OLLAMA_BASE, timeout=2).status_code == 200
    except Exception:
        return False


def chat(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 800,
    timeout: int = 120,
    think: bool = True,
) -> str:
    if not think:
        response = requests.post(
            OLLAMA_BASE + "/api/chat",
            json={
                "model": MODEL,
                "messages": messages,
                "stream": False,
                "think": False,
                "options": {"num_predict": max_tokens, "temperature": temperature},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return (response.json().get("message") or {}).get("content", "")
    response = requests.post(
        OLLAMA_BASE + "/v1/chat/completions",
        json={
            "model": MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def stream_chat(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 1200,
    timeout: int = 300,
):
    response = requests.post(
        OLLAMA_BASE + "/api/chat",
        json={
            "model": MODEL,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "options": {"num_predict": max_tokens},
        },
        timeout=timeout,
        stream=True,
    )
    response.raise_for_status()
    for line in response.iter_lines(decode_unicode=True):
        if not line:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        message = data.get("message", {})
        reasoning = message.get("reasoning_content") or message.get("thinking") or ""
        content = message.get("content") or ""
        if reasoning:
            yield "thinking", reasoning
        if content:
            yield "answer", content
        if data.get("done"):
            break
