"""结算页收尾 + 设备序列号兜底 的回归测试（不接真机）。"""
from __future__ import annotations

import json

import numpy as np
import pytest

import config

from game_assistant import battle_plan as plan_mod
from game_assistant import battle_runner as runner_mod
from game_assistant import battle_vision as vision


class CyclingLink:
    """按顺序吐画面（不夹取最后一张），记录每次点击。"""

    def __init__(self, frames: list[np.ndarray]) -> None:
        self.frames = frames
        self.taps: list[tuple[float, float]] = []
        self.swipes: list[tuple[float, float, float, float]] = []
        self.display = {"serial": "fake", "logical": 2, "sfid": "0"}
        self._index = 0

    def __enter__(self) -> "CyclingLink":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def shot(self, path, settle: float = 0.0) -> dict:
        from pathlib import Path

        from PIL import Image

        frame = self.frames[self._index % len(self.frames)]
        self._index += 1
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(frame.astype(np.uint8)).save(str(path) + ".png")
        return {"path": str(path) + ".png", "luma": float(frame.mean())}

    def tap(self, x, y, settle: float = 0.0) -> dict:
        self.taps.append((float(x), float(y)))
        return {"x": x, "y": y}

    def swipe(self, x1, y1, x2, y2, settle: float = 0.0) -> dict:
        self.swipes.append((float(x1), float(y1), float(x2), float(y2)))
        return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


def _pair() -> list[np.ndarray]:
    dark = np.zeros((720, 1280, 3), dtype=np.int16)
    bright = dark.copy()
    bright[100:600, 100:1200] = 255
    return [dark, bright]


def _attack_frame() -> np.ndarray:
    """主战斗界面：亮蓝圆盘半径按真按钮实测（核心 4470-4621 px）取 44。"""
    frame = np.full((720, 1280, 3), 120, dtype=np.int16)
    yy, xx = np.ogrid[:720, :1280]
    frame[(xx - 1163) ** 2 + (yy - 604) ** 2 <= 44**2] = (60, 150, 240)
    return frame


def _layout() -> runner_mod.SessionLayout:
    return runner_mod.SessionLayout(
        skill_x={1: (73, 163, 257)},
        skill_y=582,
        np_cards={1: (400, 205)},
        target_points={1: (325, 388)},
        master_menu=(1190, 290),
        master_skills=((907, 309),),
        undo=(1170, 684),
        source="测试用",
    )


# ---------- 结算页收尾：按画面自证的状态机（2026-10-16） ----------
#
# 为什么不再用写死的步数脚本：结果页的页数**随副本而变**（每日任务的宝物库是 2 页
# 推进会 + 战利品页，冠位战多一页）。固定脚本在冠位战上整体错位一格，把「下一步」点在
# 半路的推进会页上，等真·战利品页出来时脚本已经在点弹窗坐标了 —— 2026-10-16 真机就是
# 这样停在「获得的战利品」页的「下一步」上。现在每一步先自证（认按钮）再点。

WRAP_NEXT_BOX = (952, 607, 1267, 671)
WRAP_CLOSE_BOX = (316, 556, 571, 609)
WRAP_AGAIN_BOX = (712, 556, 967, 609)


def _wrap_pill(frame: np.ndarray, box: tuple[int, int, int, int], marks) -> None:
    """在白药丸里点几道深色横线当"文字"（模板要有方差才认得出）。"""
    left, top, right, bottom = box
    frame[top:bottom, left:right] = (250, 250, 250)
    for offset, width in marks:
        frame[top + 14 : top + 22, left + offset : left + offset + width] = (40, 40, 90)


def _wrap_page(kind: str, tint: int = 80) -> np.ndarray:
    """合成一帧结算页：results=推进会｜loot=右下「下一步 ▶」｜dialog=「连续出击」弹窗。"""
    frame = np.full((720, 1280, 3), tint, dtype=np.int16)
    frame[40:600, 200:1100] = (tint + 25, tint + 10, tint + 45)
    if kind == "loot":
        _wrap_pill(frame, WRAP_NEXT_BOX, [(150, 60), (230, 24)])
    elif kind == "dialog":
        _wrap_pill(frame, WRAP_CLOSE_BOX, [(70, 110)])
        _wrap_pill(frame, WRAP_AGAIN_BOX, [(40, 60), (140, 70)])
    return frame


def _wrap_centers() -> dict[str, tuple[int, int]]:
    def center(box: tuple[int, int, int, int]) -> tuple[int, int]:
        # 与 battle_vision.match_button 报的"模板中心"同口径（width//2 + left）
        left, top, right, bottom = box
        return (left + (right - left + 1) // 2, top + (bottom - top + 1) // 2)

    return {"next": center(WRAP_NEXT_BOX), "close": center(WRAP_CLOSE_BOX), "again": center(WRAP_AGAIN_BOX)}


def _register_wrap_buttons(*names: str) -> None:
    """把合成帧上的按钮登记成模板；搜索框收紧到按钮周边，测试才跑得快。"""
    boxes = {
        "drops_next": ("loot", WRAP_NEXT_BOX),
        "repeat_close": ("dialog", WRAP_CLOSE_BOX),
        "repeat_again": ("dialog", WRAP_AGAIN_BOX),
    }
    frames: dict[str, np.ndarray] = {}
    for name in names:
        kind, box = boxes[name]
        if kind not in frames:
            frames[kind] = _wrap_page(kind)
        left, top, right, bottom = box
        vision.save_button_template(
            name, frames[kind], box,
            search_box=(left - 20, top - 20, right + 20, bottom + 20), note="测试用合成帧",
        )


def _wrap_link(pages: list[np.ndarray]) -> CyclingLink:
    return CyclingLink(pages * 10)


def test_wrap_is_state_driven_and_ends_on_the_dialog(tmp_path, monkeypatch) -> None:
    """推进会点 (640,570)；战利品页点「下一步」按钮中心；弹窗点左「关闭」。页数多一页也不怕。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    _register_wrap_buttons("drops_next", "repeat_close", "repeat_again")
    link = _wrap_link([
        _wrap_page("results", 80), _wrap_page("results", 120),    # 推进会 1
        _wrap_page("results", 160), _wrap_page("loot", 90),       # 推进会 2 → 战利品页
        _wrap_page("loot", 130), _wrap_page("dialog", 70),        # 战利品页 → 弹窗
        _wrap_page("dialog", 60), _wrap_page("results", 200),     # 弹窗 → 回地图
    ])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="wrap-state", log=lambda _: None,
                                     settle=0.0)

    runner._do_wrap(1)

    centers = _wrap_centers()
    expected = [
        tuple(map(float, runner_mod.WRAP_ADVANCE_POINT)), tuple(map(float, runner_mod.WRAP_ADVANCE_POINT)),
        tuple(map(float, centers["next"])), tuple(map(float, centers["close"])),
    ]
    assert link.taps == expected, f"应当是 推进 → 推进 → 下一步 → 关闭：{link.taps}"
    assert tuple(map(float, centers["again"])) not in link.taps, "没开连刷就不该碰右侧「连续出击」"
    record = next(r for r in runner.records if r.kind == "wrap")
    assert record.verdict == "ok" and "未消耗 AP" in record.note


def test_wrap_repeat_clicks_the_right_button_only_when_asked(tmp_path, monkeypatch) -> None:
    """连刷的中间局点右「连续出击」；最后一局（continue_farming=False）必须点左「关闭」。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    _register_wrap_buttons("drops_next", "repeat_close", "repeat_again")
    pages = [
        _wrap_page("results", 80), _wrap_page("loot", 120),
        _wrap_page("dialog", 90), _wrap_page("results", 200),
    ]
    centers = _wrap_centers()

    last_link = _wrap_link(pages)
    last = runner_mod.BattleRunner(last_link, _layout(), run_id="wrap-last",
                                   log=lambda _: None, settle=0.0, pick_support=True, rounds=2)
    last._do_wrap(0)                      # continue_farming=False ⇒ 最后一局
    assert centers["close"] in last_link.taps and centers["again"] not in last_link.taps
    assert "未消耗 AP" in next(r for r in last.records if r.kind == "wrap").note

    mid_link = _wrap_link(pages)
    mid = runner_mod.BattleRunner(mid_link, _layout(), run_id="wrap-mid",
                                  log=lambda _: None, settle=0.0, pick_support=True, rounds=2)
    mid._do_wrap(0, continue_farming=True)
    assert centers["again"] in mid_link.taps and centers["close"] not in mid_link.taps
    assert "连续出击" in next(r for r in mid.records if r.kind == "wrap").note


def test_wrap_never_guesses_when_the_target_button_is_not_recognized(tmp_path, monkeypatch) -> None:
    """认出弹窗、但要点的那个按钮没命中 ⇒ 一个都不点（点错右侧就是白扣 40 AP）。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    _register_wrap_buttons("repeat_close")          # 故意不登记右侧「连续出击」
    link = CyclingLink([_wrap_page("dialog", 70)] * 10)
    runner = runner_mod.BattleRunner(link, _layout(), run_id="wrap-guess", log=lambda _: None,
                                     settle=0.0, repeat=True)

    runner._do_wrap(1)

    assert link.taps == [], f"判不出来就该停手：{link.taps}"
    assert not any(record.kind == "wrap" for record in runner.records)


def test_wrap_stops_after_consecutive_dead_taps(tmp_path, monkeypatch) -> None:
    """没有可认的按钮、点了也没有反应：只容忍一次动画，接着就停手。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    link = CyclingLink([np.zeros((720, 1280, 3), dtype=np.int16)])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="wrap-dead", log=lambda _: None,
                                     settle=0.0)

    runner._do_wrap(1)

    assert len(link.taps) == runner_mod.WRAP_STOP_AFTER_STILL == 2
    assert not any(record.kind == "wrap" for record in runner.records)


def _wait_action() -> plan_mod.Action:
    return plan_mod.Action(kind=plan_mod.WAIT, label="等这一回合结算完", turn=1)


# ---------- 助战选择（行结构 + 身份块指纹） ----------


SUPPORT_TINT = (90, 117, 168)


def _support_screen(top_offset: int = 0, pattern_offset: int = 0) -> np.ndarray:
    """合成一帧「助战选择」：三行青色面板，几何按真机实测
    （面板 x237-807、高度 90、**行距 200**；纯色只在上半，下半压暗模拟渐变）。
    行距统一成 200（2026-10-16）：真机两版布局都是等距（新版 200 / 旧版 200），
    旧合帧写的 186/200 不等距，会踩到"按行距吸附"那一步。
    每行「宝具行」（指纹范围）里的图案不同，用来验证指纹只认登记过的那一行。"""
    frame = np.full((720, 1280, 3), 40, dtype=np.int16)
    for index, (top, height) in enumerate(((281, 90), (481, 90), (681, 38))):
        top += top_offset
        if top >= 720:
            continue
        height = min(height, 720 - top)
        frame[top : top + height, 237:808] = SUPPORT_TINT
        frame[top + 40 : top + height, 237:808] = (70, 95, 140)          # 下半渐变
        frame[max(0, top - 98) : top, 237:808] = (60, 90, 130)           # 名字带
        shifted = index + pattern_offset
        frame[top + 46 : top + 66, 340 + 30 * shifted : 480 + 30 * shifted] = 245
    return frame


def test_support_rows_are_found_only_on_the_support_screen() -> None:
    rows = vision.find_support_rows(_support_screen())
    assert [row.index for row in rows] == [1, 2, 3]
    # 落点 = 信息面板中心（真机实测 (522,325)；合成帧右边界少一列，允许 ±1）
    assert abs(rows[0].center[0] - 522) <= 1 and rows[0].center[1] == 325
    assert rows[0].panel[0] == 237 and rows[0].panel[2] == 807
    # 指纹范围 = 面板里的「宝具 名称」那一行（相对面板 +93/+44/**-190**/+68：右边界
    # 收到「等级N」之前，2026-10-17 起；宽块布局仍是 -107）
    assert rows[0].identity == (330, 325, 617, 349)
    assert vision.find_support_rows(_attack_frame()) == [], "战斗界面不能被当成助战选择屏"
    assert vision.find_support_rows(np.zeros((720, 1280, 3), dtype=np.int16)) == []


def test_support_fingerprint_picks_the_registered_row(tmp_path, monkeypatch) -> None:
    """指纹只认登记过的那一行：同一行 ≈1.0、别的行明显低（真机实测 1.000 / 0.494 / 0.272）。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    frame = _support_screen()
    rows = vision.find_support_rows(frame)

    vision.save_support_reference("k1", frame, rows[0], note="测试")
    reference, meta = vision.load_support_reference("k1")
    assert meta["row_index"] == 1
    match = vision.match_support_row(frame, reference, rows=rows)
    assert match.accepted and match.index == 1 and match.score > 0.99
    assert match.margin > 0.2, f"与次高行要拉得开：{match.report()}"

    vision.save_support_reference("k2", frame, rows[1], note="测试")
    other, _ = vision.load_support_reference("k2")
    match2 = vision.match_support_row(frame, other, rows=rows)
    assert match2.accepted and match2.index == 2

    # 登记的那一行不在列表里（拿一张完全不同的块当指纹）⇒ 必须拒，不许硬挑了事
    stray = np.full_like(reference, 250.0)
    refused = vision.match_support_row(frame, stray, rows=rows)
    assert not refused.accepted and refused.notes


def test_support_fingerprint_accepts_duplicate_rows(tmp_path, monkeypatch) -> None:
    """两行指纹完全一样（两个好友借同一只从者）⇒ 取最上面那行，不算"分不清"。

    2026-10-14 实机遇到过：第 1、2 行的宝具行都是「环抱着你的希望之星 等级1」，只有
    玩家名/等级/留言不同。按用户口径两行都能用，取第一行即可；旧的"与次高差 ≥0.05"
    会把这种合法情形误判成"两行难分"而停手。
    """
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    frame = _support_screen()
    # 把第 2 行的**整个指纹范围**改成和第 1 行一模一样（两个好友借同一只从者的情形）
    frame[481 + 44 : 481 + 69, 330:701] = frame[281 + 44 : 281 + 69, 330:701]
    rows = vision.find_support_rows(frame)

    vision.save_support_reference("dup", frame, rows[1], note="登记第 2 行")
    reference, _ = vision.load_support_reference("dup")
    match = vision.match_support_row(frame, reference, rows=rows)
    assert match.accepted, match.report()
    assert match.index == 1, "两行一样时取最上面那行"
    assert match.margin < 0.05


def test_support_step_uses_servant_plus_craft_essence_criteria(tmp_path, monkeypatch) -> None:
    """runbook 里写了 `support: {servant, ce_names}` 时，执行器按新规则挑行。

    两行是同一只从者、不同礼装 ⇒ 由白名单决定挑哪一行（这里白名单只要第 2 行那张）。
    """
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    support = _criteria_support_screen()
    battle = _attack_frame()
    rows = vision.find_support_rows(support)
    vision.save_support_library_entry("servant", "C呆", support, rows[0].identity, note="测试")
    vision.save_support_library_entry("ce", "贝拉丽莎", support, rows[0].ce, note="测试")
    vision.save_support_library_entry("ce", "蒙娜丽莎", support, rows[1].ce, note="测试")
    link = CyclingLink([support, battle, battle])
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="criteria", log=lambda _: None, settle=0.0,
        sleeper=lambda _s: None, support_key="quest-x",
        support_criteria={"servant": "C呆", "ce_names": ["蒙娜丽莎"]},
    )

    runner._do_support(0)

    assert link.taps == [(522, 525)], f"应点第 2 行面板中心（第 1 行礼装不在白名单）：{link.taps}"
    assert runner.picked_support_row == 2
    assert runner.records[-1].verdict == "ok"


def test_support_criteria_matches_by_servant_only_when_no_ce_whitelist(tmp_path, monkeypatch) -> None:
    """礼装白名单留空 ⇒ **只按从者挑行**（冠位战用：冠位从者可戴 3 件礼装、礼装区几何不一样）。

    2026-10-16 用户口径：「冠位战里我一般只会指定从者，不会指定礼装」。
    """
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    support = _criteria_support_screen()      # 第 1、2 行同一只从者、不同礼装
    rows = vision.find_support_rows(support)
    vision.save_support_library_entry("servant", "C呆", support, rows[0].identity, note="测试")
    servant_reference = vision.load_support_library("servant")["C呆"]

    match = vision.match_support_criteria(support, servant_reference, {}, rows=rows)

    assert match.accepted and match.index == 1, match.report()
    assert "只按从者" in match.notes[0]

    # 库里没登记这只从者 ⇒ 仍然停手（"只按从者"不等于"随便挑一行"）
    other = np.full_like(servant_reference, 250.0)
    refused = vision.match_support_criteria(support, other, {}, rows=rows)
    assert not refused.accepted and "没有一行的从者指纹命中" in refused.notes[0]


def test_support_step_picks_support_by_servant_only(tmp_path, monkeypatch) -> None:
    """执行器侧：`support: {servant, ce_names: []}` 也能跑——只认从者指纹。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    support = _criteria_support_screen()
    battle = _attack_frame()
    rows = vision.find_support_rows(support)
    vision.save_support_library_entry("servant", "C呆", support, rows[0].identity, note="测试")
    link = CyclingLink([support, battle, battle])
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="servant-only", log=lambda _m: None, settle=0.0,
        sleeper=lambda _s: None, support_key="quest-grand", support_criteria={"servant": "C呆"},
    )

    runner._do_support(0)

    assert [int(x) for x, _y in link.taps] == [522], f"应点第 1 行：{link.taps}"
    assert runner.picked_support_row == 1
    assert runner.records[-1].verdict == "ok"


def test_support_step_refuses_when_criteria_library_is_missing(tmp_path, monkeypatch) -> None:
    """库里没登记过规则要的指纹 ⇒ 停手（不猜行）。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    support = _criteria_support_screen()
    link = CyclingLink([support, support, support])
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="criteria-missing", log=lambda _: None, settle=0.0,
        sleeper=lambda _s: None, support_key="quest-x",
        support_criteria={"servant": "没人登记过的从者", "ce_names": ["也没登记过"]},
    )

    try:
        runner._do_support(0)
    except runner_mod.ExecutionAbort:
        pass
    else:  # pragma: no cover - 只在护栏失效时走到
        raise AssertionError("库缺指纹时必须停手")

    assert link.taps == [], "停手时不许点任何东西"
    assert runner.records[-1].verdict == "abort"
    assert "不在库里" in runner.records[-1].note


def _criteria_support_screen() -> np.ndarray:
    """合成一帧：第 1、2 行是**同一只从者**（宝具行相同）但**不同礼装**，用于验证「从者 ∧ 礼装」。"""
    frame = np.full((720, 1280, 3), 40, dtype=np.int16)
    rng = np.random.default_rng(11)
    # 同一只从者 ⇒ 宝具行**只画一份图案**，两行都用它（真机里两个好友借同一只从者就是这样）
    upper = 281 + 44
    servant_patch = 150 + rng.integers(0, 50, size=(25, 371, 3), dtype=np.int16)
    for index, (top, height) in enumerate(((281, 90), (481, 90))):
        frame[top : top + height, 237:808] = SUPPORT_TINT
        frame[top + 40 : top + height, 237:808] = (70, 95, 140)
        frame[max(0, top - 98) : top, 237:808] = (60, 90, 130)
        frame[top + 44 : top + 69, 330:701] = servant_patch
        # 礼装条：同一亮度、但亮块位置不同（结构性差异 —— NCC 对整体明暗不敏感，
        # 只靠亮度差区分不开，必须让图案本身不同）
        ce = (46, top + 28, 230, top + height - 6)
        frame[ce[1] : ce[3] + 1, ce[0] : ce[2] + 1] = 120
        block_left = ce[0] + 8 + index * 70
        frame[ce[1] + 6 : ce[3] - 5, block_left : block_left + 55] = 235
    return frame


def test_support_criteria_picks_row_by_servant_and_craft_essence(tmp_path, monkeypatch) -> None:
    """规则：从上往下第一个「从者命中 ∧ 礼装命中白名单」的行（2026-10-15 用户口径）。

    两个好友借同一只从者、穿不同礼装时，由**白名单**决定挑哪一行；白名单里的礼装都不在场
    就停手不猜。真机回算（第 1 行登记）：命中行 从者 0.957~1.000 / 礼装 1.000，不匹配 0.25 左右。
    """
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    frame = _criteria_support_screen()
    rows = vision.find_support_rows(frame)
    assert [row.index for row in rows] == [1, 2], [(r.index, r.panel) for r in rows]

    vision.save_support_library_entry("servant", "C呆", frame, rows[0].identity, note="测试")
    vision.save_support_library_entry("ce", "贝拉丽莎", frame, rows[0].ce, note="测试")
    vision.save_support_library_entry("ce", "蒙娜丽莎", frame, rows[1].ce, note="测试")
    servants = vision.load_support_library("servant")
    ces = vision.load_support_library("ce")
    assert set(servants) == {"C呆"} and set(ces) == {"贝拉丽莎", "蒙娜丽莎"}

    first = vision.match_support_criteria(frame, servants["C呆"], {"贝拉丽莎": ces["贝拉丽莎"]}, rows=rows)
    assert first.accepted and first.index == 1, first.report()

    second = vision.match_support_criteria(frame, servants["C呆"], {"蒙娜丽莎": ces["蒙娜丽莎"]}, rows=rows)
    assert second.accepted and second.index == 2, second.report()

    both = vision.match_support_criteria(
        frame, servants["C呆"], {"贝拉丽莎": ces["贝拉丽莎"], "蒙娜丽莎": ces["蒙娜丽莎"]}, rows=rows)
    assert both.accepted and both.index == 1, "白名单命中多行时取最上面那行"

    missing = vision.match_support_criteria(
        frame, servants["C呆"], {"别的礼装": np.full_like(ces["贝拉丽莎"], 250.0)}, rows=rows)
    assert not missing.accepted and missing.notes, "白名单里的礼装都不在场 ⇒ 停手，不许硬挑"


def _register(link: CyclingLink, **kwargs):
    """跑一次登记（零点击）；默认把等待与日志收掉，测试里不真的 sleep / 刷屏。"""
    kwargs.setdefault("sleeper", lambda _s: None)
    kwargs.setdefault("log", lambda _m: None)
    return link, runner_mod.register_support(link, **kwargs)


def test_register_support_saves_fingerprints_without_tapping_anything(tmp_path, monkeypatch) -> None:
    """登记模式：只截图 + 存指纹，**一下都不点**（所以不花 AP、不改游戏状态）。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    link, report = _register(
        CyclingLink([_support_screen()]),
        row=2, servant_name="C呆", ce_specs=["贝拉丽莎"], run_id="register-1",
    )

    assert link.taps == [] and link.swipes == [], "登记绝不能点任何东西"
    assert report["ok"] is True and report["row"] == 2 and report["rows_seen"] == 3
    assert [item["name"] for item in report["saved"]] == ["C呆", "贝拉丽莎"]
    assert (tmp_path / "runs" / "register-1").is_dir(), "要留一张现场截图当证据"

    # 读回库来核对：名字对得上、图也存住了
    assert "C呆" in vision.load_support_library("servant")
    assert "贝拉丽莎" in vision.load_support_library("ce")
    # 自证判别力：指的那一行 ≈1.0，别的行明显低（否则登记了也没法用来自动挑行）
    detail = report["discrimination"]["从者 C呆"]
    assert detail["2"] > 0.99, detail
    assert detail["1"] < 0.85 and detail["3"] < 0.85, detail


def test_register_support_can_take_the_craft_essence_from_another_row(tmp_path, monkeypatch) -> None:
    """`礼装名:行号` 允许礼装取自另一行（两行同一从者、不同礼装时按需登记）。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    link, report = _register(
        CyclingLink([_criteria_support_screen()]), row=2, servant_name="C呆",
        ce_specs=["蒙娜丽莎", "贝拉丽莎:1"], run_id="register-2",
    )

    assert link.taps == []
    assert [(item["name"], item["source_row"]) for item in report["saved"]] == [
        ("C呆", 2), ("蒙娜丽莎", 2), ("贝拉丽莎", 1),
    ]
    by_row = report["discrimination"]["礼装 贝拉丽莎"]
    assert by_row["1"] > 0.99 and by_row["2"] < 0.85, by_row
    other = report["discrimination"]["礼装 蒙娜丽莎"]
    assert other["2"] > 0.99 and other["1"] < 0.85, other
    assert set(vision.load_support_library("ce")) == {"贝拉丽莎", "蒙娜丽莎"}


def test_register_support_stops_outside_the_support_screen(tmp_path, monkeypatch) -> None:
    """不在助战屏上 ⇒ 停手说清原因，不写任何指纹、不点任何东西。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    link = CyclingLink([_attack_frame()])
    with pytest.raises(runner_mod.ExecutionAbort, match="不是「助战选择」屏"):
        _register(link, row=1, servant_name="C呆", run_id="register-3", tries=1)

    assert link.taps == []
    assert not (tmp_path / "templates" / "support" / "servant").exists()


def test_register_support_stops_on_an_out_of_range_row(tmp_path, monkeypatch) -> None:
    """行号越界 ⇒ 全部拒掉（连已经在计划里的也别写半个），一下都不点。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    link = CyclingLink([_support_screen()])          # 只有 3 行
    with pytest.raises(runner_mod.ExecutionAbort, match="行号不在里面"):
        _register(link, row=5, servant_name="C呆",
                  ce_specs=["贝拉丽莎:2"], run_id="register-4", tries=1)

    assert link.taps == []
    assert not (tmp_path / "templates" / "support" / "servant").exists()
    assert not (tmp_path / "templates" / "support" / "ce").exists()


def test_register_support_requires_at_least_one_name(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    link = CyclingLink([_support_screen()])
    with pytest.raises(runner_mod.ExecutionAbort, match="至少一个名字"):
        _register(link, row=1, run_id="register-5", tries=1)
    assert link.taps == []


def test_register_support_cli_needs_no_spec_and_reports_json(tmp_path, monkeypatch, capsys) -> None:
    """CLI 打开方式：`--register-support` 不需要 spec/layout，且**永不带 --execute** 的语义
    （登记模式压根不点）；结果以 `REGISTER_REPORT {json}` 一行回给后端。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    link = CyclingLink([_support_screen()])
    monkeypatch.setattr(runner_mod, "DeviceLink", lambda *a, **k: link)
    monkeypatch.setattr(runner_mod.DeviceLease, "acquire", lambda self: True)
    monkeypatch.setattr(runner_mod.DeviceLease, "release", lambda self: None)

    code = runner_mod.main([
        "--register-support", "--support-row", "2", "--servant", "C呆", "--ce", "贝拉丽莎",
    ])

    assert code == 0
    assert link.taps == []
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("REGISTER_REPORT "))
    payload = json.loads(line[len("REGISTER_REPORT "):])
    assert payload["ok"] is True and payload["rows_seen"] == 3
    assert [item["name"] for item in payload["saved"]] == ["C呆", "贝拉丽莎"]


def _textured_support_screen() -> np.ndarray:
    """和 `_support_screen` 同几何，但每行「宝具行」里放**高频纹理**——位移 1-2 像素分数就会明显掉，
    用来复现 2026-10-15 真机那个「只偏 (1,0) 却认不出来」的场景。"""
    frame = np.full((720, 1280, 3), 40, dtype=np.int16)
    rng = np.random.default_rng(7)
    for index, (top, height) in enumerate(((281, 90), (467, 90), (667, 53))):
        frame[top : top + height, 237:808] = SUPPORT_TINT
        frame[top + 40 : top + height, 237:808] = (70, 95, 140)
        frame[max(0, top - 98) : top, 237:808] = (60, 90, 130)
        left, upper, right, lower = 330, top + 44, 700, min(top + 68, 719)
        if upper > 719:
            continue
        texture = rng.integers(0, 60, size=(lower - upper + 1, right - left + 1, 3), dtype=np.int16)
        frame[upper : lower + 1, left : right + 1] = 150 + texture
    return frame


def test_support_fingerprint_tolerates_a_few_pixels_of_shift(tmp_path, monkeypatch) -> None:
    """真机 2026-10-15：连续出击那条路上，同一行的指纹块相对登记位置只偏 (1, 0) 像素，
    旧实现只试 0/±3 这 9 个格点 ⇒ 最高 0.794 < 0.85 门槛 ⇒ 被当成"找不到"而停手。
    改成逐像素搜 ±6 之后，偏移 (2, 2) 也要能稳定认出来。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    frame = _textured_support_screen()
    rows = vision.find_support_rows(frame)
    assert [row.index for row in rows] == [1, 2, 3]
    vision.save_support_reference("shifted", frame, rows[0], note="测试：位移容忍")
    reference, _ = vision.load_support_reference("shifted")

    moved = frame.copy()
    for row in rows:
        left, upper, right, lower = row.identity
        pad = 8                       # 外扩一圈再整体平移，保证精确对齐点落在被平移的区域内
        outer = (max(0, left - pad), max(0, upper - pad),
                 min(frame.shape[1] - 3, right + pad), min(frame.shape[0] - 3, lower + pad))
        moved[outer[1] : outer[3] + 1, outer[0] : outer[2] + 1] = \
            frame[outer[1] + 2 : outer[3] + 3, outer[0] + 2 : outer[2] + 3]

    match = vision.match_support_row(moved, reference, rows=vision.find_support_rows(moved))
    assert match.accepted, match.report()
    assert match.index == 1
    assert match.score > 0.97, f"偏移 (2,2) 应几乎完全命中：{match.report()}"


def test_support_step_taps_the_panel_and_waits_for_the_battle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    support = _support_screen()
    battle = _attack_frame()
    link = CyclingLink([support, battle, battle])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="support", log=lambda _: None,
                                     settle=0.0, sleeper=lambda _s: None, support_key="quest-x",
                                     support_row=1)

    runner._do_support(0)

    assert link.taps == [(522, 325)], "只点第 1 行信息面板中心一次"
    assert runner.records[-1].verdict == "ok"
    assert runner.picked_support_row == 1
    assert (tmp_path / "templates" / "support" / "quest-x.json").exists(), "指纹要落盘"


def test_support_step_uses_the_registered_fingerprint(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    support = _support_screen()
    battle = _attack_frame()
    # 第一次：登记第 2 行
    first = runner_mod.BattleRunner(CyclingLink([support, battle, battle]), _layout(),
                                    run_id="support-first", log=lambda _: None, settle=0.0,
                                    sleeper=lambda _s: None, support_key="quest-y", support_row=2)
    first._do_support(0)
    assert first.picked_support_row == 2
    # 第二次：不给行号，靠指纹自己认回来
    second = runner_mod.BattleRunner(CyclingLink([support, battle, battle]), _layout(),
                                     run_id="support-second", log=lambda _: None, settle=0.0,
                                     sleeper=lambda _s: None, support_key="quest-y")
    second._do_support(0)
    assert second.picked_support_row == 2


def test_support_step_stops_when_it_cannot_tell_which_row(tmp_path, monkeypatch) -> None:
    """没登记过指纹 ⇒ 停手，绝不"取最上面那行"顶上（那会白打一次 40 AP）。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    link = CyclingLink([_support_screen()])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="support-none", log=lambda _: None,
                                     support_key="never-registered")

    with pytest.raises(runner_mod.ExecutionAbort, match="没登记|指纹"):
        runner._do_support(0)

    assert link.taps == []


def _ap_restore_menu_frame() -> np.ndarray:
    """合成「行动力回复」菜单（高对比面板），用来验证 AP 保护能认出这一屏。"""
    frame = np.full((720, 1280, 3), 30, dtype=np.int16)
    frame[250:400, 280:1010] = 210
    frame[300:360, 470:800] = 90
    return frame


def test_support_step_scrolls_down_to_find_the_row(tmp_path, monkeypatch) -> None:
    """目标行不在当前可见范围 ⇒ 往下翻页找（每翻一次都重新自证），找到就点它。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    target = _support_screen()                      # 目标行在第 1 行
    other = _support_screen(pattern_offset=3)       # 翻页前：可见的是别的行（指纹不匹配）
    vision.save_support_reference("quest-scroll", target, vision.find_support_rows(target)[0],
                                  note="测试")
    # ① 首屏（别的行）②③ 先滑回最上面（画面不动=已在顶）④ 往下翻一屏看到目标行 ⑤ 点完进本
    link = CyclingLink([other, other, other, target, _attack_frame(), _attack_frame()])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="support-scroll", log=lambda _: None,
                                     settle=0.0, sleeper=lambda _s: None, support_key="quest-scroll")

    runner._do_support(0)

    assert len(link.swipes) == runner_mod.SUPPORT_SCROLL_STILL_TRIES + 1, (
        f"先回顶两次（已在上方就不动）+ 往下翻一屏：{link.swipes}"
    )
    assert len(link.taps) == 1 and link.taps[0][0] == 522, "找到后点那一行的面板中心"
    assert runner.picked_support_row == 1


def test_support_step_stops_after_scrolling_without_finding(tmp_path, monkeypatch) -> None:
    """翻完规定次数还是没有 ⇒ 停手（不点、也不猜），并提示可以刷新列表。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    target = _support_screen()
    other = _support_screen(pattern_offset=3)
    vision.save_support_reference("quest-scroll2", target, vision.find_support_rows(target)[0],
                                  note="测试")
    link = CyclingLink([other])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="support-scroll2", log=lambda _: None,
                                     settle=0.0, sleeper=lambda _s: None, support_key="quest-scroll2")

    with pytest.raises(runner_mod.ExecutionAbort, match="翻"):
        runner._do_support(0)

    assert link.taps == [], "找不到就一下都不能点"
    assert len(link.swipes) == 2 * runner_mod.SUPPORT_SCROLL_STILL_TRIES, (
        "回顶连续两次不动 + 往下连续两次不动（到底）；不该继续空翻"
    )


# ---------- 「优先冠位从者」是**整张列表**级别的口径（2026-10-16 用户澄清） ----------
#
# 用户原话："我说优先选择冠位从者杀狐，是希望助战列表首屏没有的话就往下翻，一直到底部
# 都没有的话就选个普通杀狐"。⇒ 首屏只有普通杀狐时**不能**就地定下来，要翻到底；
# 一路都没有冠位，才翻回最上面用普通杀狐。

GRAND_LABEL_FRAME = {"left": 286, "right": 229, "top": 71, "bottom": 88}


def _grand_support_screen(
    kinds: tuple[str, ...] = ("plain", "grand"), pattern_variant: int = 0
) -> np.ndarray:
    """合成一帧助战屏：`kinds` 里每项一行，`plain` = 窄块（普通助战）、`grand` = 宽块（冠位从者）。

    「宝具行」的图案按**框宽的比例**画，所以同一个从者指纹在两版布局里都能命中
    （真机上就是靠 ±40 px 的横移搜索兜住的）；`grand` 行在肖像底部画一条「冠位从者」标签。
    """
    frame = np.full((720, 1280, 3), 40, dtype=np.int16)
    for order, kind in enumerate(kinds):
        width = 570 if kind == "plain" else 427
        left, right = (237, 237 + width) if kind == "plain" else (386, 386 + width)
        top = 281 + 200 * order
        panel = (left, top, right - 1, top + 89)
        frame[top : top + 90, left:right] = SUPPORT_TINT
        frame[top + 40 : top + 90, left:right] = (70, 95, 140)
        frame[top - 98 : top, left:right] = (60, 90, 130)
        identity = vision.support_identity_box(panel, "narrow" if kind == "plain" else "wide")
        span = identity[2] - identity[0]
        fractions = (
            ((0.16, 0.18), (0.48, 0.20), (0.78, 0.14))
            if pattern_variant == 0
            else ((0.05, 0.20), (0.42, 0.30), (0.86, 0.10))
        )
        for start_fraction, width_fraction in fractions:
            x0 = int(identity[0] + span * start_fraction)
            x1 = int(identity[0] + span * (start_fraction + width_fraction))
            frame[identity[1] + 3 : identity[3] - 2, x0:x1] = 245
        if kind == "grand":
            label = vision.support_grand_label_box(panel)
            frame[label[1] : label[3] + 1, label[0] : label[2] + 1] = (30, 40, 60)
            span_label = label[2] - label[0]
            frame[label[1] + 3 : label[3] - 2, label[0] + 8 : label[0] + span_label - 8] = 240
    return frame


def _register_grand_library(frame: np.ndarray, screen_kind: tuple[str, ...]) -> None:
    """把这一帧的「冠位从者」标签 + 从者指纹（取自第一条 grand 行）登记进指纹库。"""
    rows = vision.find_support_rows(frame)
    grand_row = next(row for row, kind in zip(rows, screen_kind) if kind == "grand")
    vision.save_support_library_entry(
        "grand", "冠位从者", frame, vision.support_grand_label_box(grand_row.panel), note="测试"
    )
    vision.save_support_library_entry(
        "servant", "杀狐", frame, grand_row.identity, note="测试"
    )


def test_support_identity_box_excludes_the_noble_phantasm_level() -> None:
    """指纹框必须**不含「等级N」**（2026-10-17 真机：好友把宝具升到等级2/4 ⇒ 同一只从者 0.15）。

    真机像素：窄块那行文字 ≈x340-613、`等级N` 在 x≈620-680（面板 237..807）；宽块文字
    ≈476-720、`等级N` 在 731 之后（面板 386..813）。所以窄块右边界收到面板右 -190、宽块 -107。
    """
    narrow_panel = (237, 281, 807, 370)
    wide_panel = (386, 181, 813, 270)
    narrow_box = vision.support_identity_box(narrow_panel, "narrow")
    wide_box = vision.support_identity_box(wide_panel, "wide")
    assert narrow_box[2] == 807 - 190 < 620, f"窄块框右边界必须收在「等级N」之前：{narrow_box}"
    assert wide_box[2] == 813 - 107 < 731, f"宽块框右边界必须收在「等级N」之前：{wide_box}"
    # 默认参数 = 窄块（老调用方不会悄悄换成宽块的框）
    assert vision.support_identity_box(narrow_panel) == narrow_box


def test_support_grand_only_never_settles_for_a_plain_row_on_this_screen(tmp_path, monkeypatch) -> None:
    """`prefer_grand` ⇒ **只认冠位**：同一屏里有普通行也不算数，只把它记进 `plain` 交给调用方。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    kinds = ("plain", "grand")
    frame = _grand_support_screen(kinds)
    rows = vision.find_support_rows(frame)
    assert [row.variant for row in rows] == ["narrow", "wide"], [(r.index, r.variant) for r in rows]
    _register_grand_library(frame, kinds)
    reference = vision.load_support_library("servant")["杀狐"]
    assert vision.support_row_is_grand(frame, rows[1])
    assert not vision.support_row_is_grand(frame, rows[0])

    # 不指定冠位 ⇒ 仍然是"从上往下第一个命中"（第 1 行的普通杀狐）
    plain = vision.match_support_criteria(frame, reference, {}, rows=rows)
    assert plain.accepted and plain.index == 1, plain.report()

    # 指定冠位 ⇒ 只认第 2 行；普通行的候选记在 plain 里，**不 accepted**
    grand = vision.match_support_criteria(frame, reference, {}, rows=rows, prefer_grand=True)
    assert grand.accepted and grand.index == 2, grand.report()

    plain_only = _grand_support_screen(("plain", "plain"))
    only_rows = vision.find_support_rows(plain_only)
    refused = vision.match_support_criteria(plain_only, reference, {}, rows=only_rows, prefer_grand=True)
    assert not refused.accepted, refused.report()
    assert refused.plain is not None and refused.plain[0] == 1, refused.plain
    assert any("不是冠位从者" in note for note in refused.notes), refused.notes


def test_support_step_scrolls_past_a_plain_row_to_find_a_grand_one(tmp_path, monkeypatch) -> None:
    """用户口径的核心场景：首屏只有普通杀狐 ⇒ 往下翻，第 2 屏找到冠位杀狐就点它。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    kinds = ("plain", "grand")
    screen = _grand_support_screen(kinds)
    _register_grand_library(screen, kinds)
    plain_screen = _grand_support_screen(("plain", "plain"))
    battle = _attack_frame()
    # 列表 = 位置 0（普通杀狐）、位置 1（普通杀狐）、位置 2（含冠位杀狐）
    link = ScrollingLink([plain_screen, plain_screen, screen], battle)
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="support-grand-scroll", log=lambda _m: None, settle=0.0,
        sleeper=lambda _s: None, support_key="quest-grand-scroll",
        support_criteria={"servant": "杀狐", "prefer_grand": True},
    )

    runner._do_support(0)

    grand_row = vision.find_support_rows(screen)[1]
    assert len(link.swipes) >= runner_mod.SUPPORT_SCROLL_STILL_TRIES + 1, f"必须真的往下翻：{link.swipes}"
    assert [int(x) for x, _y in link.taps] == [grand_row.center[0]], f"应点冠位那一行：{link.taps}"
    assert runner.picked_support_row == 2
    assert runner.records[-1].verdict == "ok"


def test_support_step_falls_back_to_a_plain_row_only_after_the_whole_list(tmp_path, monkeypatch) -> None:
    """翻到底都没有冠位 ⇒ 翻回最上面，用普通行（并把这件事写进证据）。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    kinds = ("plain", "grand")
    screen = _grand_support_screen(kinds)
    _register_grand_library(screen, kinds)          # 库里有冠位模板，但这一帧里一只冠位都没有
    plain_screen = _grand_support_screen(("plain", "plain"))
    battle = _attack_frame()
    # 整张列表只有两屏普通杀狐、没有冠位
    link = ScrollingLink([plain_screen, plain_screen], battle)
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="support-grand-fallback", log=lambda _m: None, settle=0.0,
        sleeper=lambda _s: None, support_key="quest-grand-fallback",
        support_criteria={"servant": "杀狐", "prefer_grand": True},
    )

    runner._do_support(0)

    plain_row = vision.find_support_rows(plain_screen)[0]
    assert len(link.swipes) >= 3 * runner_mod.SUPPORT_SCROLL_STILL_TRIES, f"翻到底再翻回顶：{link.swipes}"
    assert [int(x) for x, _y in link.taps] == [plain_row.center[0]]
    note = runner.records[-1].note
    assert "退回普通行" in note, note


def test_support_step_remembers_a_plain_candidate_from_the_first_screen(tmp_path, monkeypatch) -> None:
    """普通杀狐只在**首屏**出现、后面几屏没有 ⇒ 翻到底之后仍要能退回它。

    2026-10-17 真机就栽在这：只认"当前这一屏 match.plain"的话，翻到底时最后几屏没有杀狐，
    于是明明首屏有一只普通杀狐也报"找不到"。
    """
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    kinds = ("plain", "grand")
    screen = _grand_support_screen(kinds)
    _register_grand_library(screen, kinds)
    plain_screen = _grand_support_screen(("plain", "plain"))
    stranger = _grand_support_screen(("plain", "plain"), pattern_variant=1)   # 后面几屏没有杀狐
    battle = _attack_frame()
    # 普通杀狐只在最上面那屏，后面两屏都没有
    link = ScrollingLink([plain_screen, stranger, stranger], battle)
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="support-plain-remember", log=lambda _m: None, settle=0.0,
        sleeper=lambda _s: None, support_key="quest-plain-remember",
        support_criteria={"servant": "杀狐", "prefer_grand": True},
    )

    runner._do_support(0)

    plain_row = vision.find_support_rows(plain_screen)[0]
    assert [int(x) for x, _y in link.taps] == [plain_row.center[0]]
    assert "退回普通行" in runner.records[-1].note


def test_support_step_stops_when_the_list_has_neither_grand_nor_plain(tmp_path, monkeypatch) -> None:
    """整张列表都没有要的从者 ⇒ 停手、一下都不点。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    kinds = ("plain", "grand")
    screen = _grand_support_screen(kinds)
    _register_grand_library(screen, kinds)
    stranger = _grand_support_screen(("plain", "plain"), pattern_variant=1)   # 图案不同 ⇒ 不命中
    link = ScrollingLink([stranger, stranger], _attack_frame())
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="support-grand-none", log=lambda _m: None, settle=0.0,
        sleeper=lambda _s: None, support_key="quest-grand-none",
        support_criteria={"servant": "杀狐", "prefer_grand": True},
    )

    with pytest.raises(runner_mod.ExecutionAbort, match="翻"):
        runner._do_support(0)

    assert link.taps == []


def test_support_step_reports_ap_shortage_instead_of_guessing(tmp_path, monkeypatch) -> None:
    """AP 不够时游戏不肯进本、而是弹「行动力回复」菜单 ⇒ 停手并说清原因，一下都不许点。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    menu = _ap_restore_menu_frame()
    vision.save_button_template("ap_apple_gold", menu, (300, 280, 900, 380),
                                search_box=(280, 250, 1010, 400), note="测试")
    link = CyclingLink([menu])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="ap-guard", log=lambda _: None,
                                     support_key="k")

    with pytest.raises(runner_mod.ExecutionAbort, match="行动力回复"):
        runner._do_support(0)

    assert link.taps == [], "AP 不够时一下都不能点"


def test_support_step_stops_outside_the_support_screen(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    link = CyclingLink([_attack_frame()])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="support-wrong-screen",
                                     log=lambda _: None, support_key="k")

    with pytest.raises(runner_mod.ExecutionAbort, match="不是「助战选择」屏"):
        runner._do_support(0)

    assert link.taps == []


# ---------- 固定按钮模板（「队伍确认」→「开始任务」） ----------


def _party_confirm_frame() -> np.ndarray:
    """合成「队伍确认」屏：右下角画一个高对比的「开始任务」按钮。"""
    frame = np.full((720, 1280, 3), 30, dtype=np.int16)
    frame[630:710, 1070:1265] = 235
    frame[648:692, 1100:1240] = 150
    return frame


def _register_start_quest_button(frame: np.ndarray) -> None:
    vision.save_button_template("start_quest", frame, (1070, 630, 1264, 710),
                                search_box=(1010, 612, 1279, 719), note="测试")


FRIEND_CLOSE_BOX = (190, 585, 480, 665)


def _friend_request_frame() -> np.ndarray:
    """合成非好友助战的「是否发送好友申请？」弹窗：左侧白色「结束」药丸。"""
    frame = np.full((720, 1280, 3), 55, dtype=np.int16)
    frame[250:520, 80:1200] = (120, 130, 150)
    _wrap_pill(frame, FRIEND_CLOSE_BOX, [(115, 45), (175, 45)])
    _wrap_pill(frame, (800, 585, 1090, 665), [(40, 50), (120, 70)])
    return frame


def _register_friend_close_button(frame: np.ndarray) -> None:
    vision.save_button_template(
        "friend_request_close", frame, FRIEND_CLOSE_BOX,
        search_box=(120, 550, 620, 700), note="测试：非好友助战弹窗左「结束」",
    )


def test_button_template_matches_only_where_it_is(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    party = _party_confirm_frame()
    _register_start_quest_button(party)

    here = vision.match_button(party, "start_quest")
    assert here.accepted and here.score > 0.99
    assert here.center == (1167, 670), "落点必须来自匹配位置"

    assert not vision.match_button(_support_screen(), "start_quest").accepted
    assert not vision.match_button(np.zeros((720, 1280, 3), dtype=np.int16), "start_quest").accepted

    # 没登记过模板时不能崩，也不能当成"找到了"
    missing = vision.match_button(party, "never-registered")
    assert not missing.accepted and missing.notes and missing.center is None


def test_support_step_also_presses_start_quest_on_party_confirm(tmp_path, monkeypatch) -> None:
    """从地图手动进本时，选完助战会回到「队伍确认」，还要补点「开始任务」才进本。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    party = _party_confirm_frame()
    _register_start_quest_button(party)
    link = CyclingLink([_support_screen(), party, _attack_frame(), _attack_frame()])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="support-party", log=lambda _: None,
                                     settle=0.0, sleeper=lambda _s: None, support_key="quest-z",
                                     support_row=1)

    runner._do_support(0)

    assert link.taps == [(522, 325), (1167, 670)], "先点助战行，再点「开始任务」"
    record = next(r for r in runner.records if r.kind == "support")
    assert record.verdict == "ok" and "开始任务" in record.note


def test_support_step_dismisses_friend_request_then_presses_start_quest(tmp_path, monkeypatch) -> None:
    """非好友助战会先弹「是否发送好友申请？」：点左「结束」，再点「开始任务」。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    friend = _friend_request_frame()
    _register_friend_close_button(friend)
    party = _party_confirm_frame()
    _register_start_quest_button(party)
    link = CyclingLink([_support_screen(), friend, party, _attack_frame(), _attack_frame()])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="support-friend", log=lambda _: None,
                                     settle=0.0, sleeper=lambda _s: None, support_key="quest-z",
                                     support_row=1)

    runner._do_support(0)

    assert link.taps == [(522, 325), (335, 625), (1167, 670)]
    assert any(record.kind == "friend_request_close" for record in runner.records)
    record = next(r for r in runner.records if r.kind == "support")
    assert record.verdict == "ok" and "开始任务" in record.note


def test_wrap_dismisses_friend_request_before_the_repeat_dialog(tmp_path, monkeypatch) -> None:
    """收尾时撞上好友申请弹窗：先点「结束」，再按单局意图点「关闭」。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    friend = _friend_request_frame()
    _register_friend_close_button(friend)
    _register_wrap_buttons("repeat_close")
    link = _wrap_link([friend, _wrap_page("dialog", 70), _wrap_page("results", 200)])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="wrap-friend", log=lambda _: None,
                                     settle=0.0)

    runner._do_wrap(1)

    centers = _wrap_centers()
    assert link.taps == [(335, 625), centers["close"]]
    assert any(record.kind == "friend_request_close" for record in runner.records)


# ---------- 冷启动（--enter-quest）与连刷（--rounds） ----------


def _map_frame_with_card() -> np.ndarray:
    """合成每日任务地图：右上一张高对比的关卡卡片（横向暗条 ×3，结构上独占）。"""
    frame = np.full((720, 1280, 3), 25, dtype=np.int16)
    frame[110:320, 600:1250] = 200
    frame[130:158, 620:1230] = 60
    frame[196:224, 620:1230] = 60
    frame[262:290, 620:1230] = 60
    return frame


def _paint_ap_bar(frame: np.ndarray, ap: int) -> np.ndarray:
    """在合成帧上画行动力条：左端按 AP 比例填绿，其余留黑（和真机一致：空槽纯黑）。"""
    left, right = vision.AP_BAR_LEFT, vision.AP_BAR_RIGHT
    fill_end = int(round(vision.AP_BAR_ZERO_X + ap * vision.AP_BAR_PX_PER_AP))
    fill_end = min(fill_end, right)
    frame[vision.AP_BAR_Y - 4 : vision.AP_BAR_Y + 5, left : right + 1] = 0
    frame[vision.AP_BAR_Y - 4 : vision.AP_BAR_Y + 5, left : fill_end + 1] = (20, 200, 30)
    return frame


def test_ap_reading_retries_once_after_a_blank_frame(tmp_path, monkeypatch) -> None:
    """收工那次读数撞上全黑转场帧时，等 2 秒重读一次（2026-10-15 真机就是这样丢的数）。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    blank = np.zeros((720, 1280, 3), dtype=np.int16)
    good = _paint_ap_bar(np.full((720, 1280, 3), 25, dtype=np.int16), 100)
    waits: list[float] = []
    link = CyclingLink([blank, good])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="ap-retry",
                                     log=lambda _m: None, sleeper=waits.append)

    reading = runner._read_ap_record("收工", "done")

    assert reading is not None and reading.readable
    assert reading.estimate is not None and abs(reading.estimate - 100) <= 2
    assert waits == [runner_mod.AP_READ_RETRY_WAIT], "只重读一次"
    assert [record.kind for record in runner.records] == ["ap"], "重读成功也只记一条读数"


def test_ap_reading_survives_a_long_transition(tmp_path, monkeypatch) -> None:
    """转场黑帧不占"读数失败"的额度：连吃 4 张黑帧之后读到地图屏，读数仍然成立。

    2026-10-16 真机：收尾点完「关闭」回地图要跨 4-6 秒转场，旧实现里黑帧会把 4 次重读
    额度吃光，AP 账目就缺一条（`run-20261015-125011` 收工那次）。
    """
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    blank = np.zeros((720, 1280, 3), dtype=np.int16)
    good = _paint_ap_bar(np.full((720, 1280, 3), 25, dtype=np.int16), 41)
    waits: list[float] = []
    link = CyclingLink([blank, blank, blank, blank, good])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="ap-transition",
                                     log=lambda _m: None, sleeper=waits.append)

    reading = runner._read_ap_record("收工", "done")

    assert reading is not None and reading.readable
    assert reading.estimate is not None and abs(reading.estimate - 41) <= 2
    assert len(waits) == 4, "黑帧只是等一下再看，不该算成读数失败"
    assert [record.kind for record in runner.records] == ["ap"]


def test_ap_reading_gives_up_after_the_retry_without_breaking_the_run(tmp_path, monkeypatch) -> None:
    """全是全黑转场帧 ⇒ 不当作"读数失败"反复白读，而是**记一条说清原因的证据**再放弃。

    2026-10-16 实测：收尾点完左「关闭」后连拍两张 luma≈0 的黑帧，两次尝试都被浪费掉。
    """
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    blank = np.zeros((720, 1280, 3), dtype=np.int16)
    waits: list[float] = []
    runner = runner_mod.BattleRunner(CyclingLink([blank]), _layout(), run_id="ap-retry-fail",
                                     log=lambda _m: None, sleeper=waits.append)

    reading = runner._read_ap_record("收工", "done")

    assert reading is None, "全黑帧不该被当成一次成功/失败读数"
    assert len(waits) == runner_mod.AP_READ_BLANK_TRIES, "每次跳黑帧都等一下再看（转场额度独立）"
    assert runner.records[-1].kind == "ap"
    assert "全黑转场" in runner.records[-1].note, runner.records[-1].note


# ---------- 补给（黄金果实）：消耗道具，必须三道自证 ----------
#
# 2026-10-14 立的口径（当时在旧执行器里做、2026-10-16 接回本执行器）：① ＋ 入口自证；
# ② 菜单里**黄金果实那一行**自证（搜索框结构上不含最上面的圣晶石行）；③ 确认弹窗要同时
# 认出标题「消耗1个黄金果实」与「决定」按钮。少认一个就停手——宁可没补上，绝不错耗道具。

APPLE_ENTRY_BOX = (146, 674, 194, 716)
APPLE_ROW_BOX = (315, 268, 800, 368)
APPLE_CONFIRM_TEXT_BOX = (480, 200, 812, 240)
APPLE_CONFIRM_OK_BOX = (712, 538, 974, 594)


def _box_center_x(box: tuple[int, int, int, int]) -> int:
    """与 battle_vision.match_button 报的"模板中心横坐标"同口径。"""
    left, _top, right, _bottom = box
    return left + (right - left + 1) // 2


def _apple_map_frame(tint: int = 40) -> np.ndarray:
    frame = np.full((720, 1280, 3), tint, dtype=np.int16)
    _wrap_pill(frame, APPLE_ENTRY_BOX, [(10, 30)])              # 「行动力」行里的 ＋
    return _paint_ap_bar(frame, 65)


def _apple_menu_frame(gold: bool = True) -> np.ndarray:
    """补给菜单：最上面一行是**圣晶石**（危险项），黄金果实在它下面。"""
    frame = np.full((720, 1280, 3), 45, dtype=np.int16)
    frame[150:250, 300:1000] = (90, 90, 150)                    # 圣晶石行（绝不该被点）
    if gold:
        _wrap_pill(frame, APPLE_ROW_BOX, [(40, 120), (200, 90)])
    return frame


def _apple_confirm_frame(title: bool = True, ok: bool = True) -> np.ndarray:
    frame = np.full((720, 1280, 3), 50, dtype=np.int16)
    if title:
        _wrap_pill(frame, APPLE_CONFIRM_TEXT_BOX, [(30, 150), (220, 110)])
    if ok:
        _wrap_pill(frame, APPLE_CONFIRM_OK_BOX, [(60, 80)])
    return frame


def _register_apple_templates(*names: str) -> None:
    boxes = {
        "ap_restore": (_apple_map_frame(), APPLE_ENTRY_BOX),
        "ap_apple_gold": (_apple_menu_frame(), APPLE_ROW_BOX),
        "ap_apple_confirm_text": (_apple_confirm_frame(), APPLE_CONFIRM_TEXT_BOX),
        "ap_confirm_ok": (_apple_confirm_frame(), APPLE_CONFIRM_OK_BOX),
    }
    for name in names:
        frame, box = boxes[name]
        left, top, right, bottom = box
        vision.save_button_template(
            name, frame, box,
            search_box=(left - 20, top - 20, right + 20, bottom + 20), note="测试用合成帧",
        )


def test_apple_supply_walks_the_three_self_checks(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    _register_apple_templates("ap_restore", "ap_apple_gold", "ap_apple_confirm_text", "ap_confirm_ok")
    map_frame = _apple_map_frame()
    link = CyclingLink([map_frame, _apple_menu_frame(), _apple_confirm_frame(),
                        _apple_map_frame(50), _apple_map_frame(60)])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="apple", log=lambda _: None,
                                     settle=0.0, sleeper=lambda _s: None)

    used = runner.use_apple(1)

    assert used == 1
    assert [int(x) for x, _y in link.taps] == [
        _box_center_x(APPLE_ENTRY_BOX),          # 「行动力」行里的 ＋
        _box_center_x(APPLE_ROW_BOX),            # 黄金果实那一行
        _box_center_x(APPLE_CONFIRM_OK_BOX),     # 确认弹窗的「决定」
    ], f"应当只点 入口 → 黄金果实行 → 决定：{link.taps}"
    record = next(r for r in runner.records if r.kind == "apple")
    assert "黄金果实" in record.label and "三道自证" in record.note
    assert any(r.kind == "ap" for r in runner.records), "补完要读一次行动力留证据"


def test_apple_supply_retries_after_a_blank_transition(tmp_path, monkeypatch) -> None:
    """关闭连续出击弹窗后先拍到黑帧：等转场再认「行动力 ＋」，不能一次判死。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    _register_apple_templates("ap_restore", "ap_apple_gold", "ap_apple_confirm_text", "ap_confirm_ok")
    blank = np.zeros((720, 1280, 3), dtype=np.int16)
    link = CyclingLink([
        blank,
        _apple_map_frame(),
        _apple_menu_frame(),
        _apple_confirm_frame(),
        _apple_map_frame(50),
        _apple_map_frame(60),
    ])
    waits: list[float] = []
    runner = runner_mod.BattleRunner(link, _layout(), run_id="apple-transition",
                                     log=lambda _: None, settle=0.0, sleeper=waits.append)

    used = runner.use_apple(1)

    assert used == 1
    assert waits and waits[0] == runner_mod.APPLE_ENTRY_WAIT
    assert [int(x) for x, _y in link.taps] == [
        _box_center_x(APPLE_ENTRY_BOX),
        _box_center_x(APPLE_ROW_BOX),
        _box_center_x(APPLE_CONFIRM_OK_BOX),
    ]


def test_apple_supply_from_an_open_menu_skips_the_plus_entry(tmp_path, monkeypatch) -> None:
    """点「连续出击」后游戏已弹出补给菜单：直接从黄金果实行开始。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    _register_apple_templates("ap_restore", "ap_apple_gold", "ap_apple_confirm_text", "ap_confirm_ok")
    link = CyclingLink([_apple_menu_frame(), _apple_confirm_frame(), _apple_map_frame(50)])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="apple-from-menu",
                                     log=lambda _: None, settle=0.0, sleeper=lambda _s: None)

    used = runner.use_apple(1, from_menu=True)

    assert used == 1
    assert [int(x) for x, _y in link.taps] == [
        _box_center_x(APPLE_ROW_BOX),
        _box_center_x(APPLE_CONFIRM_OK_BOX),
    ], f"菜单已经打开时不应再点地图上的 ＋：{link.taps}"


def test_handle_ap_restore_menu_uses_the_open_menu_and_counts_the_apple(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    _register_apple_templates("ap_apple_gold")
    link = CyclingLink([_apple_menu_frame()])
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="ap-menu-handler", log=lambda _: None,
        auto_apple=3, sleeper=lambda _s: None,
    )
    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        runner, "use_apple",
        lambda count=1, from_menu=False: (calls.append((count, from_menu)), 1)[1],
    )

    handled = runner._handle_ap_restore_menu(1)

    assert handled is True
    assert calls == [(1, True)]
    assert runner.apples_used == 1


def test_handle_ap_restore_menu_reclicks_continue_if_the_dialog_returns(tmp_path, monkeypatch) -> None:
    """用完苹果若回到「连续出击」弹窗，补点右侧按钮继续，而不是让助战步失败。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    _register_apple_templates("ap_apple_gold", "ap_apple_confirm_text", "ap_confirm_ok")
    _register_wrap_buttons("repeat_again")
    dialog = _wrap_page("dialog", 70)
    link = CyclingLink([
        _apple_menu_frame(), _apple_menu_frame(), _apple_confirm_frame(), dialog, dialog,
    ])
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="ap-menu-return-dialog", log=lambda _: None,
        auto_apple=3, settle=0.0, sleeper=lambda _s: None,
    )

    handled = runner._handle_ap_restore_menu(1)

    assert handled is True
    assert [int(x) for x, _y in link.taps] == [
        _box_center_x(APPLE_ROW_BOX),
        _box_center_x(APPLE_CONFIRM_OK_BOX),
        _wrap_centers()["again"][0],
    ]


def test_apple_supply_stops_before_touching_anything_when_the_row_is_missing(tmp_path, monkeypatch) -> None:
    """菜单里认不出「黄金果实」那一行 ⇒ 只点开了菜单就停手（圣晶石行绝不猜着点）。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    _register_apple_templates("ap_restore", "ap_apple_gold", "ap_apple_confirm_text", "ap_confirm_ok")
    link = CyclingLink([_apple_map_frame(), _apple_menu_frame(gold=False)])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="apple-miss", log=lambda _: None,
                                     settle=0.0, sleeper=lambda _s: None)

    used = runner.use_apple(1)

    assert used == 0 and len(link.taps) == 1, f"只该点开菜单：{link.taps}"
    assert not any(r.kind == "apple" for r in runner.records)


def test_apple_supply_stops_when_the_confirm_popup_is_not_fully_recognized(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    _register_apple_templates("ap_restore", "ap_apple_gold", "ap_apple_confirm_text", "ap_confirm_ok")
    link = CyclingLink([_apple_map_frame(), _apple_menu_frame(), _apple_confirm_frame(ok=False)])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="apple-confirm", log=lambda _: None,
                                     settle=0.0, sleeper=lambda _s: None)

    used = runner.use_apple(1)

    assert used == 0 and len(link.taps) == 2, f"没认出弹窗就不该点「决定」：{link.taps}"
    assert not any(r.kind == "apple" for r in runner.records)


def test_repeat_is_an_alias_of_two_rounds() -> None:
    """`--repeat` 与 `--rounds` 统一口径（2026-10-15）：前者就是 --rounds 2 的旧写法。"""
    import argparse

    def args(**overrides):
        base = {"rounds": 1, "repeat": False, "pick_support": False}
        base.update(overrides)
        return argparse.Namespace(**base)

    repeat = args(repeat=True)
    assert runner_mod.normalize_run_args(repeat) == 0
    assert repeat.rounds == 2 and repeat.pick_support is True and repeat.repeat is False

    rounds3 = args(rounds=3)
    assert runner_mod.normalize_run_args(rounds3) == 0
    assert rounds3.pick_support is True

    assert runner_mod.normalize_run_args(args(repeat=True, rounds=3)) == 2, "--repeat 与 --rounds 互斥"
    assert runner_mod.normalize_run_args(args(pick_support=True)) == 2, "单局给 --pick-support 是错的"
    assert runner_mod.normalize_run_args(args(rounds=0)) == 2


def test_read_ap_estimates_from_the_bar() -> None:
    """行动力读数：按条的填充端估算（真机帧回归过 ±1；这里是合成帧的口径回归）。"""
    for ap in (23, 62, 100, 133):
        frame = _paint_ap_bar(np.full((720, 1280, 3), 25, dtype=np.int16), ap)
        reading = vision.read_ap(frame)
        assert reading.readable and reading.estimate is not None
        assert abs(reading.estimate - ap) <= 2, f"AP={ap} 读成 {reading.estimate}"
    # 空条（AP≈0）：要么读成 0、要么直接报读不出——两种都不许报成"够用"
    empty = _paint_ap_bar(np.full((720, 1280, 3), 25, dtype=np.int16), 0)
    empty_reading = vision.read_ap(empty)
    assert (not empty_reading.readable) or (empty_reading.estimate or 0) <= 2
    full = _paint_ap_bar(np.full((720, 1280, 3), 25, dtype=np.int16), 148)
    assert vision.read_ap(full).saturated
    assert not vision.read_ap(np.full((720, 1280, 3), 25, dtype=np.int16)).readable


def _register_quest_card(frame: np.ndarray) -> None:
    vision.save_button_template("daily_quest_card", frame, (600, 110, 1250, 320),
                                search_box=(560, 90, 1279, 350), note="测试")


def test_enter_quest_refuses_when_ap_is_not_enough(tmp_path, monkeypatch) -> None:
    """开刷前读行动力：连第一局的 40 AP 都不够就停手、一下都不点。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    frame = _paint_ap_bar(_map_frame_with_card(), 12)
    _register_quest_card(frame)
    link = CyclingLink([frame, frame])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="ap-check", log=lambda _: None,
                                     sleeper=lambda _s: None, support_key="k", enter_quest=True,
                                     rounds=3)      # 第一局就要 40 AP，12 不够

    with pytest.raises(runner_mod.ExecutionAbort, match="行动力不够"):
        runner._enter_quest()

    assert link.taps == [], "AP 不够时一下都不能点"
    assert any(record.kind == "ap" for record in runner.records), "读数要留证据"


def test_ap_gate_only_requires_the_first_round() -> None:
    """规划 4 局时不再要求开局就有 160 AP；先保证第一局即可。"""
    link = CyclingLink([])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="ap-first", log=lambda _: None,
                                     rounds=4)
    runner.ap_estimate = 42
    assert runner._needs_apple_for_next_round() is False
    runner.ap_estimate = 2
    assert runner._needs_apple_for_next_round() is True


def test_check_ap_before_start_does_not_reserve_the_whole_batch() -> None:
    link = CyclingLink([_paint_ap_bar(_map_frame_with_card(), 50)])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="ap-no-reserve",
                                     log=lambda _: None, rounds=4, enter_quest=True)
    runner._check_ap_before_start()
    assert runner.ap_estimate == 50


def test_auto_apple_uses_one_apple_when_the_next_round_is_short(monkeypatch) -> None:
    link = CyclingLink([])
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="auto-apple", log=lambda _: None, rounds=4, auto_apple=3,
    )
    runner.ap_estimate = 2
    calls: list[int] = []

    class _Reading:
        estimate = 148
        saturated = False

    monkeypatch.setattr(runner, "use_apple", lambda count=1: (calls.append(count), 1)[1])
    monkeypatch.setattr(runner, "_read_ap_record", lambda *args, **kwargs: _Reading())
    runner._ensure_ap_for_next_round()

    assert calls == [1]
    assert runner.apples_used == 1
    assert runner.ap_estimate == 148
    assert runner._needs_apple_for_next_round() is False


def test_auto_apple_stops_at_the_authorized_cap() -> None:
    link = CyclingLink([])
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="auto-apple-cap", log=lambda _: None, auto_apple=1,
    )
    runner.ap_estimate = 2
    runner.apples_used = 1
    with pytest.raises(runner_mod.ExecutionAbort, match="上限"):
        runner._ensure_ap_for_next_round()


def test_run_rounds_uses_continuous_button_then_handles_the_ap_menu(monkeypatch) -> None:
    """连刷中途直接点「连续出击」；AP 不足时在游戏弹出的补给菜单里处理。"""
    link = CyclingLink([])
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="rounds-ap-menu", log=lambda _: None,
        rounds=2, auto_apple=3, sleeper=lambda _s: None,
    )
    calls: list[object] = []
    monkeypatch.setattr(runner, "_play_round", lambda *args, **kwargs: True)
    monkeypatch.setattr(runner, "_do_wrap", lambda idx, continue_farming=False: calls.append(("wrap", continue_farming)))
    monkeypatch.setattr(runner, "_handle_ap_restore_menu", lambda idx: calls.append("ap_menu"))
    monkeypatch.setattr(runner, "_do_support", lambda idx: calls.append("support"))
    monkeypatch.setattr(runner, "_read_ap_record", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_write_log", lambda *args, **kwargs: None)

    runner._run_rounds(None, 1, 0)  # type: ignore[arg-type]

    assert calls.index(("wrap", True)) < calls.index("ap_menu") < calls.index("support")
    assert ("wrap", False) in calls, "最后一局仍应点左「关闭」"


def test_enter_quest_taps_the_card_then_picks_support(tmp_path, monkeypatch) -> None:
    """冷启动：地图上点关卡卡片 → 落到助战选择 → 选助战 → 直接进本。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    # 画上行动力条：开刷前那次读数第一帧就能读到，不会触发"读不出就重读一次"多吃掉一帧
    card = _paint_ap_bar(_map_frame_with_card(), 120)
    _register_quest_card(card)
    # 第 1 张给 _enter_quest 开头的行动力读数用
    link = CyclingLink([card, card, _support_screen(), _attack_frame(), _attack_frame()])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="enter-quest", log=lambda _: None,
                                     settle=0.0, sleeper=lambda _s: None,
                                     support_key="quest-eq", support_row=1, enter_quest=True)

    runner._enter_quest()

    assert [int(x) for x, _y in link.taps] == [925, 522], "先点关卡卡片，再点助战行"
    kinds = [r.kind for r in runner.records]
    assert kinds == ["ap", "enter_quest", "support"]
    assert runner.records[-1].verdict == "ok"


def _home_frame() -> np.ndarray:
    """合成主界面：靠下位置有「迦勒底之门」入口（和卡片那一屏的行位置错开）。"""
    frame = np.full((720, 1280, 3), 25, dtype=np.int16)
    frame[420:540, 660:1240] = 200
    frame[440:470, 700:780] = 60      # 小方块 ×2
    frame[490:520, 700:780] = 60
    return frame


def _gate_frame() -> np.ndarray:
    """合成「迦勒底之门」列表：第一行是「每日任务」（竖向暗条 + 一个方块）。"""
    frame = np.full((720, 1280, 3), 35, dtype=np.int16)
    frame[175:290, 660:1240] = 150
    frame[180:285, 900:920] = 60      # 竖条
    frame[240:280, 1060:1160] = 60    # 方块
    return frame


def test_enter_quest_navigates_home_to_daily_screen(tmp_path, monkeypatch) -> None:
    """冷启动导航：主界面 → 迦勒底之门 → 每日任务 → 关卡卡片 → 选助战（每一跳都要模板自证）。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    home = _paint_ap_bar(_home_frame(), 120)   # 开刷前读数一帧读到，不额外消费画面
    gate = _gate_frame()
    daily = _map_frame_with_card()
    vision.save_button_template("chaldea_gate", home, (700, 440, 1000, 520),
                                search_box=(600, 400, 1279, 580), note="测试")
    vision.save_button_template("daily_quest_entry", gate, (890, 200, 1150, 268),
                                search_box=(650, 120, 1279, 340), note="测试")
    _register_quest_card(daily)
    # 先确认三个模板互不串台（合成帧是结构性的，这里就是"位置 + 结构"两道判据的回归）
    assert not vision.match_button(home, "daily_quest_card").accepted
    assert not vision.match_button(gate, "daily_quest_card").accepted
    assert not vision.match_button(gate, "chaldea_gate").accepted
    # 第 1 张是 _enter_quest 开头的"是不是已经在战斗里"自检，第 2 张才轮到第一跳
    link = CyclingLink([home, home, home, gate, daily, _support_screen(),
                        _attack_frame(), _attack_frame()])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="enter-nav", log=lambda _: None,
                                     settle=0.0, sleeper=lambda _s: None, support_key="quest-nav",
                                     support_row=1, enter_quest=True)

    runner._enter_quest()

    xs = [int(x) for x, _y in link.taps]
    assert len(xs) == 4, f"应该是 导航×2 + 关卡卡片 + 助战行：{link.taps}"
    assert xs[2] == 925, "第三下是关卡卡片（合成帧里卡片中心 x=925）"
    assert xs[3] == 522, "第四下是助战行（面板中心 x=522）"
    assert [r.kind for r in runner.records] == [
        "ap", "enter_quest_nav", "enter_quest_nav", "enter_quest", "support"
    ]


def test_startup_popup_cleanup_then_navigation_stops_before_card(tmp_path, monkeypatch) -> None:
    """C15：先清启动弹窗，再只导航到每日任务卡片；不点关卡、不花 AP。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    home = _paint_ap_bar(_home_frame(), 120)
    gate = _gate_frame()
    daily = _map_frame_with_card()
    popup1 = home.copy()
    popup1[80:140, 1000:1060:10] = 250
    popup1[80:140:10, 1000:1060] = 250
    popup2 = home.copy()
    popup2[300:360, 520:580:10] = 250
    popup2[300:360:10, 520:580] = 250
    vision.save_button_template(
        "announcement_close", popup1, (1000, 80, 1060, 140), search_box=(0, 0, 1279, 719),
        min_score=0.7, note="测试"
    )
    vision.save_button_template(
        "login_bonus_close", popup2, (520, 300, 580, 360), search_box=(0, 0, 1279, 719),
        min_score=0.7, note="测试"
    )
    vision.save_button_template(
        "chaldea_gate", home, (700, 440, 1000, 520), search_box=(600, 400, 1279, 580), note="测试"
    )
    vision.save_button_template(
        "daily_quest_entry", gate, (890, 200, 1150, 268), search_box=(650, 120, 1279, 340), note="测试"
    )
    _register_quest_card(daily)
    link = CyclingLink([popup1, popup2, home, home, gate, daily])
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="startup-nav", log=lambda _: None, settle=0.0,
        sleeper=lambda _s: None, enter_quest=True,
    )
    scene, _image, _info = runner._clear_startup_popups()
    card, _scene_name = runner._nav_to_daily_screen()
    assert scene.name in {"other", "battle_main"}
    assert card is not None and card.center is not None
    assert [record.kind for record in runner.records] == [
        "startup_clear", "startup_clear", "enter_quest_nav", "enter_quest_nav"
    ]
    assert len(link.taps) == 4, "两个弹窗 + 两跳导航；不能出现关卡卡片点击"


def test_enter_quest_starts_from_the_support_screen(tmp_path, monkeypatch) -> None:
    """已经停在「助战选择」屏时：跳过地图导航，直接选助战 →（补点开始任务）→ 进本。

    2026-10-16 用户口径：「冠位战自动进本可以暂缓，我现在可以接受从助战开始刷」——
    冠位战的入口不在"每日任务 → 关卡卡片"那条导航线上，所以这条捷径是必需的。
    """
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    party = _party_confirm_frame()
    _register_start_quest_button(party)
    support = _support_screen()
    rows = vision.find_support_rows(support)
    vision.save_support_reference("quest-from-support", support, rows[0], note="测试")
    link = CyclingLink([support, support, support, party, _attack_frame(), _attack_frame()])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="from-support", log=lambda _m: None,
                                     settle=0.0, sleeper=lambda _s: None,
                                     support_key="quest-from-support", enter_quest=True)

    runner._enter_quest()

    assert [int(x) for x, _y in link.taps] == [522, 1167], (
        f"应当是「选助战行的面板中心」→「开始任务」，不该去点关卡卡片：{link.taps}"
    )
    kinds = [record.kind for record in runner.records]
    assert kinds == ["support"], f"不该留下「点关卡卡片」这类记录：{kinds}"
    assert runner.records[-1].verdict == "ok"


def _grand_quest_list_frame() -> np.ndarray:
    """合成「冠位戴冠战」关卡列表：右上角一张关卡行，行里有「消耗 AP 40」框 + AP 条。"""
    frame = np.full((720, 1280, 3), 55, dtype=np.int16)
    frame[150:300, 470:1200] = (120, 40, 45)          # 关卡行（红底）
    frame[236:274, 778:935] = (240, 240, 240)         # 「消耗 AP 40」框
    frame[250:262, 800:820] = (30, 30, 30)            # 框里的字
    frame[165:193, 618:691] = (232, 232, 232)         # 「上次执行」角标
    frame[172:186, 628:681] = (40, 40, 120)           # 角标里的字
    return _paint_ap_bar(frame, 120)


def test_enter_quest_taps_the_grand_battle_card(tmp_path, monkeypatch) -> None:
    """冠位战关卡列表 ⇒ 自己点那一关的卡片（模板自证）→ 助战屏 → 选助行 → 进本。

    2026-10-17：冠位战的入口不在"迦勒底之门 → 每日任务 → 关卡卡片"那条线上，以前每局都要
    人手动点进去；这里补上"从关卡列表一键开刷"（AP 闸门照旧：这一屏有条，读不够就停手）。
    """
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    quest_list = _grand_quest_list_frame()
    vision.save_button_template(
        "grand_assassin_card", quest_list, (778, 236, 935, 274),
        search_box=(700, 100, 1279, 700), note="测试",
    )
    vision.save_button_template(
        "last_executed", quest_list, (618, 165, 691, 193),
        search_box=(520, 120, 1279, 700), note="测试",
    )
    support = _grand_support_screen(("plain", "plain"))
    rows = vision.find_support_rows(support)
    vision.save_support_library_entry("servant", "杀狐", support, rows[0].identity, note="测试")
    battle = _attack_frame()
    link = CyclingLink([quest_list, support, support, battle, battle])
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="enter-grand", log=lambda _m: None, settle=0.0,
        sleeper=lambda _s: None, enter_quest=True, support_key="quest-grand-enter",
        support_criteria={"servant": "杀狐"},
    )

    runner._enter_quest()

    assert link.taps, "应该点了一下关卡卡片"
    first = link.taps[0]
    assert abs(first[0] - 857) <= 2 and abs(first[1] - 255) <= 2, (
        f"第一下应当是「消耗 AP 40」框的中心：{first}"
    )
    enter_record = next(r for r in runner.records if r.kind == "enter_quest")
    assert "冠位战关卡卡片" in enter_record.label


def test_enter_quest_stops_when_last_executed_marks_another_row(tmp_path, monkeypatch) -> None:
    """「上次执行」角标标在**别的行**上 ⇒ 说明 runbook 指的关卡不是你最近刷的那关，停手。

    用户 2026-10-17 口径：角标标在最近刷过的那一关行上。它和卡片不同行时，点下去就是"点错关卡"。
    """
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    quest_list = _grand_quest_list_frame()
    # 把角标挪到下一行（y 往下 200）
    quest_list[365:393, 618:691] = (232, 232, 232)
    quest_list[372:386, 628:681] = (40, 40, 120)
    quest_list[165:193, 618:691] = (120, 40, 45)
    vision.save_button_template(
        "grand_assassin_card", quest_list, (778, 236, 935, 274),
        search_box=(700, 100, 1279, 700), note="测试",
    )
    vision.save_button_template(
        "last_executed", _grand_quest_list_frame(), (618, 165, 691, 193),
        search_box=(520, 120, 1279, 700), note="测试",
    )
    link = CyclingLink([quest_list])
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="enter-grand-badge", log=lambda _m: None, settle=0.0,
        sleeper=lambda _s: None, enter_quest=True, support_key="k",
    )

    with pytest.raises(runner_mod.ExecutionAbort, match="上次执行"):
        runner._enter_quest()

    assert link.taps == [], "角标对不上就一下都不能点"


def test_enter_quest_refuses_when_ap_is_not_enough_on_the_grand_list(tmp_path, monkeypatch) -> None:
    """冠位战关卡列表上 AP 不够 ⇒ 一下都不点（这一屏能读行动力）。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    quest_list = _paint_ap_bar(_grand_quest_list_frame(), 12)
    vision.save_button_template(
        "grand_assassin_card", quest_list, (778, 236, 935, 274),
        search_box=(700, 100, 1279, 700), note="测试",
    )
    link = CyclingLink([quest_list])
    runner = runner_mod.BattleRunner(
        link, _layout(), run_id="enter-grand-ap", log=lambda _m: None, settle=0.0,
        sleeper=lambda _s: None, enter_quest=True, rounds=2, support_key="k",
    )

    with pytest.raises(runner_mod.ExecutionAbort, match="行动力不够"):
        runner._enter_quest()

    assert link.taps == []


def test_enter_quest_is_skipped_when_already_in_battle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    link = CyclingLink([_attack_frame()])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="enter-quest-skip",
                                     log=lambda _: None, enter_quest=True)

    runner._enter_quest()

    assert link.taps == [], "已经在战斗里就不该再点卡片"
    assert runner.records == []


def test_rounds_loop_continues_until_the_last_round(tmp_path, monkeypatch) -> None:
    """连刷 N 局：前 N-1 局收尾点「连续出击」+ 选助战，最后一局点「关闭」收工。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(runner_mod.BattleRunner, "_play_round",
                        lambda self, plan, start_at, stop_at: True)
    monkeypatch.setattr(runner_mod.BattleRunner, "_do_wrap",
                        lambda self, index, continue_farming=False: calls.append(("wrap", continue_farming)))
    monkeypatch.setattr(runner_mod.BattleRunner, "_do_support",
                        lambda self, index: calls.append(("support", index)))
    plan = plan_mod.ExecutionPlan(quest_id="q", title="连刷回归", team=[], actions=[])

    runner = runner_mod.BattleRunner(CyclingLink([_attack_frame()]), _layout(), run_id="rounds3",
                                     log=lambda _: None, sleeper=lambda _s: None, rounds=3)
    runner.run(plan)

    assert calls == [("wrap", True), ("support", 0), ("wrap", True), ("support", 0), ("wrap", False)]

    calls.clear()
    single = runner_mod.BattleRunner(CyclingLink([_attack_frame()]), _layout(), run_id="rounds1",
                                     log=lambda _: None, sleeper=lambda _s: None, rounds=1)
    single.run(plan)
    assert calls == [("wrap", False)], "单局仍然只收尾一次、点左「关闭」"


def test_wait_does_not_end_the_battle_on_moving_frames(tmp_path, monkeypatch) -> None:
    """宝具演出的中间帧不能当"本局结束"的证据。

    2026-10-14 用磁盘上的历史帧实测：演出中间帧两两之间变化 0.93-1.0，真结算页几乎静止。
    老判据只看"不是战斗界面"，连出 3 帧演出就会误判成打完了，接着按结算页坐标去点。
    """
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    assert vision.read_scene(_attack_frame()).name == vision.SCENE_BATTLE_MAIN
    dark = np.zeros((720, 1280, 3), dtype=np.int16)
    bright = np.full((720, 1280, 3), 220, dtype=np.int16)
    link = CyclingLink([dark, bright, dark, bright, _attack_frame(), _attack_frame()])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="wait-move",
                                     log=lambda _: None, sleeper=lambda _s: None)

    runner._do_wait(1, _wait_action())

    assert runner.records[-1].verdict == "ok"
    assert not any(record.verdict == "battle_over" for record in runner.records)


def test_wait_declares_battle_over_on_static_non_battle_frames(tmp_path, monkeypatch) -> None:
    """静下来的非战斗画面（结算页 / 地图）连出 3 帧才算本局结束。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    blank = np.zeros((720, 1280, 3), dtype=np.int16)
    link = CyclingLink([blank])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="wait-over",
                                     log=lambda _: None, sleeper=lambda _s: None)

    runner._do_wait(1, _wait_action())

    assert runner.records[-1].verdict == "battle_over"

class ScrollingLink(CyclingLink):
    """按"滚动位置"吐帧的假设备：每次 swipe 把位置挪一格，shot 返回该位置的帧。

    为什么不用 CyclingLink（按拍摄次序轮播）：助战列表的翻页次数取决于判据（到底 / 到顶 /
    重叠多少行），写死"第几张截图是哪一屏"会让测试一改判据就错位。这里直接模拟"列表"：
    位置 0 = 最上面，位置 N = 最下面；swipe 往上=往后翻、往下=往前翻。
    """

    def __init__(self, frames: list[np.ndarray], battle: np.ndarray) -> None:
        super().__init__([battle])
        self.positions = frames
        self.battle_frame = battle
        self.pos = 0
        self.entered = False

    def _frame(self) -> np.ndarray:
        if self.entered:
            return self.battle_frame
        return self.positions[max(0, min(self.pos, len(self.positions) - 1))]

    def shot(self, path, settle: float = 0.0) -> dict:
        from pathlib import Path

        from PIL import Image

        frame = self._frame()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(frame.astype(np.uint8)).save(str(path) + ".png")
        return {"path": str(path) + ".png", "luma": float(frame.mean())}

    def tap(self, x, y, settle: float = 0.0) -> dict:
        self.taps.append((float(x), float(y)))
        self.entered = True          # 点了助战就进本
        return {"x": x, "y": y}

    def swipe(self, x1, y1, x2, y2, settle: float = 0.0) -> dict:
        self.swipes.append((float(x1), float(y1), float(x2), float(y2)))
        self.pos += 1 if y2 < y1 else -1   # 手指往上划 = 往后翻
        self.pos = max(0, min(self.pos, len(self.positions) - 1))
        return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}
