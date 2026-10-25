"""执行器 HTTP 入口（run / stop / status / options）的回归测试。

不真的起进程、不碰设备：`Popen` 被换成假的，只验"该不该放行、参数对不对、进度读得对不对"。
"""
from __future__ import annotations

import json

import pytest

import config
from game_assistant import execution_router as api

BASE = "/api/game-assistant/fgo/execution"


class FakeProcess:
    def __init__(self) -> None:
        self.pid = 4242
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self.command: list[str] = []

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


@pytest.fixture()
def execution_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    for name in ("runbooks", "layouts", "runs", "templates/buttons", "templates/support"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "runbooks" / "spec.json").write_text("{}", encoding="utf-8")
    (tmp_path / "layouts" / "layout.json").write_text("{}", encoding="utf-8")
    api._STATE.process = None
    api._STATE.run_id = ""
    api._STATE.exit_code = None
    api._STATE.stop_requested = False
    return tmp_path


def _spawn_spy(monkeypatch) -> list[FakeProcess]:
    spawned: list[FakeProcess] = []

    def fake_popen(command, **kwargs):
        process = FakeProcess()
        process.command = list(command)
        process.kwargs = dict(kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(api.subprocess, "Popen", fake_popen)
    return spawned


VALID_DRAFT = {
    "name": "test_draft.json",
    "quest_id": "fgo-cn-daily-treasure-door-extreme",
    "title": "测试用 runbook",
    "source": "单测",
    "team": [
        {"name": "莫德雷德(Rider)", "class_name": "Rider"},
        {"name": "阿尔托莉雅·卡斯特(Berserker)", "class_name": "Berserker"},
        {"name": "阿尔托莉雅·卡斯特(Caster)", "class_name": "Caster"},
    ],
    "steps": [
        {"turn": 1, "actor": "莫德雷德(Rider)", "kind": "skill", "skill_slot": 1,
         "target": "莫德雷德(Rider)"},
        {"turn": 1, "actor": "莫德雷德(Rider)", "kind": "np"},
        {"turn": 1, "actor": "莫德雷德(Rider)", "kind": "card", "card": "any", "position": "leftmost"},
        {"turn": 1, "actor": "莫德雷德(Rider)", "kind": "card", "card": "any", "position": "leftmost"},
    ],
    "support": {"servant": "阿尔托莉雅·卡斯特(Caster)", "ce_names": ["贝拉丽莎"]},
}


def test_create_runbook_saves_after_compile_check(client, execution_env) -> None:
    """表单提交的「队伍 + 每回合操作 + 助战规则」先过编译期校验，再落盘成 runbook。"""
    response = client.post(f"{BASE}/runbooks", json=VALID_DRAFT)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["name"] == "test_draft.json" and payload["actions"] >= 4

    saved = execution_env / "runbooks" / "test_draft.json"
    assert saved.exists()
    written = json.loads(saved.read_text(encoding="utf-8"))
    assert written["support"]["ce_names"] == ["贝拉丽莎"]
    assert [slot["name"] for slot in written["team"]][0] == "莫德雷德(Rider)"


def test_create_runbook_rejects_broken_plan_and_bad_name(client, execution_env) -> None:
    """每回合必须 3 个出手位、文件名不许带路径 —— 校验不过就 400，一个字节都不写。"""
    broken = json.loads(json.dumps(VALID_DRAFT))
    broken["steps"] = broken["steps"][:-1]          # 只剩 2 个出手位
    response = client.post(f"{BASE}/runbooks", json=broken)
    assert response.status_code == 400, response.text
    assert "编译不过" in response.json()["detail"]
    assert not (execution_env / "runbooks" / "test_draft.json").exists()

    bad_name = json.loads(json.dumps(VALID_DRAFT))
    bad_name["name"] = "../evil.json"
    assert client.post(f"{BASE}/runbooks", json=bad_name).status_code == 400


def test_create_runbook_keeps_the_dps_and_defaults_support_targets(client, execution_env) -> None:
    """表单能提交「打手位」：落盘的 spec 里保留 `dps`，辅助技能不写 target 也能编译过。

    用户口径 2026-10-16：辅助技能默认给打手，但**要通知**（通知在计划摘要的 ⚠ 里）。
    """
    draft = {
        "name": "grand_test.json",
        "quest_id": "fgo-cn-2026-grand-assassin",
        "title": "冠位战（表单生成）",
        "source": "界面表单",
        "notes": [],
        "dps": "“山中老人”",
        "team": [
            {"name": "“山中老人”", "class_name": "Assassin"},
            {"name": "光之高扬斯卡娅", "class_name": "Assassin"},
        ],
        "steps": [
            # 辅助技能**故意不写 target**，靠 dps 默认
            {"turn": 1, "actor_slot": 2, "kind": "skill", "skill_slot": 2},
            {"turn": 1, "actor_slot": 1, "kind": "np"},
            {"turn": 1, "actor_slot": 1, "kind": "card", "card": "any", "position": "leftmost"},
            {"turn": 1, "actor_slot": 1, "kind": "card", "card": "any", "position": "leftmost"},
        ],
    }

    response = client.post(f"{BASE}/runbooks", json=draft)

    assert response.status_code == 200, response.text
    saved = json.loads((execution_env / "runbooks" / "grand_test.json").read_text(encoding="utf-8"))
    assert saved["dps"] == "“山中老人”"
    # 摘要里要带"默认指向打手"的通知（用户要求"默认可以这样、但必须告诉我"）
    assert "默认指向" in response.json()["summary"], response.json()["summary"]


def test_support_library_lists_registered_names(client, execution_env) -> None:
    servant_dir = execution_env / "templates" / "support" / "servant"
    ce_dir = execution_env / "templates" / "support" / "ce"
    servant_dir.mkdir(parents=True, exist_ok=True)
    ce_dir.mkdir(parents=True, exist_ok=True)
    (servant_dir / "a.json").write_text(
        json.dumps({"name": "阿尔托莉雅·卡斯特(Caster)"}, ensure_ascii=False), encoding="utf-8")
    (ce_dir / "b.json").write_text(json.dumps({"name": "贝拉丽莎"}, ensure_ascii=False), encoding="utf-8")

    payload = client.get(f"{BASE}/support-library").json()

    assert payload["servant"] == ["阿尔托莉雅·卡斯特(Caster)"]
    assert payload["ce"] == ["贝拉丽莎"]


REGISTER_REPORT_LINE = (
    'REGISTER_REPORT {"ok": true, "row": 2, "rows_seen": 3, "saved": '
    '[{"kind": "ce", "name": "贝拉丽莎", "meta": "贝拉丽莎.json", "source_row": 2}], '
    '"discrimination": {"礼装 贝拉丽莎": {"2": 1.0, "1": 0.24}}}\n'
)


def _stub_executor_run(monkeypatch, returncode: int, stdout: str) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    class Finished:
        pass

    finished = Finished()
    finished.returncode = returncode
    finished.stdout = stdout.encode("utf-8")

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        captured["env"] = dict(kwargs.get("env") or {})
        return finished

    monkeypatch.setattr(api.subprocess, "run", fake_run)
    return captured


def test_register_support_runs_the_executor_without_execute(client, execution_env, monkeypatch) -> None:
    """登记 = 起执行器的登记模式：只截图 + 存指纹，**绝不能带 --execute**。"""
    captured = _stub_executor_run(monkeypatch, 0, "登记模式：只截图 + 存指纹\n" + REGISTER_REPORT_LINE)

    response = client.post(
        f"{BASE}/support/register",
        json={
            "row": 2,
            "servant": "阿尔托莉雅·卡斯特(Caster)",
            "ce": ["贝拉丽莎", "蒙娜丽莎:1", "  "],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["report"]["rows_seen"] == 3
    assert payload["report"]["saved"][0]["name"] == "贝拉丽莎"
    assert payload["run_id"].startswith("register-")

    command = captured["command"]
    assert "game_assistant.battle_runner" in command
    assert "--register-support" in command
    assert "--execute" not in command, "登记绝不能真的执行"
    assert command[command.index("--support-row") + 1] == "2"
    assert command[command.index("--servant") + 1] == "阿尔托莉雅·卡斯特(Caster)"
    assert [command[i + 1] for i, item in enumerate(command) if item == "--ce"] == [
        "贝拉丽莎", "蒙娜丽莎:1",
    ]
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"


def test_register_support_rejects_empty_or_illegal_names(client, execution_env, monkeypatch) -> None:
    spawned = _spawn_spy(monkeypatch)

    assert client.post(f"{BASE}/support/register", json={"row": 1}).status_code == 400
    for bad in ("../evil", "从者:名字", "a/b"):
        response = client.post(f"{BASE}/support/register", json={"row": 1, "servant": bad})
        assert response.status_code == 400, response.text
    # 礼装项的「名字:行号」是合法写法，但名字本身仍然不许带路径
    assert client.post(
        f"{BASE}/support/register", json={"row": 1, "ce": ["../evil:2"]}
    ).status_code == 400
    assert spawned == [], "参数不合法时一个进程都不许起"


def test_register_support_is_blocked_while_a_run_is_active(client, execution_env, monkeypatch) -> None:
    """设备被正在跑的运行占着 ⇒ 409（不能插进去截图）。"""
    _spawn_spy(monkeypatch)
    started = client.post(
        f"{BASE}/run", json={"spec": "spec.json", "layout": "layout.json", "confirm_ap": True}
    )
    assert started.status_code == 200

    blocked = client.post(f"{BASE}/support/register", json={"row": 1, "servant": "C呆"})

    assert blocked.status_code == 409
    assert "已经有运行在跑" in blocked.json()["detail"]


def test_register_support_reports_a_fail_stop_without_a_report_line(client, execution_env, monkeypatch) -> None:
    """屏不对时执行器不带报告行退出 ⇒ ok=False，把它的输出尾巴回给界面看原因。"""
    _stub_executor_run(monkeypatch, 4, "已按判据停下：当前画面不是「助战选择」屏\n")

    payload = client.post(f"{BASE}/support/register", json={"row": 1, "servant": "C呆"}).json()

    assert payload["ok"] is False and payload["exit_code"] == 4 and payload["report"] is None
    assert any("不是「助战选择」屏" in line for line in payload["output_tail"])


def test_check_runbook_runs_the_executor_without_execute(client, execution_env, monkeypatch) -> None:
    """自检 = 用「不执行」模式跑一遍执行器：不点任何东西、不花 AP，只把报告回给界面。"""
    captured: dict[str, Any] = {}

    class Finished:
        returncode = 0
        stdout = "scene: battle_main\nready: True\n".encode("utf-8")

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        captured["env"] = dict(kwargs.get("env") or {})
        return Finished()

    monkeypatch.setattr(api.subprocess, "run", fake_run)
    response = client.post(f"{BASE}/runbooks/spec.json/check?enter_quest=true")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True and payload["exit_code"] == 0
    assert payload["output_tail"][-1] == "ready: True"
    command = captured["command"]
    assert "--execute" not in command, "自检绝不能真的执行"
    assert "--enter-quest" in command
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"


def test_run_requires_explicit_ap_confirmation(client, execution_env, monkeypatch) -> None:
    spawned = _spawn_spy(monkeypatch)
    response = client.post(f"{BASE}/run", json={"spec": "spec.json", "layout": "layout.json"})
    assert response.status_code == 400
    assert "confirm_ap" in response.json()["detail"]
    assert spawned == []


@pytest.mark.parametrize("spec", ["../spec.json", "nope.json", "sub/spec.json"])
def test_run_rejects_bad_spec_paths(client, execution_env, monkeypatch, spec) -> None:
    spawned = _spawn_spy(monkeypatch)
    response = client.post(
        f"{BASE}/run",
        json={"spec": spec, "layout": "layout.json", "confirm_ap": True},
    )
    assert response.status_code == 400
    assert spawned == []


def test_run_starts_the_executor_with_the_expected_flags(client, execution_env, monkeypatch) -> None:
    spawned = _spawn_spy(monkeypatch)
    response = client.post(
        f"{BASE}/run",
        json={
            "spec": "spec.json", "layout": "layout.json", "rounds": 2,
            "enter_quest": True, "support_row": 1, "confirm_ap": True,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rounds"] == 2 and payload["enter_quest"] is True
    assert len(spawned) == 1
    command = spawned[0].command
    assert "game_assistant.battle_runner" in command
    for flag, value in (("--execute", None), ("--rounds", "2"), ("--enter-quest", None),
                        ("--support-row", "1"), ("--run-id", payload["run_id"])):
        if value is None:
            assert flag in command
        else:
            assert command[command.index(flag) + 1] == value


def test_second_run_while_active_is_rejected(client, execution_env, monkeypatch) -> None:
    _spawn_spy(monkeypatch)
    body = {"spec": "spec.json", "layout": "layout.json", "confirm_ap": True}
    assert client.post(f"{BASE}/run", json=body).status_code == 200
    second = client.post(f"{BASE}/run", json=body)
    assert second.status_code == 409
    assert "已经有运行在跑" in second.json()["detail"]


def test_stop_terminates_the_executor(client, execution_env, monkeypatch) -> None:
    spawned = _spawn_spy(monkeypatch)
    body = {"spec": "spec.json", "layout": "layout.json", "confirm_ap": True}
    client.post(f"{BASE}/run", json=body)
    stopped = client.post(f"{BASE}/stop")
    assert stopped.status_code == 200
    assert stopped.json()["stopped"] is True
    assert spawned[0].terminated is True
    again = client.post(f"{BASE}/stop")
    assert again.json()["stopped"] is False


def test_stop_releases_the_run_lease(client, execution_env, monkeypatch) -> None:
    """停止后立刻重开不能被自己的旧租约挡住（2026-10-19 资源冲突回归）。"""
    import task_resources

    _spawn_spy(monkeypatch)
    body = {"spec": "spec.json", "layout": "layout.json", "confirm_ap": True}
    started = client.post(f"{BASE}/run", json=body).json()
    run_id = started["run_id"]
    task_resources.claim_resources(
        run_id, "game_assistant_run", task_resources.for_kind("game_assistant_run")
    )
    assert task_resources.list_job_claims(run_id)

    stopped = client.post(f"{BASE}/stop")
    assert stopped.status_code == 200
    assert stopped.json()["released_resources"] >= 1
    assert task_resources.list_job_claims(run_id) == []


def test_status_reports_progress_from_the_evidence_dir(client, execution_env) -> None:
    run_id = "run-20261014-120000"
    run_dir = execution_env / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "steps.json").write_text(json.dumps({
        "run_id": run_id, "quest_id": "q", "support": {"key": "q", "picked_row": 1},
        "steps": [
            {"index": 1, "round": 1, "kind": "skill", "label": "技能1", "verdict": "ok"},
            {"index": 2, "round": 1, "kind": "wait", "label": "等结算", "verdict": "battle_over"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    (run_dir / "runner.log").write_text("第一行\n第二行\n", encoding="utf-8")
    api._STATE.run_id = run_id

    payload = client.get(f"{BASE}/status").json()

    assert payload["run_id"] == run_id
    assert payload["progress"]["steps_total"] == 2
    assert payload["progress"]["by_verdict"] == {"ok": 1, "battle_over": 1}
    assert payload["progress"]["last_steps"][-1]["label"] == "等结算"
    assert payload["progress"]["log_tail"] == ["第一行", "第二行"]
    assert payload["progress"]["support"]["picked_row"] == 1


def test_status_decodes_gbk_runner_log_without_mojibake(client, execution_env) -> None:
    """2026-10-15 用户报告：UI 的"实时进度"整片乱码。

    原因：后端起执行器时没设 PYTHONIOENCODING，子进程按系统默认（简体中文 Windows = GBK）
    写 runner.log，而 /status 按 UTF-8 读。这里用 GBK 字节写日志，接口必须还能读出中文。
    """
    run_id = "run-20261015-100000"
    run_dir = execution_env / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "steps.json").write_text(
        json.dumps({"run_id": run_id, "quest_id": "q", "steps": []}), encoding="utf-8")
    (run_dir / "runner.log").write_bytes("点关卡卡片 → 进本\n助战行：第1行\n".encode("gbk"))
    api._STATE.run_id = run_id

    payload = client.get(f"{BASE}/status").json()

    assert payload["progress"]["log_tail"] == ["点关卡卡片 → 进本", "助战行：第1行"]


def test_status_reads_utf8_runner_log_too(client, execution_env) -> None:
    run_id = "run-20261015-100001"
    run_dir = execution_env / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "steps.json").write_text(
        json.dumps({"run_id": run_id, "quest_id": "q", "steps": []}), encoding="utf-8")
    (run_dir / "runner.log").write_text("第 1 回合完成\n", encoding="utf-8")
    api._STATE.run_id = run_id

    payload = client.get(f"{BASE}/status").json()

    assert payload["progress"]["log_tail"] == ["第 1 回合完成"]


def test_run_forces_utf8_for_the_executor_process(client, execution_env, monkeypatch) -> None:
    """新建运行必须给子进程指定 UTF-8 输出，新日志才不会再出现乱码。"""
    spawned = _spawn_spy(monkeypatch)
    response = client.post(
        f"{BASE}/run",
        json={"spec": "spec.json", "layout": "layout.json", "confirm_ap": True},
    )
    assert response.status_code == 200
    assert spawned[0].kwargs["env"]["PYTHONIOENCODING"] == "utf-8"


# ---------- 活动结束后的 runbook：可用性判定 / 拦截 / 归档（2026-10-15） ----------


def _event_bundle(event_id: str, *, starts_at: str, ends_at: str, exchange_ends_at: str | None = None):
    from game_assistant import domain

    kwargs = {
        "event_id": event_id,
        "revision": 1,
        "server": "CN",
        "title": "幕末武斗神话 唠唠叨叨新选组",
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    if exchange_ends_at:
        kwargs["exchange_ends_at"] = exchange_ends_at
    return domain.EventBundle(**kwargs)


ENDED_EVENT_ID = "fgo-cn-2026-gudaguda9"


def test_match_event_for_quest_uses_the_longest_event_prefix() -> None:
    short = _event_bundle("fgo-cn-2026", starts_at="2020-01-01T00:00:00+08:00",
                          ends_at="2020-01-02T00:00:00+08:00")
    long = _event_bundle(ENDED_EVENT_ID, starts_at="2020-01-01T00:00:00+08:00",
                         ends_at="2020-01-02T00:00:00+08:00")

    assert api.match_event_for_quest(f"{ENDED_EVENT_ID}-90pp", [short, long]) is long
    assert api.match_event_for_quest("fgo-cn-daily-treasure-door-extreme", [long]) is None
    assert api.match_event_for_quest(ENDED_EVENT_ID, [long]) is long, "quest_id 就是活动本体也要认"
    assert api.match_event_for_quest("fgo-cn-2026-gudaguda90-90pp", [long]) is None, "不许前缀误配"


def test_options_marks_runbooks_bound_to_a_finished_event(client, execution_env, monkeypatch) -> None:
    """活动结束的 runbook 仍列出，但带 `event_ended` 标记（界面据此禁用 + 给归档按钮）。"""
    monkeypatch.setattr(api, "_event_bundles", lambda: [
        _event_bundle(ENDED_EVENT_ID, starts_at="2020-09-24T19:00:00+08:00",
                      ends_at="2020-10-15T13:59:00+08:00", exchange_ends_at="2020-10-22T13:59:00+08:00"),
    ])
    (execution_env / "runbooks" / "90pp.json").write_text(
        json.dumps({"quest_id": f"{ENDED_EVENT_ID}-90pp", "title": "90++ 神剑改"}), encoding="utf-8")

    payload = client.get(f"{BASE}/options").json()

    ended = next(item for item in payload["runbook_items"] if item["name"] == "90pp.json")
    assert ended["availability"] == "event_ended" and ended["event_id"] == ENDED_EVENT_ID
    assert "已经不在游戏里" in ended["reason"]
    # 没写 quest_id 的（老 runbook）判不出来 ⇒ 标 unknown 但不拦
    unknown = next(item for item in payload["runbook_items"] if item["name"] == "spec.json")
    assert unknown["availability"] == "unknown"


def test_run_is_blocked_for_a_finished_event_without_allow_ended(client, execution_env, monkeypatch) -> None:
    spawned = _spawn_spy(monkeypatch)
    monkeypatch.setattr(api, "_event_bundles", lambda: [
        _event_bundle(ENDED_EVENT_ID, starts_at="2020-09-24T19:00:00+08:00",
                      ends_at="2020-10-15T13:59:00+08:00"),
    ])
    (execution_env / "runbooks" / "90pp.json").write_text(
        json.dumps({"quest_id": f"{ENDED_EVENT_ID}-90pp"}), encoding="utf-8")
    body = {"spec": "90pp.json", "layout": "layout.json", "confirm_ap": True}

    blocked = client.post(f"{BASE}/run", json=body)

    assert blocked.status_code == 409
    assert "这份 runbook 现在不能跑" in blocked.json()["detail"]
    assert "allow_ended" in blocked.json()["detail"]
    assert spawned == [], "拦住的运行一个进程都不许起"

    allowed = client.post(f"{BASE}/run", json={**body, "allow_ended": True})
    assert allowed.status_code == 200, allowed.text
    assert len(spawned) == 1


def test_archive_moves_the_runbook_out_of_the_picker(client, execution_env) -> None:
    """归档 = 挪进 `runbooks/_archive/`（不删）：下拉里不再出现，文件还在，可撤销。"""
    assert (execution_env / "runbooks" / "spec.json").exists()

    response = client.post(f"{BASE}/runbooks/spec.json/archive")

    assert response.status_code == 200 and response.json()["archived"] is True
    assert (execution_env / "runbooks" / "_archive" / "spec.json").exists()
    assert not (execution_env / "runbooks" / "spec.json").exists()
    payload = client.get(f"{BASE}/options").json()
    assert payload["runbooks"] == [] and payload["archived_runbooks"] == ["spec.json"]

    assert client.post(f"{BASE}/run", json={
        "spec": "spec.json", "layout": "layout.json", "confirm_ap": True,
    }).status_code == 400, "归档之后按老名字跑 → 文件找不到（400），不会误跑"
    assert client.post(f"{BASE}/runbooks/spec.json/archive").status_code == 400, "再归档一次没有这个文件"

    back = client.post(f"{BASE}/runbooks/spec.json/unarchive")
    assert back.status_code == 200 and back.json()["archived"] is False
    assert (execution_env / "runbooks" / "spec.json").exists()
    assert client.post(f"{BASE}/runbooks/spec.json/unarchive").status_code == 400
    assert client.post(f"{BASE}/runbooks/..%2Fevil.json/archive").status_code in (400, 404)


def test_options_lists_runbooks_layouts_and_templates(client, execution_env) -> None:
    payload = client.get(f"{BASE}/options").json()
    assert payload["runbooks"] == ["spec.json"]
    assert payload["layouts"] == ["layout.json"]
    assert payload["registered_support_keys"] == []
    assert "扣 AP" in payload["note"]


def test_evidence_serves_the_latest_step_image_only_from_the_run_dir(client, execution_env) -> None:
    run_id = "run-20261014-130000"
    run_dir = execution_env / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "001_skill_before.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    api._STATE.run_id = run_id

    payload = client.get(f"{BASE}/status").json()
    assert payload["progress"]["latest_evidence"]["name"] == "001_skill_before.png"
    image = client.get(f"{BASE}/evidence/{run_id}/001_skill_before.png")
    assert image.status_code == 200

    # 只允许 runs/<run_id>/ 下的图片：穿越/别的后缀都要被拒（400 = 我们的守卫，404 = 路由先归一路径）
    assert client.get(f"{BASE}/evidence/{run_id}/..%2F..%2Fsteps.json").status_code in (400, 404)
    assert client.get(f"{BASE}/evidence/{run_id}/../steps.json").status_code in (400, 404)
    assert client.get(f"{BASE}/evidence/{run_id}/nope.png").status_code == 404
