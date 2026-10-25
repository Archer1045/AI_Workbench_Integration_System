"""Ollama chat helper."""
from __future__ import annotations

import json

import requests

import config

OLLAMA_BASE = config.OLLAMA_BASE
MODEL = config.LOCAL_CHAT_MODEL


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
    model: str | None = None,
) -> str:
    use_model = model or MODEL
    if not think:
        response = requests.post(
            OLLAMA_BASE + "/api/chat",
            json={
                "model": use_model,
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
            "model": use_model,
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


def cloud_chat(
    messages: list[dict],
    base_url: str,
    api_key: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 800,
    timeout: int = 120,
) -> str:
    """调用 OpenAI 兼容的云端聊天接口（非流式）。"""
    if not base_url or not api_key or not model:
        raise ValueError("云端模型未配置（base_url/api_key/model 不能为空）")
    url = base_url.rstrip("/") + "/chat/completions"
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def cloud_stream_chat(
    messages: list[dict],
    base_url: str,
    api_key: str,
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 1200,
    timeout: int = 300,
):
    """调用 OpenAI 兼容的云端聊天接口（流式），逐段返回 answer。"""
    if not base_url or not api_key or not model:
        raise ValueError("云端模型未配置（base_url/api_key/model 不能为空）")
    url = base_url.rstrip("/") + "/chat/completions"
    response = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        },
        timeout=timeout,
        stream=True,
    )
    response.raise_for_status()
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            data = json.loads(payload)
        except Exception:
            continue
        choices = data.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        content = delta.get("content") or ""
        if content:
            yield "answer", content
