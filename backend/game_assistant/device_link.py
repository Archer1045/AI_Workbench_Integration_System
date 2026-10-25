"""与 FGO-py 常驻设备驱动（fgoAgent.py）的通信链路。

**本文件不驱动设备**：它只负责启动/停止 FGO-py 进程、按 JSON 协议收发命令。
所有截图与点击原语都在 FGO-py 侧（`_research/fgo-py/FGO-py/fgoAgent.py`），
这样执行层仍然是 FGO-py（decisions.md 的绑定规则），后端不新增控制层。

协议：每行一个 JSON。启动后第一行是握手（{"ready": true, "display": {...}}）。
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import config


# 设备序列号的兜底解析**不放在这个文件里**：护栏测试 test_project_guardrails.py 禁止
# 工作区代码出现设备调试通道 / 输入 / 截图驱动的字样（控制原语只允许存在于 FGO-py 侧，
# 连注释里的关键词都会被它拦下）。序列号优先级与"配置值不在线时退到当前唯一设备"的
# 逻辑放在 `fgoAgent.py` 里做。


class DeviceLinkError(RuntimeError):
    pass


class DeviceLink:
    """一次启动、多轮请求；`with` 语句结束时自动收掉子进程。"""

    def __init__(
        self,
        python: Path | str | None = None,
        script: str | None = None,
        workdir: Path | str | None = None,
        device: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.python = Path(python or config.FGO_PY_PYTHON)
        self.workdir = Path(workdir or config.FGO_PY_DIR)
        self.script = str(script or config.FGO_PY_AGENT)
        self.device = str(device or config.FGO_PY_DEVICE)
        self.timeout = timeout
        self.process: subprocess.Popen[str] | None = None
        self.handshake: dict[str, Any] = {}
        self._seq = 0

    # ---------- 生命周期 ----------

    def start(self) -> dict[str, Any]:
        if self.process is not None:
            return self.handshake
        if not self.python.exists():
            raise DeviceLinkError(f"找不到 FGO-py 解释器：{self.python}")
        script_path = self.workdir / self.script
        if not script_path.exists():
            raise DeviceLinkError(f"找不到驱动脚本：{script_path}")
        self.process = subprocess.Popen(
            [str(self.python), self.script, self.device],
            cwd=str(self.workdir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        handshake = self._read_line()
        if not handshake.get("ok"):
            self.close()
            raise DeviceLinkError(f"FGO-py 驱动启动失败：{handshake.get('error')}")
        if not handshake.get("ready"):
            # 首行不是握手（例如更早的进程残留输出），再读一行
            handshake = self._read_line()
        self.handshake = handshake
        return handshake

    def close(self) -> None:
        if self.process is None:
            return
        try:
            self.request(cmd="quit", timeout=5.0)
        except Exception:
            pass
        try:
            self.process.wait(timeout=5)
        except Exception:
            self.process.kill()
        self.process = None

    def __enter__(self) -> "DeviceLink":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ---------- 请求 ----------

    def _read_line(self) -> dict[str, Any]:
        assert self.process is not None and self.process.stdout is not None
        line = self.process.stdout.readline()
        if not line:
            stderr = ""
            if self.process.stderr is not None:
                try:
                    stderr = self.process.stderr.read()[-400:]
                except Exception:
                    stderr = "(stderr 读不到)"
            raise DeviceLinkError(f"驱动没有响应（进程退出？）stderr={stderr}")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise DeviceLinkError(f"驱动返回的不是 JSON：{line[:200]!r}") from exc

    def request(self, timeout: float | None = None, **payload: Any) -> dict[str, Any]:
        if self.process is None or self.process.stdin is None:
            raise DeviceLinkError("驱动未启动（先调用 start()）")
        self._seq += 1
        payload["id"] = self._seq
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        started = time.perf_counter()
        line = self._read_line()
        line.setdefault("elapsed_s", round(time.perf_counter() - started, 3))
        if not line.get("ok"):
            raise DeviceLinkError(f"驱动执行 {payload.get('cmd')} 失败：{line.get('error')}")
        return line

    # ---------- 便捷封装 ----------

    def shot(
        self,
        path: Path | str,
        settle: float = 0.0,
        attempts: int = 3,
        retry_wait: float = 0.8,
    ) -> dict[str, Any]:
        """截图。过场 / 黑帧上 FGO-py 偶发取不到画面（实测 2026-10-13：回合切换的
        那一刻报 `'NoneType' object is not subscriptable`），所以这里自己重试几次；
        连续失败才把错误抛出去，由调用方决定停不停。"""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        last: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                return self.request(cmd="shot", path=str(path), settle=settle)
            except DeviceLinkError as exc:
                last = exc
                if attempt < attempts:
                    time.sleep(retry_wait)
        assert last is not None
        raise last

    def tap(self, x: float, y: float, settle: float = 0.0) -> dict[str, Any]:
        return self.request(cmd="tap", x=float(x), y=float(y), settle=settle)

    def swipe(self, x1: float, y1: float, x2: float, y2: float, settle: float = 0.0) -> dict[str, Any]:
        """滑动（用于翻列表这类手势）。起点/终点由调用方按画面几何给出，不写死。"""
        return self.request(cmd="swipe", x1=float(x1), y1=float(y1), x2=float(x2), y2=float(y2),
                            settle=settle)

    def probe_display(self) -> dict[str, Any]:
        return self.request(cmd="probe_display")

    @property
    def display(self) -> dict[str, Any]:
        return dict(self.handshake.get("display") or {})
