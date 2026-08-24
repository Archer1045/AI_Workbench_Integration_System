"""Manage Ollama and ComfyUI processes."""
from __future__ import annotations

import os
import subprocess
import time

import requests

OLLAMA_EXE = r"D:\AI\Ollama\ollama.exe"
OLLAMA_MODELS = r"D:\AI\Ollama\models"
OLLAMA_URL = "http://127.0.0.1:11434"

COMFY_PY = r"D:\AI\ComfyUI\venv\Scripts\python.exe"
COMFY_DIR = r"D:\AI\ComfyUI"
COMFY_URL = "http://127.0.0.1:8188"

_procs: dict[str, subprocess.Popen | None] = {"ollama": None, "comfyui": None}


def _ollama_env() -> dict[str, str]:
    env = os.environ.copy()
    env["OLLAMA_MODELS"] = OLLAMA_MODELS
    env["OLLAMA_HOST"] = "127.0.0.1:11434"
    return env


def is_ollama_up() -> bool:
    try:
        return requests.get(OLLAMA_URL, timeout=2).status_code == 200
    except Exception:
        return False


def is_comfyui_up() -> bool:
    try:
        return requests.get(COMFY_URL + "/system_stats", timeout=2).status_code == 200
    except Exception:
        return False


def start_ollama() -> tuple[bool, str]:
    if is_ollama_up():
        return True, "already running"
    proc = subprocess.Popen(
        [OLLAMA_EXE, "serve"],
        env=_ollama_env(),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    _procs["ollama"] = proc
    for _ in range(40):
        if is_ollama_up():
            return True, "started"
        time.sleep(0.5)
    return False, "start timeout"


def stop_ollama() -> tuple[bool, str]:
    proc = _procs.get("ollama")
    if proc is not None:
        proc.terminate()
        _procs["ollama"] = None
    return True, "stopped"


def start_comfyui() -> tuple[bool, str]:
    if is_comfyui_up():
        return True, "already running"
    proc = subprocess.Popen(
        [COMFY_PY, "main.py", "--listen", "127.0.0.1", "--port", "8188"],
        cwd=COMFY_DIR,
        env=os.environ.copy(),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    _procs["comfyui"] = proc
    for _ in range(150):
        if is_comfyui_up():
            return True, "started"
        time.sleep(1)
    return False, "start timeout"


def stop_comfyui() -> tuple[bool, str]:
    proc = _procs.get("comfyui")
    if proc is not None:
        proc.terminate()
        _procs["comfyui"] = None
    return True, "stopped"


def status() -> dict:
    return {
        "ollama": is_ollama_up(),
        "comfyui": is_comfyui_up(),
    }


def start(name: str) -> tuple[bool, str]:
    if name == "ollama":
        return start_ollama()
    if name == "comfyui":
        return start_comfyui()
    return False, "unknown service"


def stop(name: str) -> tuple[bool, str]:
    if name == "ollama":
        return stop_ollama()
    if name == "comfyui":
        return stop_comfyui()
    return False, "unknown service"
