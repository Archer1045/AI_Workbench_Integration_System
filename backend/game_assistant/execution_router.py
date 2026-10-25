"""游戏执行器的 HTTP 入口：起/停 `battle_runner` 子进程 + 读进度。

分工不变：**控制原语只在 FGO-py 侧**（`fgoAgent.py`，工作区之外）。本模块只做编排——
把命令行执行器当子进程起来，再把它落在 `runs/<run_id>/` 的证据（`steps.json` + 每步前后
截图）读出来当进度流。这里不出现任何设备通道 / 输入 / 截图的驱动代码。

安全口径（与 AGENTS.md「执行范围受控」一致）：
  * 每次运行都必须显式带 `confirm_ap=true`（**每一局都真实扣 AP**，默认 40）；
  * 同一时间只允许一个运行在跑；
  * `spec` / `layout` 只允许取 `game_assistant_execution/{runbooks,layouts}` 下的文件，
    解析后的真实路径必须仍在该目录内（防目录穿越）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import config
from . import battle_plan as plan_mod

router = APIRouter(prefix="/api/game-assistant/fgo/execution", tags=["game-assistant-execution"])

STOP_GRACE_SECONDS = 8.0
LOG_TAIL_LINES = 40
STEP_TAIL = 12


def execution_dir() -> Path:
    """每次都现读 config（测试里 monkeypatch 执行目录就能隔离）。"""
    return Path(config.GAME_ASSISTANT_EXECUTION_DIR)


def runbook_dir() -> Path:
    return execution_dir() / "runbooks"


def layout_dir() -> Path:
    return execution_dir() / "layouts"


def runs_dir() -> Path:
    return execution_dir() / "runs"


class ExecutionRunRequest(BaseModel):
    spec: str = Field(..., description="runbooks/ 下的文件名，例如 daily_treasure_door_extreme_*.json")
    layout: str = Field(..., description="layouts/ 下的文件名")
    rounds: int = Field(1, ge=1, le=99, description="连刷局数；每一局都真实扣 AP")
    enter_quest: bool = Field(False, description="先在地图上把这一局开起来（自证式导航）")
    support_row: int = Field(0, ge=0, le=9, description="首次登记 / 换助战时指定第几行（0 = 按指纹自动认）")
    auto_apple: int = Field(
        0,
        ge=0,
        le=3,
        description="AP 不足时自动使用黄金果实，最多 3 个；0 = 不自动使用（消耗道具，需显式确认）",
    )
    device: str = Field("", description="设备序列号覆盖；留空则用 config 里的值（驱动侧会自动兜底）")
    confirm_ap: bool = Field(False, description="必须显式给 true：确认这次运行会真实消耗 AP")
    allow_ended: bool = Field(
        False,
        description="显式允许跑「活动已结束」的 runbook（默认拦住：副本已经不在了，"
        "从地图开刷会点到别的关卡、白烧 AP）",
    )


class _RunState:
    """当前/最近一次运行的状态（单运行模型）。"""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.process: subprocess.Popen[bytes] | None = None
        self.run_id = ""
        self.run_dir = Path()
        self.log_path = Path()
        self.started_at = ""
        self.rounds = 1
        self.auto_apple = 0
        self.enter_quest = False
        self.exit_code: int | None = None
        self.stop_requested = False

    def snapshot(self) -> dict[str, Any]:
        process = self.process
        running = process is not None and process.poll() is None
        if process is not None and not running:
            self.exit_code = process.returncode
        return {
            "running": running,
            "run_id": self.run_id,
            "run_dir": str(self.run_dir) if self.run_id else "",
            "started_at": self.started_at,
            "rounds": self.rounds,
            "auto_apple": self.auto_apple,
            "enter_quest": self.enter_quest,
            "pid": process.pid if (process is not None and running) else None,
            "exit_code": self.exit_code,
            "stop_requested": self.stop_requested,
        }


_STATE = _RunState()


def _resolve_under(directory: Path, name: str) -> Path:
    """把文件名解析到指定目录内；越界（含 `..`）直接拒绝。"""
    candidate = (directory / str(name or "")).resolve()
    root = directory.resolve()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(status_code=400, detail=f"只允许 {root.name}/ 下的文件：{name}")
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail=f"文件不存在：{name}")
    return candidate


def _tail(path: Path, lines: int) -> list[str]:
    """读日志尾巴。

    编码：从 2026-10-15 起执行器被强制用 UTF-8 输出（见 `start_run` 里的 PYTHONIOENCODING），
    但**历史日志**是系统默认编码（简体中文 Windows = GBK）写出来的——按 UTF-8 硬读会整片乱码
    （UI 的"实时进度"里那堆问号就是它）。所以先严格按 UTF-8 解，失败再退到系统 ANSI / GBK。
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    for encoding in ("utf-8", "mbcs", "gbk"):
        try:
            return raw.decode(encoding).splitlines()[-lines:]
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace").splitlines()[-lines:]


def _event_bundles() -> list[Any]:
    """读活动事实包（**注入点**：测试 monkeypatch 这个函数就能伪造活动状态）。"""
    try:
        from .store import GameAssistantStore

        store = GameAssistantStore()
        store.initialize()
        return store.list_bundles(active_only=False)
    except Exception:
        # 事实库读不出来时不拦：判不了的事情不该挡人干活（宁可在 UI 上标"无法判定"）
        return []


def match_event_for_quest(quest_id: str, bundles: list[Any]) -> Any | None:
    """runbook 的 `quest_id` → 对应的活动事实包（按**最长的 event_id 前缀**匹配）。

    约定：活动本的 runbook 用 `<event_id>-<后缀>` 命名（推荐器生成的就是
    `fgo-cn-2026-gudaguda9-90pp`）；日常本（例如宝物之门）匹配不到任何活动，返回 None。
    """
    best: Any | None = None
    for bundle in bundles:
        event_id = str(getattr(bundle, "event_id", "") or "")
        if not event_id:
            continue
        if quest_id == event_id or quest_id.startswith(f"{event_id}-"):
            if best is None or len(event_id) > len(str(best.event_id)):
                best = bundle
    return best


def runbook_availability(quest_id: str) -> dict[str, Any]:
    """判定一份 runbook 现在还能不能跑。

    起因（2026-10-15）：幕末武斗神话结束后，那份 90++ runbook 还留在执行页下拉里。它绑的
    90++ 自由本已经关掉了，而执行器认路靠的是**关卡卡片模板**、不认 quest_id ⇒ 真跑起来会点到
    模板匹配上的另一张卡（宝物库之门），在错的副本里跑那套动作、白烧 AP。所以这里要判定，
    `/run` 也要拦（除非显式 `allow_ended`）。

    返回值：
      * `availability = usable`：绑的活动在办，或压根不属于任何活动（日常本）；
      * `availability = event_ended`：绑的活动已结束（副本没了）；
      * `availability = unknown`：事实库读不出来，判不了（不拦，但界面标注）。
    """
    from . import service as ga_service

    bundles = _event_bundles()
    if not bundles:
        return {
            "availability": "unknown",
            "event_id": "",
            "event_status": "",
            "reason": "读不到活动事实库：这份 runbook 能不能跑没法判定",
        }
    bundle = match_event_for_quest(str(quest_id or ""), bundles)
    if bundle is None:
        return {
            "availability": "usable",
            "event_id": "",
            "event_status": "",
            "reason": "不属于已导入的活动（例如日常本），按原样可用",
        }
    status = ga_service.event_status(bundle, datetime.now(ga_service.SHANGHAI))
    if status == ga_service.STATUS_RUNNING:
        return {
            "availability": "usable",
            "event_id": bundle.event_id,
            "event_status": status,
            "reason": f"绑定的活动《{bundle.title}》在办",
        }
    return {
        "availability": "event_ended",
        "event_id": bundle.event_id,
        "event_status": status,
        "reason": (
            f"绑定的活动《{bundle.title}》已于 "
            f"{bundle.ends_at.strftime('%Y-%m-%d %H:%M')} 结束，对应的副本已经不在游戏里了"
            "（从地图开刷会点到别的关卡、白烧 AP）"
        ),
    }


def _progress(run_id: str) -> dict[str, Any]:
    """从证据目录读进度：steps.json 的统计 + 最后几步 + 日志尾巴。"""
    if not run_id:
        return {"steps_total": 0, "by_verdict": {}, "last_steps": [], "log_tail": []}
    path = runs_dir() / run_id / "steps.json"
    payload: dict[str, Any] = {"steps_total": 0, "by_verdict": {}, "last_steps": [], "log_tail": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    if isinstance(data, dict):
        steps = data.get("steps") or []
        payload["steps_total"] = len(steps)
        counts: dict[str, int] = {}
        for step in steps:
            verdict = str(step.get("verdict") or "?")
            counts[verdict] = counts.get(verdict, 0) + 1
        payload["by_verdict"] = counts
        payload["last_steps"] = [
            {
                "index": step.get("index"),
                "round": step.get("round"),
                "kind": step.get("kind"),
                "label": step.get("label"),
                "verdict": step.get("verdict"),
                "note": step.get("note"),
            }
            for step in steps[-STEP_TAIL:]
        ]
        payload["quest_id"] = data.get("quest_id")
        payload["support"] = data.get("support")
    log_path = runs_dir() / run_id / "runner.log"
    payload["log_tail"] = _tail(log_path, LOG_TAIL_LINES)
    # 最新一张现场图（执行器每步都会存一张，UI 直接显示它；按 mtime 取最新的）
    run_root = runs_dir() / run_id
    latest: dict[str, Any] | None = None
    try:
        images = [p for p in run_root.glob("*.png") if p.is_file()]
        if images:
            newest = max(images, key=lambda p: p.stat().st_mtime)
            latest = {"name": newest.name, "mtime": int(newest.stat().st_mtime)}
    except OSError:
        latest = None
    payload["latest_evidence"] = latest
    return payload


@router.get("/evidence/{run_id}/{name}")
def evidence(run_id: str, name: str) -> FileResponse:
    """读某次运行的现场图（只允许 `runs/<run_id>/` 下的图片）。"""
    run_root = runs_dir().resolve()
    target = (run_root / run_id / name).resolve()
    if run_root not in target.parents or target.suffix.lower() not in (".png", ".jpg"):
        raise HTTPException(status_code=400, detail="只允许读取 runs/<run_id>/ 下的图片")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="证据文件不存在")
    return FileResponse(target)


class RunbookTeamSlot(BaseModel):
    """队伍里的一格。`name` 用图鉴正式名；同名多只时用 `class_name` 消歧（编译器会校验）。"""

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=80)
    class_name: str = Field(default="", max_length=40)


class RunbookDraft(BaseModel):
    """前端表单提交的东西：副本 + 队伍 + 每回合操作 + 助战规则。"""

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=120, description="落盘文件名，必须以 .json 结尾")
    quest_id: str = Field(default="", max_length=120)
    title: str = Field(default="", max_length=200)
    source: str = Field(default="", max_length=300)
    notes: list[str] = Field(default_factory=list)
    dps: str = Field(
        default="",
        max_length=80,
        description="打手位（队伍里的名字）。写了之后辅助位的单体友方技能没给 target 时默认指向它",
    )
    team: list[RunbookTeamSlot] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    support: dict[str, Any] | None = None


class SupportRegisterRequest(BaseModel):
    """「登记当前助战行」：游戏停在助战屏时，把第 N 行的从者/礼装指纹存进指纹库。"""

    model_config = {"extra": "forbid"}

    row: int = Field(1, ge=1, le=9, description="从第几行取指纹（1-based，从上往下数）")
    servant: str = Field("", max_length=80, description="把该行的从者指纹存成这个名字；留空则不登记从者")
    ce: list[str] = Field(
        default_factory=list,
        description="礼装名字清单（可重复）；写 `名字:行号` 表示取另一行的礼装条",
    )
    device: str = Field("", description="设备序列号覆盖；留空则用 config 里的值")


def _clean_register_name(value: str, what: str) -> str:
    """登记用的名字要能安全地当文件名/白名单项：不许带路径分隔符或冒号。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > 80 or any(ch in text for ch in "/\\:") or text.startswith("."):
        raise HTTPException(
            status_code=400,
            detail=f"{what}名字不合法（不能带路径分隔符、冒号，也不能以点开头）：{value}",
        )
    return text


def _executor_env(device: str) -> dict[str, str]:
    """执行器子进程的环境：日志统一 UTF-8（否则 UI 的"实时进度"会乱码）。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("PYTHONUTF8", "1")
    if device.strip():
        env["FGO_PY_DEVICE"] = device.strip()
    return env


@router.get("/support-library")
def support_library() -> dict[str, list[str]]:
    """已登记过的助战指纹（表单里勾助战规则用）：按从者、按礼装两份名字清单。"""
    base = execution_dir() / "templates" / "support"
    result: dict[str, list[str]] = {}
    for kind in ("servant", "ce"):
        names: list[str] = []
        directory = base / kind
        if directory.is_dir():
            for meta_path in sorted(directory.glob("*.json")):
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                names.append(str(meta.get("name") or meta_path.stem))
        result[kind] = names
    return result


@router.post("/support/register")
def register_support_row(request: SupportRegisterRequest) -> dict[str, Any]:
    """零点击登记：游戏停在「助战选择」屏时，把第 N 行的从者/礼装指纹存进指纹库。

    执行器只截图 + 存图，**一下都不点**（不花 AP、也不改游戏状态），所以照旧起
    `battle_runner` 子进程（设备通道只在执行器那一侧），但**永远不带 `--execute`**。
    屏不对 / 行号越界时执行器会 fail-stop，这里把它的报告原样回给界面。
    """
    servant = _clean_register_name(request.servant, "从者")
    ce_specs: list[str] = []
    for raw in request.ce:
        text = str(raw or "").strip()
        if not text:
            continue
        name, _sep, tail = text.rpartition(":")
        if name.strip() and tail.strip().isdigit():
            _clean_register_name(name, "礼装")
            ce_specs.append(f"{name.strip()}:{int(tail)}")
        else:
            _clean_register_name(text, "礼装")
            ce_specs.append(text)
    if not servant and not ce_specs:
        raise HTTPException(status_code=400, detail="登记至少要给一个名字：从者 和/或 礼装")
    with _STATE.lock:
        if _STATE.process is not None and _STATE.process.poll() is None:
            raise HTTPException(
                status_code=409,
                detail=f"已经有运行在跑（run_id={_STATE.run_id}）；设备被它占着，先停掉再登记。",
            )
    run_id = datetime.now().strftime("register-%Y%m%d-%H%M%S")
    command = [
        sys.executable, "-u", "-m", "game_assistant.battle_runner",
        "--register-support", "--support-row", str(int(request.row)), "--run-id", run_id,
    ]
    if servant:
        command += ["--servant", servant]
    for spec in ce_specs:
        command += ["--ce", spec]
    try:
        finished = subprocess.run(
            command, cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, env=_executor_env(request.device), timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False, "exit_code": None, "run_id": run_id, "report": None,
            "output_tail": ["登记超时（120 秒）——设备或游戏可能没响应"],
        }
    output = (finished.stdout or b"").decode("utf-8", errors="replace")
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    report: dict[str, Any] | None = None
    for line in lines:
        if line.startswith("REGISTER_REPORT "):
            try:
                report = json.loads(line[len("REGISTER_REPORT "):])
            except json.JSONDecodeError:
                report = None
    return {
        "ok": finished.returncode == 0 and report is not None,
        "exit_code": finished.returncode,
        "run_id": run_id,
        "report": report,
        "output_tail": lines[-30:],
        "note": "登记只截图 + 存指纹，不花 AP、不改游戏状态。",
    }


@router.post("/runbooks")
def create_runbook(draft: RunbookDraft) -> dict[str, Any]:
    """把「副本 + 队伍 + 每回合操作 + 助战规则」落成一个 runbook。

    **先编译期校验再写盘**：`compile_plan` 会拦下同名歧义、技能槽越界、每回合出手位不是 3 个
    这类错误；校验不过就 400，一个字节都不写。落盘后 `/options` 会自动列出它，执行页就能选。
    """
    name = draft.name.strip()
    if not name.endswith(".json") or any(ch in name for ch in ("/", "\\")) or name.startswith("."):
        raise HTTPException(status_code=400, detail="runbook 名字必须是 <名字>.json，且不能带路径")
    spec: dict[str, Any] = {
        "quest_id": draft.quest_id,
        "title": draft.title,
        "source": draft.source,
        "notes": draft.notes,
        "team": [slot.model_dump() for slot in draft.team],
        "steps": draft.steps,
    }
    if draft.dps.strip():
        spec["dps"] = draft.dps.strip()
    if draft.support:
        spec["support"] = draft.support
    try:
        plan = plan_mod.compile_plan(spec)
    except plan_mod.PlanError as exc:
        raise HTTPException(status_code=400, detail=f"计划编译不过：{exc}") from exc
    runbook_dir().mkdir(parents=True, exist_ok=True)
    path = runbook_dir() / name
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "name": name,
        "actions": len(plan.actions),
        "summary": plan.summary(),
        "support": spec.get("support") or {},
    }


def _archivable_name(name: str) -> str:
    """归档用的是文件名，不接受路径（和 `/runbooks` 落盘时同一条口径）。"""
    text = str(name or "").strip()
    if not text or any(ch in text for ch in ("/", "\\")) or text.startswith("."):
        raise HTTPException(status_code=400, detail=f"只接受 runbooks/ 下的文件名：{name}")
    return text


@router.post("/runbooks/{name}/archive")
def archive_runbook(name: str) -> dict[str, Any]:
    """把 runbook 挪进 `runbooks/_archive/`（**不删**）。

    活动结束后它绑的副本没了、也不该留在执行页下拉里误选；但动作序列（技能顺序、宝具时机、
    纹章那几条踩坑结论）在复刻或做同类 90++ 时还能抄，所以归档而不是删除。
    """
    path = _resolve_under(runbook_dir(), _archivable_name(name))
    archive_dir = runbook_dir() / "_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / path.name
    if target.exists():
        raise HTTPException(status_code=409, detail=f"_archive/ 里已经有同名文件：{target.name}")
    path.replace(target)
    return {"archived": True, "name": target.name, "path": str(target)}


@router.post("/runbooks/{name}/unarchive")
def unarchive_runbook(name: str) -> dict[str, Any]:
    """把归档的 runbook 放回 `runbooks/`（撤销归档）。"""
    archive_dir = runbook_dir() / "_archive"
    source = archive_dir / _archivable_name(name)
    if not source.is_file():
        raise HTTPException(status_code=400, detail=f"_archive/ 里没有这个文件：{name}")
    target = runbook_dir() / source.name
    if target.exists():
        raise HTTPException(status_code=409, detail=f"runbooks/ 里已经有同名文件：{source.name}")
    source.replace(target)
    return {"archived": False, "name": source.name, "path": str(target)}


@router.post("/runbooks/{name}/check")
def check_runbook(name: str, layout: str = "", enter_quest: bool = False, device: str = "") -> dict[str, Any]:
    """对某个 runbook 做**零点击自检**：用"不执行"模式跑一遍执行器，把它的报告回给界面。

    只截图 + 判据，**不点任何东西、不花 AP**；画面不是预期起点时执行器自己会报不 ready。
    参数 `layout` 省略时用 layouts 目录里的第一个（现在只有一份）。
    """
    spec_path = _resolve_under(runbook_dir(), name)
    if layout:
        layout_path = _resolve_under(layout_dir(), layout)
    else:
        candidates = sorted(layout_dir().glob("*.json")) if layout_dir().is_dir() else []
        if not candidates:
            raise HTTPException(status_code=400, detail="layouts 目录里没有可用的布局文件")
        layout_path = candidates[0]
    command = [
        sys.executable, "-u", "-m", "game_assistant.battle_runner",
        str(spec_path), str(layout_path),
    ]
    if enter_quest:
        command.append("--enter-quest")
    try:
        finished = subprocess.run(
            command, cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, env=_executor_env(device), timeout=180,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": None, "output_tail": ["自检超时（180 秒）——设备或游戏可能没响应"]}
    output = (finished.stdout or b"").decode("utf-8", errors="replace")
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    return {
        "ok": finished.returncode == 0,
        "exit_code": finished.returncode,
        "output_tail": lines[-30:],
    }


@router.get("/options")
def options() -> dict[str, Any]:
    """UI 选择用：有哪些 runbook / layout，以及各自的助战指纹登记情况。"""
    support_dir = execution_dir() / "templates" / "support"
    runbooks = sorted(p.name for p in runbook_dir().glob("*.json")) if runbook_dir().is_dir() else []
    archived = (
        sorted(p.name for p in (runbook_dir() / "_archive").glob("*.json"))
        if (runbook_dir() / "_archive").is_dir()
        else []
    )
    layouts = sorted(p.name for p in layout_dir().glob("*.json")) if layout_dir().is_dir() else []
    buttons = sorted(p.stem for p in (execution_dir() / "templates" / "buttons").glob("*.json")) \
        if (execution_dir() / "templates" / "buttons").is_dir() else []
    # runbook 的可用性：绑的活动结束了就不能跑（副本已经不在游戏里，硬跑会点到别的关卡）
    runbook_items: list[dict[str, Any]] = []
    for name in runbooks:
        quest_id = ""
        title = ""
        try:
            spec = json.loads((runbook_dir() / name).read_text(encoding="utf-8"))
            quest_id = str(spec.get("quest_id") or "")
            title = str(spec.get("title") or "")
        except (OSError, json.JSONDecodeError):
            pass
        if quest_id:
            availability = runbook_availability(quest_id)
        else:
            availability = {
                "availability": "unknown",
                "event_id": "",
                "event_status": "",
                "reason": "runbook 里没写 quest_id：判不了它绑的是哪个活动",
            }
        runbook_items.append({"name": name, "quest_id": quest_id, "title": title, **availability})
    return {
        "runbooks": runbooks,
        "runbook_items": runbook_items,
        "archived_runbooks": archived,
        "layouts": layouts,
        "registered_support_keys": sorted(p.stem for p in support_dir.glob("*.json"))
        if support_dir.is_dir() else [],
        "registered_buttons": buttons,
        "note": "每次运行都会真实扣 AP；连续出击相关的开关请在 UI 上显式确认。",
    }


@router.get("/status")
def status() -> dict[str, Any]:
    with _STATE.lock:
        snapshot = _STATE.snapshot()
        log_path = _STATE.log_path
        if snapshot["running"]:
            log_path = _STATE.log_path
    snapshot["progress"] = _progress(snapshot["run_id"])
    snapshot["log_path"] = str(log_path) if str(log_path) else ""
    return snapshot


@router.post("/run")
def start_run(request: ExecutionRunRequest) -> dict[str, Any]:
    if not request.confirm_ap:
        raise HTTPException(
            status_code=400,
            detail="必须显式确认：加 confirm_ap=true。每一局都真实消耗 AP（本关 40）。",
        )
    spec_path = _resolve_under(runbook_dir(), request.spec)
    # 「活动已结束」的 runbook 默认拦住（2026-10-15）：它绑的副本已经不在游戏里，而执行器认路靠
    # 关卡卡片模板、不认 quest_id ⇒ 硬跑会点到别的关卡，白烧 AP。真要跑得显式 allow_ended=true。
    try:
        spec_payload = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"runbook 读不出来：{exc}") from exc
    quest_id = str(spec_payload.get("quest_id") or "")
    availability = runbook_availability(quest_id) if quest_id else {
        "availability": "unknown", "reason": "runbook 里没写 quest_id：判不了它绑的是哪个活动",
    }
    if availability.get("availability") == "event_ended" and not request.allow_ended:
        raise HTTPException(
            status_code=409,
            detail=(
                f"这份 runbook 现在不能跑：{availability.get('reason')}。"
                "要强行跑（复刻了、或想手动对照）请带 allow_ended=true。"
            ),
        )
    layout_path = _resolve_under(layout_dir(), request.layout)
    with _STATE.lock:
        if _STATE.process is not None and _STATE.process.poll() is None:
            raise HTTPException(
                status_code=409,
                detail=f"已经有运行在跑（run_id={_STATE.run_id}）；先停掉再起新的。",
            )
        run_id = datetime.now().strftime("run-%Y%m%d-%H%M%S")
        run_dir = runs_dir() / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "runner.log"
        command = [
            sys.executable, "-u", "-m", "game_assistant.battle_runner",
            str(spec_path), str(layout_path),
            "--execute", "--start-at", "1", "--rounds", str(request.rounds),
            "--run-id", run_id,
        ]
        if request.enter_quest:
            command.append("--enter-quest")
        if request.support_row:
            command += ["--support-row", str(int(request.support_row))]
        if request.auto_apple:
            command += ["--auto-apple", str(int(request.auto_apple))]
        # 统一按 UTF-8 输出日志：否则子进程按系统默认（简体中文 Windows = GBK）写，
        # 而 /status 按 UTF-8 读 ⇒ UI 的"实时进度"整片乱码（2026-10-15 用户报告）。
        env = _executor_env(request.device)
        log_handle = log_path.open("wb")
        try:
            process = subprocess.Popen(
                command, cwd=str(Path(__file__).resolve().parent.parent),
                stdout=log_handle, stderr=subprocess.STDOUT, env=env,
            )
        finally:
            log_handle.close()
        _STATE.process = process
        _STATE.run_id = run_id
        _STATE.run_dir = run_dir
        _STATE.log_path = log_path
        _STATE.started_at = datetime.now().isoformat(timespec="seconds")
        _STATE.rounds = request.rounds
        _STATE.auto_apple = request.auto_apple
        _STATE.enter_quest = request.enter_quest
        _STATE.exit_code = None
        _STATE.stop_requested = False
    return {
        "run_id": run_id,
        "pid": process.pid,
        "rounds": request.rounds,
        "auto_apple": request.auto_apple,
        "enter_quest": request.enter_quest,
        "run_dir": str(run_dir),
        "log_path": str(log_path),
        "note": "已启动。用 GET /status 看进度；点「停止」会终止进程，设备停在当前画面需人工确认。",
    }


@router.post("/stop")
def stop_run() -> dict[str, Any]:
    with _STATE.lock:
        process = _STATE.process
        if process is None or process.poll() is not None:
            return {"stopped": False, "reason": "当前没有在跑的运行", "run_id": _STATE.run_id}
        _STATE.stop_requested = True
        run_id = _STATE.run_id
    process.terminate()
    deadline = time.time() + STOP_GRACE_SECONDS
    while time.time() < deadline and process.poll() is None:
        time.sleep(0.2)
    if process.poll() is None:
        process.kill()
    with _STATE.lock:
        _STATE.exit_code = process.returncode
    # Windows 上 terminate()/kill() 不保证子进程执行 finally，DeviceLease.release()
    # 可能来不及跑；这里按 run_id 主动释放，避免下一次点击「开始」在 120 秒 TTL 内
    # 被自己的旧租约挡住（2026-10-19 实测：停止后立刻重开 ⇒ 资源冲突 ADB+模拟器）。
    released = 0
    try:
        import task_resources

        released = task_resources.release_resources(run_id, reason="run_stopped")
    except Exception:
        pass
    return {
        "stopped": True,
        "run_id": run_id,
        "exit_code": process.returncode,
        "released_resources": released,
        "note": "已停止。设备会停在当时的画面，请人工确认后再决定下一步；本次资源租约已释放。",
    }
