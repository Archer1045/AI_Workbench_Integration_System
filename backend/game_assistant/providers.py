"""LLM providers that enforce JSON output for guide generation."""
from __future__ import annotations

import requests

import config


def local_json_chat(
    messages: list[dict[str, str]],
    *,
    base_url: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> str:
    if not base_url or not model:
        raise ValueError("Ollama provider is not configured")
    response = requests.post(
        base_url.rstrip("/") + "/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": "json",
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return ((response.json().get("message") or {}).get("content") or "").strip()


def openai_json_chat(
    messages: list[dict[str, str]],
    *,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    require_key: bool = True,
) -> str:
    if not base_url or not model or (require_key and not api_key):
        raise ValueError("OpenAI-compatible provider is not configured")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = requests.post(
        base_url.rstrip("/") + "/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return (data["choices"][0]["message"].get("content") or "").strip()


def deepseek_json_chat(
    messages: list[dict[str, str]],
    *,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> str:
    return openai_json_chat(
        messages,
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        require_key=True,
    )
