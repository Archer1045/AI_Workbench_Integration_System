"""Manage Ollama and ComfyUI processes."""
from __future__ import annotations

import os
import subprocess
import time

import psutil
import requests

OLLAMA_EXE = r"D:\AI\Ollama\ollama.exe"
OLLAMA_MODELS = r"D:\AI\Ollama\models"
OLLAMA_URL = "http://127.0.0.1:11434"

COMFY_PY = r"D:\AI\ComfyUI\venv\Scripts\python.exe"
COMFY_DIR = r"D:\AI\ComfyUI"
COMFY_URL = "http://127.0.0.1:8188"
COMFY_LOG = r"D:\AI\ComfyUI\comfyui-service.log"

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
        return requests.get(COMFY_URL + "/system_stats", timeout=3).status_code == 200
    except Exception:
        return False


def _kill_stale_comfyui() -> None:
    """清理占用 8188 端口但已卡死的 ComfyUI 进程。"""
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if "main.py" in cmdline and "--port 8188" in cmdline:
                proc.kill()
        except Exception:
            continue


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
    # 端口可能被卡死的旧进程占用，先清理再启动
    _kill_stale_comfyui()
    for _ in range(20):
        if not _is_port_open(8188):
            break
        time.sleep(0.5)
    log_file = open(COMFY_LOG, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [COMFY_PY, "main.py", "--listen", "127.0.0.1", "--port", "8188"],
        cwd=COMFY_DIR,
        env=os.environ.copy(),
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=log_file,
        stderr=subprocess.STDOUT,
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
    _kill_stale_comfyui()
    return True, "stopped"


def _is_port_open(port: int) -> bool:
    """检查本地端口是否有监听。"""
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port and conn.status == "LISTEN":
                return True
    except Exception:
        pass
    return False


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
