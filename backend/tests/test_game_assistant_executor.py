"""执行器离线逻辑测试：相对基线校验、场景守卫、卡色选卡失败即停。"""
from __future__ import annotations

import pytest
from PIL import Image

from game_assistant.battle_executor import (
    ExecutionAbort,
    SceneGuard,
    pick_card,
    region_delta,
    screen_luma,
)


def solid(color: int) -> Image.Image:
    return Image.new("RGB", (1280, 720), (color, color, color))


def test_region_delta_is_relative_not_absolute() -> None:
    """同一落差在"深色场景"和"浅色场景"里都应被识别为变化。"""
    dark_before, dark_after = solid(60), solid(100)
    light_before, light_after = solid(140), solid(200)
    box = (0, 0, 100, 100)
    assert region_delta(dark_before, dark_after, box) == pytest.approx(40, abs=1)
    assert region_delta(light_before, light_after, box) == pytest.approx(60, abs=1)


def test_scene_guard_aborts_when_screen_deviates() -> None:
    guard = SceneGuard(tolerance=25.0)
    baseline = guard.arm(solid(60))
    assert baseline == pytest.approx(60, abs=1)
    guard.check(solid(70))  # 轻微变化：通过
    with pytest.raises(ExecutionAbort):
        guard.check(solid(150))


def test_scene_guard_requires_arming() -> None:
    with pytest.raises(ExecutionAbort):
        SceneGuard().check(solid(60))


def test_screen_luma_is_scene_scale_free() -> None:
    assert screen_luma(solid(0)) == pytest.approx(0, abs=1)
    assert screen_luma(solid(255)) == pytest.approx(255, abs=1)


def test_pick_card_stops_when_required_color_absent() -> None:
    assert pick_card("buster", {1: "arts", 2: "buster"}) == 2
    with pytest.raises(ExecutionAbort):
        pick_card("quick", {1: "arts", 2: "buster"})
