"""执行器的设备资源租约（模拟器 + 设备通道）回归测试。

口径：真跑期间必须占住 `game_assistant_run` 的两项独占资源；被别人占着就停手不硬闯；
资源系统出错时不阻塞（只记说明）；跑完（含异常/停手）一定释放。
"""
from __future__ import annotations

import pytest

import config
import database
import task_resources
from game_assistant import battle_plan as plan_mod
from game_assistant import battle_runner as runner_mod
from game_assistant import device_lease


def _init(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "lease.db")
    database.init_db()


def test_lease_acquires_blocks_others_and_releases(tmp_path, monkeypatch) -> None:
    _init(tmp_path, monkeypatch)
    first = device_lease.DeviceLease(job_id="run-1")
    assert first.acquire() is True
    assert first.acquired and "已认领资源" in first.note
    assert sorted(first.resources) == sorted(["emulator", "adb"])

    second = device_lease.DeviceLease(job_id="run-2")
    assert second.acquire() is False, "独占资源被占着时必须拒绝"
    assert second.note and not second.acquired

    first.release()
    assert task_resources.list_job_claims("run-1") == []
    assert second.acquire() is True
    second.release()


def test_lease_never_blocks_when_the_resource_system_errors(tmp_path, monkeypatch) -> None:
    _init(tmp_path, monkeypatch)

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(task_resources, "claim_resources", boom)
    lease = device_lease.DeviceLease(job_id="run-3")
    assert lease.acquire() is True, "资源系统出问题不该让执行器起不来"
    assert "出错" in lease.note
    lease.release()


def _runner(tmp_path, monkeypatch) -> runner_mod.BattleRunner:
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)

    class FakeLink:
        display = {"serial": "fake", "logical": 2, "sfid": "0"}

        def tap(self, *_args, **_kwargs):
            return {}

        def shot(self, *_args, **_kwargs):
            raise AssertionError("这条用例不该截图")

    return runner_mod.BattleRunner(FakeLink(), None, run_id="run-lease", log=lambda _: None)


def test_run_holds_the_lease_while_working_and_frees_it_afterwards(tmp_path, monkeypatch) -> None:
    _init(tmp_path, monkeypatch)
    runner = _runner(tmp_path, monkeypatch)
    seen: dict[str, int] = {}

    def fake_rounds(self, plan, start_at, stop_at):
        seen["claims_while_running"] = len(task_resources.list_job_claims(self.run_id))
        return []

    monkeypatch.setattr(runner_mod.BattleRunner, "_run_rounds", fake_rounds)
    plan = plan_mod.ExecutionPlan(quest_id="q", title="租约回归", team=[], actions=[])

    runner.run(plan)

    assert seen["claims_while_running"] == 2, "跑的时候必须占着模拟器 + 设备通道"
    assert task_resources.list_job_claims(runner.run_id) == [], "跑完必须释放"


def test_run_refuses_when_the_device_is_already_claimed(tmp_path, monkeypatch) -> None:
    _init(tmp_path, monkeypatch)
    task_resources.claim_resources("someone-else", "game_assistant_run",
                                   task_resources.for_kind("game_assistant_run"))
    runner = _runner(tmp_path, monkeypatch)
    monkeypatch.setattr(runner_mod.BattleRunner, "_run_rounds",
                        lambda self, plan, start_at, stop_at: [])
    plan = plan_mod.ExecutionPlan(quest_id="q", title="冲突回归", team=[], actions=[])

    with pytest.raises(runner_mod.ExecutionAbort, match="正被别的任务占着"):
        runner.run(plan)

    task_resources.release_resources("someone-else")
