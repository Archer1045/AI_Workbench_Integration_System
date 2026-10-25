"""跑真机期间认领「模拟器 / 设备通道」资源租约。

为什么要它：执行器会独占模拟器（点屏幕、截图），而工作台里别的任务（绘图、VLM、视频）
也可能要用资源。资源系统里**已经**为这件事预留了任务类型 `game_assistant_run`
（= 模拟器 + 设备通道，两者都是 exclusive），本模块只是按它的口径认领 / 续租 / 释放。

口径：
  * 认领失败（别人正占着）⇒ 由调用方**直接停手**，把冲突信息带给用户，不硬闯；
  * 租约 TTL 120 秒 ⇒ 跑的时候开一个守护线程按 30 秒续租；
  * 进程退出（正常 / 异常 / 被停）都释放，避免留下"僵尸租约"；
  * 资源系统不可用（例如脱离后端单独跑 CLI、表还没迁移）⇒ **不阻塞**，只记一句说明。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

LEASE_KIND = "game_assistant_run"
HEARTBEAT_SECONDS = 30.0


@dataclass
class DeviceLease:
    """一次运行的资源租约（模拟器 + 设备通道）。"""

    job_id: str
    acquired: bool = False
    note: str = ""
    resources: list[str] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    def acquire(self) -> bool:
        """尝试认领。返回 False 表示资源被占用（调用方应当停手）。"""
        try:
            import task_resources
        except Exception as exc:  # 资源系统不在：不阻塞，只说明
            self.note = f"资源系统不可用（{exc}）：这次没有认领模拟器租约"
            return True
        try:
            resources = task_resources.for_kind(LEASE_KIND)
            self.resources = [str(item.get("key")) for item in resources]
            task_resources.claim_resources(self.job_id, LEASE_KIND, resources)
        except task_resources.ResourceConflictError as exc:
            self.note = task_resources.conflict_message(exc)
            return False
        except Exception as exc:
            self.note = f"认领租约时出错（{exc}）：这次没有认领模拟器租约"
            return True
        self.acquired = True
        self.note = "已认领资源：" + "、".join(self.resources)
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._thread.start()
        return True

    def _heartbeat(self) -> None:
        import task_resources

        while not self._stop.wait(HEARTBEAT_SECONDS):
            try:
                task_resources.renew_resources(self.job_id)
            except Exception:
                # 续租失败不在这里炸：真丢了租约，下一个任务会拿到冲突提示。
                pass

    def release(self) -> None:
        self._stop.set()
        if not self.acquired:
            return
        try:
            import task_resources

            task_resources.release_resources(self.job_id, reason="game_run_finished")
        except Exception:
            pass
        self.acquired = False
