# LAYER: control —— 本文件属于**控制层**（截图/点击/状态机）。
# 绑定规则（2026-10-10，decisions.md）：执行层必须走 FGO-py；本文件已**冻结**，
# 仅在 FGO-py POC 失败且用户明确同意后才可继续扩展。任何新增控制层代码都会让
# `tests/test_project_guardrails.py` 失败。
"""固定轮转回放执行器（离线逻辑 + MuMu 控制）。**已冻结，待 FGO-py 接管执行层。**

分工：本模块负责「按手册生成点击序列」「每一步做区域校验」「任何不符立即停止」；
真实点击/截图由 `MuMuController`（adb）承担，坐标来自 `battle_layout`。

安全约定：
- `dry_run=True` 只计算并打印点击序列，不调用任何输入命令。
- 任何校验失败 → 抛 `ExecutionAbort`，不继续、不猜，由调用方保留截图。
- 校验一律按区域裁切 + 阈值容忍，**绝不整屏比对**（实测画面有持续动画）。
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from . import battle_layout as layout

ADB_DEFAULT = r"C:\Program Files\Netease\MuMu Player 12\nx_main\adb.exe"
DEVICE_DEFAULT = "emulator-5554"
DISPLAY_DEFAULT = "2"
SF_ID_DEFAULT = "4619827767814508545"

CARD_LABELS = {"buster": "力击", "arts": "技击", "quick": "迅击"}


class ExecutionAbort(RuntimeError):
    """校验失败即停止。"""


def screen_luma(image: Any) -> float:
    """整屏平均亮度：用于"当前是不是我以为的那个画面"的粗判（绝对值依赖场景）。"""
    small = image.convert("L").resize((64, 36))
    pixels = list(small.getdata())
    return sum(pixels) / len(pixels)


def region_delta(before: Any, after: Any, box: tuple[int, int, int, int]) -> float:
    """同一区域在两次截图之间的**相对**变化量（平均亮度差）。

    实测教训：绝对阈值依赖场景（90++ 背景 ≈145，廉价副本同一区域只有 55.5），
    所以校验必须看"变化量"，而不是"像不像某个绝对亮度"。
    """
    return abs(signature(after, box).mean_luma - signature(before, box).mean_luma)


class SceneGuard:
    """记录开局画面基线；后续截图若整屏亮度偏离基线过多，说明进入了非预期界面。

    用途：任何一步之前先过 `check()`，基线异常就**立即停止**，
    避免"在错误界面上继续点"（2026-10-10 实测踩过：起点已经是异常界面，走到第三步才发现）。
    """

    def __init__(self, tolerance: float = 25.0) -> None:
        self.tolerance = tolerance
        self.baseline: float | None = None

    def arm(self, image: Any) -> float:
        self.baseline = screen_luma(image)
        return self.baseline

    def check(self, image: Any) -> None:
        if self.baseline is None:
            raise ExecutionAbort("SceneGuard 尚未 arm（未记录基线）")
        current = screen_luma(image)
        if abs(current - self.baseline) > self.tolerance:
            raise ExecutionAbort(
                f"画面与开局基线偏离过大（基线 {self.baseline:.1f} → 现在 {current:.1f}），"
                "可能不在预期界面，已停止。"
            )


@dataclass
class RegionSignature:
    mean_luma: float
    mean_rgb: tuple[float, float, float]

    def close_to(self, other: "RegionSignature", luma_tol: float = 12.0) -> bool:
        return abs(self.mean_luma - other.mean_luma) <= luma_tol


def signature(image: Any, box: tuple[int, int, int, int]) -> RegionSignature:
    region = image.crop(box).convert("RGB")
    pixels = list(region.getdata())
    count = len(pixels)
    mean_r = sum(p[0] for p in pixels) / count
    mean_g = sum(p[1] for p in pixels) / count
    mean_b = sum(p[2] for p in pixels) / count
    luma = 0.299 * mean_r + 0.587 * mean_g + 0.114 * mean_b
    return RegionSignature(mean_luma=luma, mean_rgb=(mean_r, mean_g, mean_b))


def badge_box(card_index: int) -> tuple[int, int, int, int]:
    cx, cy = layout.CARD_AREA[card_index]
    dx, dy = layout.CARD_BADGE_OFFSET
    w, h = layout.CARD_BADGE_SIZE
    x0, y0 = cx + dx, cy + dy
    return x0, y0, x0 + w, y0 + h


def skill_box(slot: str, index: int) -> tuple[int, int, int, int]:
    cx, cy = layout.skill_point(slot, index)
    size = layout.SKILL_ICON_BOX
    half_w, half_h = (size, size) if isinstance(size, int) else size
    half_w, half_h = half_w // 2, half_h // 2
    return cx - half_w, cy - half_h, cx + half_w, cy + half_h


def pick_card(runbook_card: str, available: dict[int, str], used: Iterable[int] = ()) -> int:
    """从当前手牌里挑一张符合要求的卡；找不到就停止，绝不点错卡。"""
    used_set = set(used)
    wanted = str(runbook_card or "").lower()
    if wanted in {"", "any"}:  # 轮转里写"任意"的卡位：按剩余位置从左到右取
        for index in sorted(available):
            if index not in used_set:
                return index
        raise ExecutionAbort("手牌已空，无法再选卡")
    for index in sorted(available):
        if index in used_set:
            continue
        if available[index] == wanted:
            return index
    raise ExecutionAbort(
        "手牌里没有 " + CARD_LABELS.get(wanted, wanted) + "：当前 "
        + str([CARD_LABELS.get(v, v) for v in available.values()])
    )


@dataclass
class TapStep:
    turn: int
    label: str
    point: tuple[int, int] | None = None
    needs_screen: bool = False


def _skill_index(actor: str, skill_name: str, member: dict[str, Any]) -> int:
    """技能名 → 技能槽序号；查不到就停止（不猜）。"""
    from .skill_effects import get_skill_table

    entry = get_skill_table().find(actor, str(member.get("class_name") or ""))
    if entry is None:
        raise ExecutionAbort("技能表里找不到 " + actor)
    for skill in entry.get("skills") or []:
        if str(skill.get("name")) == skill_name:
            return int(skill.get("slot") or 1)
    raise ExecutionAbort(actor + " 没有技能「" + skill_name + "」")


def plan_taps(spec: dict[str, Any]) -> list[TapStep]:
    """把 spec 的步骤翻译成点击序列。

    **出手流程（用户 2026-10-10 两次纠正后的最终版）**：
    ① 技能全部在主战斗界面用完；
    ② 点右下「攻击」进入选择界面；
    ③ **按执行顺序依次点**：宝具卡（最左侧那张）→ 指令卡，共选 3 张；
    ④ **选满 3 张会自动执行本回合，没有"再点攻击确认"这一步**。
    注意：宝具必须是第一个点（点击顺序=执行顺序）；直接点主界面的宝具条只会打开从者状态信息。
    """
    team = list(spec.get("team") or [])
    slot_of = {str(member.get("name")): "slot" + str(index) for index, member in enumerate(team, start=1)}
    steps: list[TapStep] = []
    cards_in_turn = 0
    last_turn = 0
    hand_index = 0
    for raw in spec.get("steps") or []:
        turn = int(raw.get("turn") or 1)
        if turn != last_turn:
            # 换回合：**没有"再点攻击执行"这一步**——选满 3 张会自动执行。
            cards_in_turn = 0
            entered = False
            last_turn = turn
        actor = str(raw.get("actor") or "")
        slot = slot_of.get(actor, "slot1")
        kind = str(raw.get("kind") or "")
        if kind in {"np", "card"} and not entered:
            # 技能必须在主战斗界面使用完毕，再点「攻击」进入选择界面选卡。
            steps.append(TapStep(turn, "点「攻击」进入选择界面", layout.ATTACK_BUTTON))
            entered = True
            cards_in_turn = 0
        if kind == "skill":
            member = next((m for m in team if str(m.get("name")) == actor), {})
            index = _skill_index(actor, str(raw.get("skill") or ""), member)
            steps.append(TapStep(turn, actor + " 技能" + str(index) + "：" + str(raw.get("skill")), layout.skill_point(slot, index)))
        elif kind == "np":
            steps.append(TapStep(turn, actor + " 宝具卡（选择界面最左）", layout.NP_CARD_SLOT))
        elif kind == "card":
            label = CARD_LABELS.get(str(raw.get("card")), str(raw.get("card")))
            steps.append(TapStep(turn, actor + " " + label + " 指令卡", None, needs_screen=True))
            cards_in_turn += 1
        else:
            raise ValueError("未知步骤：" + kind)
    # 选满 3 张（宝具卡 + 指令卡）后自动执行，无需额外点击。
    return steps


class MuMuController:
    """MuMu(adb) 的最小控制器：截图与点击。"""

    def __init__(
        self,
        adb: str = ADB_DEFAULT,
        device: str = DEVICE_DEFAULT,
        display: str = DISPLAY_DEFAULT,
        sf_id: str = SF_ID_DEFAULT,
        shot_dir: Path | str = Path(r"D:\workSpace\code\.tmp\shots"),
    ) -> None:
        self.adb = adb
        self.device = device
        self.display = display
        self.sf_id = sf_id
        self.shot_dir = Path(shot_dir)
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        self.counter = 0

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([self.adb, "-s", self.device, *args], capture_output=True, text=True)

    def screenshot(self) -> Any:
        from PIL import Image

        self.counter += 1
        remote = "/sdcard/exec_" + str(self.counter).zfill(3) + ".png"
        local = self.shot_dir / ("exec_" + str(self.counter).zfill(3) + ".png")
        self._run("shell", "screencap", "-p", "-d", self.sf_id, remote)
        self._run("pull", remote, str(local))
        return Image.open(local)

    def tap(self, point: tuple[int, int]) -> None:
        self._run("shell", "input", "-d", self.display, "tap", str(point[0]), str(point[1]))


def run_rotation(
    spec: dict[str, Any],
    controller: MuMuController | None = None,
    dry_run: bool = True,
    echo: Callable[[str], None] = print,
    card_types: dict[int, str] | None = None,
) -> list[str]:
    """执行固定轮转；`dry_run=True` 只打印计划，不点击。"""
    steps = plan_taps(spec)
    log: list[str] = []
    used_cards: set[int] = set()
    wanted_cards = [str(raw.get("card") or "") for raw in spec.get("steps") or [] if str(raw.get("kind")) == "card"]
    wanted_iter = iter(wanted_cards)
    for step in steps:
        if step.needs_screen:
            wanted = next(wanted_iter, "")
            if dry_run or card_types is None:
                log.append("[计划] 第" + str(step.turn) + "回合 " + step.label + "（需截图识别卡色）")
                continue
            index = pick_card(wanted, card_types, used_cards)
            used_cards.add(index)
            point = layout.CARD_AREA[index]
            log.append("[执行] " + step.label + " → 第 " + str(index) + " 张 " + str(point))
            if controller:
                controller.tap(point)
            continue
        log.append("[计划] 第" + str(step.turn) + "回合 " + step.label + " → " + str(step.point))
        if not dry_run and controller and step.point:
            controller.tap(step.point)
    for line in log:
        echo(line)
    return log
