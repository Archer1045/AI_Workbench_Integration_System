"""Manage Ollama and ComfyUI processes."""
from __future__ import annotations

import os
import subprocess
import threading
import time

import psutil
import requests

import config
import database

OLLAMA_EXE = str(config.OLLAMA_EXE)
OLLAMA_MODELS = str(config.OLLAMA_MODELS)
OLLAMA_URL = config.OLLAMA_BASE
OLLAMA_HOST = config.OLLAMA_HOST
OLLAMA_PORT = config.OLLAMA_PORT

COMFY_PY = str(config.COMFY_PY)
COMFY_DIR = str(config.COMFY_DIR)
COMFY_URL = config.COMFY_URL
COMFY_LOG = str(config.COMFY_LOG)
COMFY_HOST = config.COMFY_HOST
COMFY_PORT = config.COMFY_PORT

_procs: dict[str, subprocess.Popen | None] = {"ollama": None, "comfyui": None}
_consecutive: dict[str, int] = {"ollama": 0, "comfyui": 0}
_restarting: set[str] = set()
_supervisor_stop = threading.Event()


def gpu_status() -> dict:
    """返回 GPU 实时状态与当前驻留的 Ollama 模型。"""
    data = {
        "util": 0,
        "memory_used_mb": 0,
        "memory_total_mb": 0,
        "temperature_c": 0,
        "power_w": 0,
        "active_models": [],
    }
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = [part.strip() for part in result.stdout.strip().splitlines()[0].split(",")]
            if len(parts) >= 5:
                data.update(
                    {
                        "util": int(float(parts[0])),
                        "memory_used_mb": int(float(parts[1])),
                        "memory_total_mb": int(float(parts[2])),
                        "temperature_c": int(float(parts[3])),
                        "power_w": int(float(parts[4])),
                    }
                )
    except Exception:
        pass
    try:
        models = requests.get(OLLAMA_URL + "/api/ps", timeout=5).json().get("models", [])
        data["active_models"] = [
            {"name": str(model.get("name") or ""), "size_mb": round((model.get("size") or 0) / 1024 / 1024)}
            for model in models
        ]
    except Exception:
        pass
    return data


def _ollama_env() -> dict[str, str]:
    env = os.environ.copy()
    env["OLLAMA_MODELS"] = OLLAMA_MODELS
    env["OLLAMA_HOST"] = f"{OLLAMA_HOST}:{OLLAMA_PORT}"
    env["OLLAMA_MAX_LOADED_MODELS"] = "1"
    env["OLLAMA_KEEP_ALIVE"] = "2m"
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
    """清理占用配置端口但已卡死的 ComfyUI 进程。"""
    port_marker = f"--port {COMFY_PORT}"
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if "main.py" in cmdline and port_marker in cmdline:
                proc.kill()
        except Exception:
            continue


def _kill_ollama_runners() -> None:
    """清理 Ollama 的 llama-server 子进程，避免重启后残留孤儿占显存。"""
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if name == "llama-server.exe" or "llama-server" in cmdline.lower():
                proc.kill()
        except Exception:
            continue


def start_ollama() -> tuple[bool, str]:
    if is_ollama_up():
        return True, "already running"
    _kill_ollama_runners()
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
    _kill_ollama_runners()
    return True, "stopped"


def start_comfyui() -> tuple[bool, str]:
    if is_comfyui_up():
        return True, "already running"
    # 端口可能被卡死的旧进程占用，先清理再启动
    _kill_stale_comfyui()
    for _ in range(20):
        if not _is_port_open(COMFY_PORT):
            break
        time.sleep(0.5)
    log_file = open(COMFY_LOG, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [COMFY_PY, "main.py", "--listen", COMFY_HOST, "--port", str(COMFY_PORT)],
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


def supervision_settings() -> dict:
    """读取服务自启与健康探活配置。"""
    return {
        "auto_start": database.get_setting("service_auto_start", "false") == "true",
        "auto_restart": database.get_setting("service_auto_restart", "true") == "true",
        "interval_seconds": max(
            config.SETTINGS_HEALTH_INTERVAL_MIN,
            min(
                config.SETTINGS_HEALTH_INTERVAL_MAX,
                int(
                    database.get_setting(
                        "service_health_interval",
                        str(config.SETTINGS_HEALTH_INTERVAL_DEFAULT),
                    )
                    or config.SETTINGS_HEALTH_INTERVAL_DEFAULT
                ),
            ),
        ),
        "max_failures": max(
            config.SETTINGS_MAX_FAILURES_MIN,
            min(
                config.SETTINGS_MAX_FAILURES_MAX,
                int(
                    database.get_setting(
                        "service_max_failures",
                        str(config.SETTINGS_MAX_FAILURES_DEFAULT),
                    )
                    or config.SETTINGS_MAX_FAILURES_DEFAULT
                ),
            ),
        ),
    }


def update_supervision_settings(payload: dict) -> dict:
    """保存服务自启与健康探活配置。"""
    for key, db_key in (
        ("auto_start", "service_auto_start"),
        ("auto_restart", "service_auto_restart"),
        ("interval_seconds", "service_health_interval"),
        ("max_failures", "service_max_failures"),
    ):
        if key not in payload:
            continue
        if key in ("auto_start", "auto_restart"):
            database.set_setting(db_key, "true" if bool(payload[key]) else "false")
        else:
            try:
                if key == "interval_seconds":
                    value = max(
                        config.SETTINGS_HEALTH_INTERVAL_MIN,
                        min(config.SETTINGS_HEALTH_INTERVAL_MAX, int(payload[key])),
                    )
                else:
                    value = max(
                        config.SETTINGS_MAX_FAILURES_MIN,
                        min(config.SETTINGS_MAX_FAILURES_MAX, int(payload[key])),
                    )
            except (TypeError, ValueError):
                raise ValueError(f"{key} 必须是非负整数") from None
            database.set_setting(db_key, str(value))
    return supervision_settings()


def supervision_status() -> dict:
    """返回健康探活配置与当前连续失败次数。"""
    return {
        **supervision_settings(),
        "consecutive": dict(_consecutive),
        "restarting": {name: name in _restarting for name in ("ollama", "comfyui")},
    }


def _supervisor_once() -> None:
    settings = supervision_settings()
    if not settings["auto_restart"]:
        return
    busy = False
    try:
        from task_state import running_tasks

        busy = bool(running_tasks())
    except Exception:
        busy = False
    checks = (("ollama", is_ollama_up()), ("comfyui", is_comfyui_up()))
    for name, up in checks:
        if up:
            _consecutive[name] = 0
            continue
        _consecutive[name] = _consecutive.get(name, 0) + 1
        if busy or name in _restarting:
            continue
        if _consecutive[name] < settings["max_failures"]:
            continue
        _restarting.add(name)
        try:
            start(name)
        finally:
            _restarting.discard(name)


def service_supervisor_loop() -> None:
    """后台健康探活循环：连续失败达到阈值后自动重启服务。"""
    while not _supervisor_stop.is_set():
        try:
            _supervisor_once()
        except Exception:
            pass
        try:
            interval = supervision_settings()["interval_seconds"]
        except Exception:
            interval = config.SETTINGS_HEALTH_INTERVAL_DEFAULT
        _supervisor_stop.wait(interval)


def start_supervisor() -> None:
    """启动服务健康探活线程（幂等）。"""
    if any(thread.name == "service-supervisor" for thread in threading.enumerate()):
        return
    thread = threading.Thread(target=service_supervisor_loop, daemon=True, name="service-supervisor")
    thread.start()


def auto_start_services() -> None:
    """按配置在后台自动启动 Ollama 与 ComfyUI。"""
    if not supervision_settings()["auto_start"]:
        return
    for name in ("ollama", "comfyui"):
        threading.Thread(target=start, args=(name,), daemon=True, name=f"auto-start-{name}").start()


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
