"""「刻了某个指令纹章的那张卡」识别 + 执行接线的回归测试。

用合成画面（自己画金徽 + 贴模板）验判据逻辑：命中、命中不了要拒、两张都像要拒；
另外验编译期闸门（engraved_code 的名字白名单、不许同时写死 position）。
最后一条是真实帧回归，文件不在就跳过（真机帧不入库）。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from game_assistant import battle_plan as plan_mod
from game_assistant import battle_vision as vision

CODE_NAME = "花之魔术师"
BADGE_RGB = (214, 171, 20)
BADGE_SIZE = (30, 35)          # (宽, 高)，真机实测
BADGE_OFFSET_X = 57            # 金徽中心 ≈ 卡心 + 57
BADGE_Y = 461


def _template_rgb() -> np.ndarray:
    registry = json.loads(
        (vision.COMMAND_CODE_DIR / "command_codes.json").read_text(encoding="utf-8")
    )
    entry = next(item for item in registry["codes"] if item["name"] == CODE_NAME)
    with Image.open(vision.COMMAND_CODE_DIR / entry["template"]) as handle:
        return np.asarray(handle.convert("RGB")).astype(np.int16)


def _base_frame() -> np.ndarray:
    return np.full((720, 1280, 3), 90, dtype=np.int16)


def _draw_badge(frame: np.ndarray, slot: int) -> tuple[int, int]:
    cx = vision.HAND_CARD_CENTERS[slot - 1] + BADGE_OFFSET_X
    width, height = BADGE_SIZE
    frame[BADGE_Y - height // 2 : BADGE_Y + height // 2, cx - width // 2 : cx + width // 2] = BADGE_RGB
    return cx, BADGE_Y


def _paste_icon(frame: np.ndarray, badge_center: tuple[int, int]) -> None:
    template = _template_rgb()
    height, width = template.shape[:2]
    cx = badge_center[0] - 5
    cy = badge_center[1] - 48
    frame[cy - height // 2 : cy - height // 2 + height, cx - width // 2 : cx - width // 2 + width] = template


def test_finds_the_engraved_card() -> None:
    frame = _base_frame()
    centers = {slot: _draw_badge(frame, slot) for slot in range(1, 6)}
    _paste_icon(frame, centers[3])

    match = vision.find_command_code_card(frame, CODE_NAME)

    assert match.accepted, f"{match.report()} / {'；'.join(match.notes)}"
    assert match.index == 3
    assert match.score > 0.9


def test_rejects_when_no_card_has_the_code() -> None:
    frame = _base_frame()
    for slot in range(1, 6):
        _draw_badge(frame, slot)

    match = vision.find_command_code_card(frame, CODE_NAME)

    assert not match.accepted
    assert any("门槛" in note for note in match.notes)


def test_rejects_when_two_cards_look_the_same() -> None:
    frame = _base_frame()
    centers = {slot: _draw_badge(frame, slot) for slot in range(1, 6)}
    _paste_icon(frame, centers[1])
    _paste_icon(frame, centers[4])

    match = vision.find_command_code_card(frame, CODE_NAME)

    assert not match.accepted, "两张卡都命中时必须判不出来（差距门槛），绝不能挑一张"
    assert any("分不清" in note for note in match.notes)


def test_rejects_when_anchors_are_missing() -> None:
    frame = _base_frame()
    _paste_icon(frame, (vision.HAND_CARD_CENTERS[1] + BADGE_OFFSET_X, BADGE_Y))

    match = vision.find_command_code_card(frame, CODE_NAME)

    assert not match.accepted
    assert match.notes


def _spec(step_extra: dict) -> dict:
    step = {"turn": 2, "actor": "U－奥尔加玛丽", "kind": "card", "card": "arts", "crit": True}
    step.update(step_extra)
    return {
        "quest_id": "q",
        "title": "t",
        "team": [{"name": "U－奥尔加玛丽"}],
        "steps": [
            {"turn": 2, "actor": "U－奥尔加玛丽", "kind": "np"},
            {"turn": 2, "actor": "U－奥尔加玛丽", "kind": "card", "card": "buster", "position": "leftmost"},
            step,
        ],
    }


def test_plan_compiles_engraved_code_step() -> None:
    plan = plan_mod.compile_plan(_spec({"engraved_code": CODE_NAME}), skill_table={})

    picks = [action for action in plan.actions if action.kind == plan_mod.CARD and action.command_code]
    assert len(picks) == 1
    assert picks[0].position == plan_mod.POSITION_COMMAND_CODE
    assert CODE_NAME in picks[0].label


def test_plan_rejects_unknown_code_name() -> None:
    with pytest.raises(plan_mod.PlanError):
        plan_mod.compile_plan(_spec({"engraved_code": "兽爪"}), skill_table={})


def test_plan_rejects_code_plus_fixed_position() -> None:
    with pytest.raises(plan_mod.PlanError):
        plan_mod.compile_plan(
            _spec({"engraved_code": CODE_NAME, "position": "rightmost"}), skill_table={}
        )


REAL_FRAME = Path(r"D:\workSpace\code\.tmp\live_cards_1013.png")


@pytest.mark.skipif(not REAL_FRAME.exists(), reason="真机帧不在盘上")
def test_real_frame_regression() -> None:
    """2026-10-13 实机帧：花之魔术师在第 1 张卡（用户圈注样本，NCC 0.954）。"""
    image = vision.load(str(REAL_FRAME))

    match = vision.find_command_code_card(image, CODE_NAME)

    assert match.accepted, match.report()
    assert match.index == 1
