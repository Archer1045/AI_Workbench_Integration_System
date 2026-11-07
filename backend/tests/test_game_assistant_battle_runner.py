"""执行链路（spec -> 动作流 -> 状态机）的回归测试。

用合成画面 + 假设备，不碰真机：这里验的是**判据逻辑**（编译、卡位约束、
画面判定、前置/后置校验、失败即停），真机验证另见 `.agent-handoff/work-log.md`。
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

import config

from game_assistant import battle_plan as plan_mod
from game_assistant import battle_runner as runner_mod
from game_assistant import battle_vision as vision


# ---------- 合成画面 ----------


def _base_frame(value: int = 120) -> np.ndarray:
    return np.full((720, 1280, 3), value, dtype=np.int16)


def _add_card_bursts(frame: np.ndarray, colors: list[str | None]) -> np.ndarray:
    """按卡槽网格画 5 片饱和色带，模拟选牌界面。"""
    palette = {"buster": (230, 40, 40), "arts": (40, 60, 230), "quick": (40, 200, 70)}
    for slot, color in zip(vision.HAND_CARD_CENTERS, colors):
        if color is None:
            continue
        x0, x1 = slot - 90, slot + 90
        frame[440:660, x0:x1] = palette[color]
    return frame


def _add_attack_button(frame: np.ndarray) -> np.ndarray:
    """右下角画一个亮蓝圆盘（模拟「攻击」按钮）。

    半径按**实测**取值：真按钮腐蚀 6 次后的核心是 4470-4621 px（2026-10-12/14 实测），
    即半径 ≈38 px，反推绘制半径 ≈44 px。画大了会踩到 battle_vision 的核心面积上限。
    """
    yy, xx = np.ogrid[:720, :1280]
    disc = (xx - 1163) ** 2 + (yy - 604) ** 2 <= 44**2
    frame[disc] = (60, 150, 240)
    return frame


def _write(tmp_path, name: str, frame: np.ndarray) -> str:
    path = tmp_path / name
    Image.fromarray(frame.astype(np.uint8)).save(path)
    return str(path)


# ---------- 画面判定 ----------


def test_read_hand_reads_five_cards(tmp_path) -> None:
    frame = _add_card_bursts(_base_frame(), ["arts", "buster", "buster", "quick", "arts"])
    reading = vision.read_hand(frame)
    assert reading.verified
    assert reading.indices_with_color("buster") == [2, 3]
    assert vision.resolve_cards(reading, "buster", count=2, position="leftmost") == [2, 3]
    assert vision.resolve_cards(reading, "arts", position="rightmost") == [5]
    assert vision.resolve_cards(reading, "any", position="leftmost") == [1]


def test_hand_detector_refuses_non_card_screens() -> None:
    assert not vision.read_hand(_base_frame()).verified
    assert not vision.read_hand(_add_attack_button(_base_frame())).verified


def test_hand_detector_refuses_off_shape_bands() -> None:
    """只数"有几条色带"挡不住冠位戴冠战的「关卡选择屏」——2026-10-16 真机撞到过。

    那一屏左下的巨大从者卡面 + 队伍头像正好落在手牌带 (y440-660) 里，凑出 5 条红带 ⇒
    被判成在选牌。这里按真机实测的形状复刻那 5 条（`preflight-20261016-151447/
    001_preflight.png`）：217×220 / 240×220 / 69×138 / 240×128 / 41×149。真卡的色带是
    "接近正方形的竖块"（663 帧历史帧实测宽 152-217、宽高比 0.91-1.18），所以后三条
    （太窄或太扁）必须被挡掉，剩下的不够 3 条 ⇒ 判不出来。
    """
    frame = _base_frame()
    for x0, x1, y0, y1 in (
        (50, 266, 440, 659),
        (281, 520, 440, 659),
        (650, 718, 493, 630),
        (793, 1032, 457, 584),
        (1205, 1245, 441, 589),
    ):
        frame[y0:y1, x0:x1] = (230, 40, 40)
    reading = vision.read_hand(frame)
    assert not reading.verified, reading.report()
    assert vision.read_scene(frame).name == vision.SCENE_OTHER


def test_scene_classification() -> None:
    main = vision.read_scene(_add_attack_button(_base_frame()))
    assert main.name == vision.SCENE_BATTLE_MAIN
    assert main.attack is not None and main.attack.usable

    cards = vision.read_scene(_add_card_bursts(_add_attack_button(_base_frame()), ["arts"] * 5))
    assert cards.name == vision.SCENE_CARD_SELECT

    # 浮层是把整屏压暗（实测按钮亮度 142 -> 122，蓝色核心 4470 -> 3222 px），
    # 所以这里整体乘 0.75：蓝色仍在掩膜内、形状还在，但亮度掉到门槛以下 -> overlay
    dim = (_add_attack_button(_base_frame()) * 0.75).astype(np.int16)
    assert vision.read_scene(dim).name == vision.SCENE_OVERLAY

    assert vision.read_scene(_base_frame()).name == vision.SCENE_OTHER


def test_wide_blue_bar_is_not_the_attack_button() -> None:
    """活动地图右下那种细长蓝按钮不能冒充「攻击」（宽高比判据）。"""
    frame = _base_frame()
    frame[630:670, 1110:1250] = (150, 200, 240)
    attack = vision.find_attack_button(frame)
    assert attack is None or not attack.usable


def test_oversized_blue_blob_is_not_the_attack_button() -> None:
    """宝具演出那片大蓝光不能冒充「攻击」按钮（核心面积上限）。

    2026-10-14 实测：宝具演出帧上那块蓝色腐蚀 6 次后仍有 11420 px（真按钮 4470-4621），
    当时被当成"可用按钮" ⇒ 画面判成 battle_main ⇒ 回合等待误以为下一回合已就绪、
    自动收尾不触发。这里合成一块同量级的蓝块，要求既不命中按钮、也不判成主战斗界面。
    """
    frame = _base_frame()
    frame[430:660, 1090:1270] = (70, 160, 245)
    raw = vision.find_attack_button(frame)
    assert raw is None, f"超大蓝块不该被当成攻击按钮（核心 {raw.area if raw else '-'} px）"
    assert vision.read_scene(frame).name == vision.SCENE_OTHER


def test_region_delta_threshold_behaviour() -> None:
    before = _add_attack_button(_base_frame())
    after = before.copy()
    after[0:60, 0:60] = 255
    assert vision.region_delta(before, after, (0, 0, 60, 60)) == 1.0
    assert vision.region_delta(before, after, (600, 300, 700, 400)) == 0.0


def test_any_card_never_picks_an_unreadable_slot() -> None:
    """读数"未知"的卡槽不能当成可用的 any——它多半是刚点过、抬起后被盖住的那张。

    2026-10-14 实测：第 3 回合点掉第 5 张后，它在手牌读数里变成"未知"；若把它算作
    可用的 any，就会再点一次同一张卡，等于把它取消掉。
    """
    reading = vision.HandReading(
        cards=[
            vision.HandCard(index=1, center_x=147, color="buster", label="力击", burst_pixels=3000),
            vision.HandCard(index=2, center_x=401, color="arts", label="技击", burst_pixels=3000),
            vision.HandCard(index=5, center_x=1163, color=None, label="未知", burst_pixels=0),
        ],
        verified=True,
    )
    assert vision.resolve_cards(reading, "any", count=2, position="leftmost") == [1, 2]
    only_unknown = vision.HandReading(
        cards=[vision.HandCard(index=1, center_x=147, color=None, label="未知", burst_pixels=0)],
        verified=True,
    )
    with pytest.raises(ValueError):
        vision.resolve_cards(only_unknown, "any", position="leftmost")


# ---------- spec -> 动作流 ----------


def _skill(name: str, slot: int, target: str = "self") -> dict:
    return {"slot": slot, "name": name, "effects": [{"target": target}]}


def _table() -> dict:
    return {
        plan_mod._norm("主输出"): [
            _skill("自有强化 EX", 1),
            _skill("单体充能 B", 2),
        ],
        plan_mod._norm("辅助"): [
            _skill("全体加攻 A", 1, "ally_all"),
            _skill("指定加护 A", 2, "ally_one"),
        ],
    }


def _spec() -> dict:
    return {
        "quest_id": "test-quest",
        "title": "编译测试",
        "team": [{"name": "主输出", "class_name": "Beast"}, {"name": "辅助", "class_name": "Caster"}],
        "steps": [
            {"turn": 1, "actor": "辅助", "kind": "skill", "skill": "指定加护 A", "target": "主输出"},
            {"turn": 1, "actor": "主输出", "kind": "skill", "skill": "自有强化 EX"},
            {"turn": 1, "actor": "主输出", "kind": "mystic_code", "skill_slot": 3, "target": "主输出"},
            {"turn": 1, "actor": "主输出", "kind": "np"},
            {"turn": 1, "actor": "主输出", "kind": "card", "card": "buster", "position": "leftmost"},
            {"turn": 1, "actor": "主输出", "kind": "card", "card": "any", "position": "leftmost"},
        ],
    }


def test_compile_plan_builds_tap_sequence() -> None:
    plan = plan_mod.compile_plan(_spec(), skill_table=_table())
    assert [action.kind for action in plan.actions] == [
        plan_mod.SKILL, plan_mod.TARGET,      # 单体技能 -> 必须选目标
        plan_mod.SKILL,                       # 自身技能 -> 不选目标
        plan_mod.MASTER_MENU, plan_mod.MASTER_SKILL, plan_mod.TARGET,
        plan_mod.ATTACK,                      # 技能放完才进选牌界面
        plan_mod.NP, plan_mod.CARD, plan_mod.CARD, plan_mod.WAIT,
    ]
    assert plan.actions[0].expect_before == plan_mod.SCENE_BATTLE_MAIN
    assert plan.actions[0].expect_after == plan_mod.SCENE_OVERLAY
    assert plan.actions[4].expect_after == plan_mod.SCENE_OVERLAY  # 礼装技能会弹目标浮层
    assert plan.actions[5].expect_before == plan_mod.SCENE_OVERLAY  # 接着选目标
    assert plan.actions[-2].expect_after == plan_mod.SCENE_ANY     # 第 3 张点下即自动执行


def test_compile_plan_rejects_wrong_slot_count() -> None:
    spec = _spec()
    spec["steps"] = [step for step in spec["steps"] if step.get("kind") != "card"][:4]
    with pytest.raises(plan_mod.PlanError, match="出手卡位"):
        plan_mod.compile_plan(spec, skill_table=_table())


# ---------- 条件派生的第一步（2026-10-15）：按站位指定演员 + 选卡偏好链 ----------
# 起因：冠位战（Assassin）1T 打不死，必须靠指令卡暴击，但首回合不一定有打手的卡。
# 用户确定的路线是"计划支持条件分支"，这里先落第 1 步（纯编译/执行层，不需要新感知）。


def _double_fox_table() -> dict:
    return {
        plan_mod._norm("王哈桑"): [_skill("信仰的加护 A", 1), _skill("晚钟 EX", 2)],
        plan_mod._norm("光之高扬斯卡娅"): [
            _skill("杀戮技巧（人） A", 1, "ally_one"),
            _skill("NFF特别服务 A", 2, "ally_one"),
            _skill("兔子革新者 A", 3, "ally_one"),
        ],
    }


def _double_fox_spec(actor_step: dict) -> dict:
    """站位 1 王哈桑 / 站位 2、3 都是光之高扬斯卡娅（双杀狐，用户编成）。"""
    return {
        "quest_id": "grand-assassin-1t",
        "title": "冠位战 条件派生测试",
        "team": [
            {"name": "王哈桑", "class_name": "Assassin"},
            {"name": "光之高扬斯卡娅", "class_name": "Assassin"},
            {"name": "光之高扬斯卡娅", "class_name": "Assassin"},
        ],
        "steps": [
            actor_step,
            {"turn": 1, "actor_slot": 1, "kind": "np"},
            {"turn": 1, "actor_slot": 1, "kind": "card", "card": "any", "position": "leftmost"},
            {"turn": 1, "actor_slot": 1, "kind": "card", "card": "any", "position": "leftmost"},
        ],
    }


def test_support_skills_default_to_the_dps_and_say_so() -> None:
    """角色约定：写了 `dps` 之后，**辅助位**的单体友方技能不写 target 就默认指向打手，
    并且要在 plan.notes 里留一句通知（用户 2026-10-16 口径："默认可以这么来，但需要通知我"）。
    打手自己的技能不套这个默认——真需要就显式写。
    """
    spec = {
        "quest_id": "grand-assassin",
        "title": "角色默认",
        "dps": "王哈桑",
        "team": [
            {"name": "王哈桑", "class_name": "Assassin"},
            {"name": "光之高扬斯卡娅", "class_name": "Assassin"},
            {"name": "光之高扬斯卡娅", "class_name": "Assassin"},
        ],
        "steps": [
            {"turn": 1, "actor_slot": 2, "kind": "skill", "skill_slot": 2},          # 没写 target
            {"turn": 1, "actor_slot": 1, "kind": "skill", "skill_slot": 1},          # 打手自己
            {"turn": 1, "actor_slot": 1, "kind": "np"},
            {"turn": 1, "actor_slot": 1, "kind": "card", "card": "any", "position": "leftmost"},
            {"turn": 1, "actor_slot": 1, "kind": "card", "card": "any", "position": "leftmost"},
        ],
    }

    plan = plan_mod.compile_plan(spec, skill_table=_double_fox_table())

    targets = [action for action in plan.actions if action.kind == plan_mod.TARGET]
    assert len(targets) == 1 and targets[0].target_slot == 1, "辅助技能默认指向打手（站位 1）"
    assert any("默认指向" in note and "王哈桑" in note for note in plan.notes), plan.notes
    assert "⚠" in plan.summary()


def _owner_frame(patterns: list[int | None]) -> np.ndarray:
    """合成选牌帧：给每张卡画**各自卡主**的卡面图案（放在卡主识别窗口里）。

    图案是结构性差异（NCC 对整体明暗不敏感，必须是图案本身不同）。
    """
    frame = _add_card_bursts(_base_frame(90), ["buster"] * 5)
    rng = np.random.default_rng(31)
    patches = {key: 120 + rng.integers(0, 90, size=(96, 141, 3), dtype=np.int16) for key in (1, 2)}
    for center, key in zip(vision.HAND_CARD_CENTERS, patterns):
        if key is None:
            continue
        box = vision.card_owner_box(center)
        frame[box[1] : box[3] + 1, box[0] : box[2] + 1] = patches[key]
    return frame


def test_card_owner_matching_picks_the_dps_card(tmp_path, monkeypatch) -> None:
    """按卡主挑卡（2026-10-16 第 2 步）：只有卡面属于打手的那张才算"打手的红卡"。

    用户口径：冠位战里"优先红卡"必须先是**打手**的红卡，否则会挑到辅助的红卡。
    """
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    # 第 2 张是打手的卡（红），第 1 张是辅助的卡（也是红）
    frame = _owner_frame([2, 1, 1, 1, None])
    box = vision.card_owner_box(vision.HAND_CARD_CENTERS[1])
    vision.save_support_library_entry("card", "打手", frame, box, note="测试")
    library = vision.load_support_library("card")
    assert set(library) == {"打手"}
    hand = vision.read_hand(frame)

    name, score = vision.match_card_owner(frame, vision.HAND_CARD_CENTERS[1], library)
    assert name == "打手" and score > 0.95
    other_name, other_score = vision.match_card_owner(frame, vision.HAND_CARD_CENTERS[0], library)
    assert other_name == "" and other_score < 0.55, (other_name, other_score)

    # 收窄到"打手的卡"里挑红卡 ⇒ 只能是第 2 张
    assert vision.resolve_cards(hand, "buster", count=1, position="leftmost", allowed=[2]) == [2]


def test_card_chain_with_owner_picks_the_dps_card_and_falls_back(tmp_path, monkeypatch) -> None:
    """执行器侧：偏好链写 `owner` ⇒ 点的是**打手那张**红卡；打手没卡时退到"任意卡"。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    frame = _owner_frame([2, 1, 1, 1, None])          # 第 1 张是辅助的红卡、第 2 张是打手的红卡
    vision.save_support_library_entry("card", "打手", frame, vision.card_owner_box(401), note="测试")
    chain = (
        {"card": "buster", "position": "any", "engraved_code": None, "crit": False,
         "owner": "打手", "label": "打手的力击"},
        {"card": "any", "position": "leftmost", "engraved_code": None, "crit": False,
         "owner": None, "label": "任意卡·leftmost"},
    )
    action = plan_mod.Action(
        kind=plan_mod.CARD, label="打手 出卡（打手的力击 → 任意卡）", turn=1, actor_slot=1,
        card_color="buster", fills_slot=True, choices=chain,
        expect_before=vision.SCENE_CARD_SELECT, expect_after=vision.SCENE_CARD_SELECT,
    )
    after = frame.copy()
    after[556:577, :] = 255          # 点一张卡之后画面必有变化（整条色带过一遍白）
    link = FakeLink([frame, after] * 8)
    runner = runner_mod.BattleRunner(link, _layout(), run_id="owner-chain", log=lambda _m: None,
                                     settle=0.0, sleeper=lambda _s: None)
    runner.run(plan_mod.ExecutionPlan(quest_id="q", title="卡主", team=[], actions=[action]))
    xs = [int(x) for x, _y in link.taps]
    assert len(xs) == 1 and abs(xs[0] - 401) <= 2, f"应点打手那张（第 2 张）：{link.taps}"

    # 打手这一手没有卡 ⇒ 退回第二条（任意卡·最左）
    no_dps = _owner_frame([1, 1, 1, 1, None])
    no_dps_after = no_dps.copy()
    no_dps_after[556:577, :] = 255
    link2 = FakeLink([no_dps, no_dps_after] * 8)
    runner2 = runner_mod.BattleRunner(link2, _layout(), run_id="owner-fallback", log=lambda _m: None,
                                      settle=0.0, sleeper=lambda _s: None)
    runner2.run(plan_mod.ExecutionPlan(quest_id="q", title="卡主回退", team=[], actions=[action]))
    xs2 = [int(x) for x, _y in link2.taps]
    assert len(xs2) == 1 and abs(xs2[0] - 147) <= 2, f"应退回最左那张：{link2.taps}"


def test_actor_slot_addresses_the_third_position_of_a_duplicate_servant() -> None:
    """双杀狐：`actor: 杀狐` 只会命中第 2 站位，所以必须能写 `actor_slot: 3`。"""
    spec = _double_fox_spec(
        {"turn": 1, "actor_slot": 3, "kind": "skill", "skill": "兔子革新者 A", "target": "王哈桑"}
    )
    plan = plan_mod.compile_plan(spec, skill_table=_double_fox_table())
    skill = plan.actions[0]
    assert skill.actor_slot == 3 and skill.skill_index == 3, plan.actions[0]
    assert plan.actions[1].target_slot == 1
    assert "光之高扬斯卡娅" in skill.label

    # 反证：按名字写只会指到第一个同名站位（这是为什么需要 actor_slot）
    by_name = _double_fox_spec(
        {"turn": 1, "actor": "光之高扬斯卡娅", "kind": "skill", "skill": "兔子革新者 A", "target": "王哈桑"}
    )
    assert plan_mod.compile_plan(by_name, skill_table=_double_fox_table()).actions[0].actor_slot == 2

    out_of_range = _double_fox_spec(
        {"turn": 1, "actor_slot": 4, "kind": "skill", "skill": "兔子革新者 A", "target": "王哈桑"}
    )
    with pytest.raises(plan_mod.PlanError, match="actor_slot"):
        plan_mod.compile_plan(out_of_range, skill_table=_double_fox_table())


def test_card_preference_chain_compiles_in_order() -> None:
    spec = _double_fox_spec({"turn": 1, "actor_slot": 3, "kind": "skill",
                             "skill": "兔子革新者 A", "target": "王哈桑"})
    spec["steps"][2] = {
        "turn": 1, "actor_slot": 1, "kind": "card",
        "choose": [{"card": "buster"}, {"card": "any", "position": "leftmost"}],
    }
    plan = plan_mod.compile_plan(spec, skill_table=_double_fox_table())

    card = next(action for action in plan.actions if action.kind == plan_mod.CARD)
    assert [entry["card"] for entry in card.choices] == ["buster", "any"]
    assert [entry["label"] for entry in card.choices] == ["力击", "任意卡·leftmost"]
    assert card.fills_slot is True and "力击 → 任意卡" in card.label


def test_card_preference_chain_keeps_the_owner_and_rejects_owner_slot() -> None:
    """「按卡主挑卡」已实现（2026-10-16 第 2 步）⇒ `owner` 能编译、标签带上卡主；
    不支持的 `owner_slot` 仍然编译期报错（不静默忽略）。"""
    spec = _double_fox_spec({"turn": 1, "actor_slot": 3, "kind": "skill",
                             "skill": "兔子革新者 A", "target": "王哈桑"})
    spec["steps"][2] = {
        "turn": 1, "actor_slot": 1, "kind": "card",
        "choose": [{"owner": "王哈桑", "card": "buster"}, {"card": "any"}],
    }
    plan = plan_mod.compile_plan(spec, skill_table=_double_fox_table())
    card = next(action for action in plan.actions if action.kind == plan_mod.CARD)
    assert [entry["owner"] for entry in card.choices] == ["王哈桑", None]
    assert card.choices[0]["label"] == "王哈桑的力击", card.choices[0]["label"]

    spec["steps"][2] = {"turn": 1, "actor_slot": 1, "kind": "card",
                        "choose": [{"owner_slot": 1, "card": "buster"}]}
    with pytest.raises(plan_mod.PlanError, match="owner_slot"):
        plan_mod.compile_plan(spec, skill_table=_double_fox_table())

    spec["steps"][2] = {"turn": 1, "actor_slot": 1, "kind": "card", "card": "buster",
                        "choose": [{"card": "buster"}]}
    with pytest.raises(plan_mod.PlanError, match="不能同时写"):
        plan_mod.compile_plan(spec, skill_table=_double_fox_table())


def test_card_preference_chain_falls_back_when_the_first_choice_is_absent(tmp_path, monkeypatch) -> None:
    """手牌里没有力击 ⇒ 自动走第二条（任意卡·最左），不再停在原地。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    frame_a = _add_card_bursts(_base_frame(100), ["arts", "arts", "quick", "quick", "arts"])
    frame_b = frame_a.copy()
    frame_b[556:577, :] = 255
    link = FakeLink([frame_a, frame_b] * 6)
    card = plan_mod.Action(
        kind=plan_mod.CARD, label="王哈桑 出卡（力击 → 任意卡·leftmost）", turn=1,
        actor_slot=1, card_color="buster", position="any", fills_slot=True,
        choices=(
            {"card": "buster", "position": "any", "engraved_code": None, "crit": False, "label": "力击"},
            {"card": "any", "position": "leftmost", "engraved_code": None, "crit": False, "label": "任意卡·leftmost"},
        ),
        expect_before=vision.SCENE_CARD_SELECT, expect_after=vision.SCENE_CARD_SELECT,
    )
    plan = plan_mod.ExecutionPlan(quest_id="q", title="偏好链", team=[], actions=[card])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="card-chain",
                                     log=lambda _m: None, settle=0.0, sleeper=lambda _s: None)

    runner.run(plan)

    xs = [int(x) for x, _y in link.taps]
    assert len(xs) == 1 and abs(xs[0] - 147) <= 2, f"应退到第二条：最左的那张卡，实际 {xs}"
    assert runner.records[-1].verdict == "ok"


def test_card_preference_chain_fails_stop_when_nothing_matches(tmp_path, monkeypatch) -> None:
    """两条都挑不到（手牌只有技击）⇒ fail-stop 说清每一条为什么不行。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    frame = _add_card_bursts(_base_frame(100), ["arts", "arts", "arts", "arts", "arts"])
    link = FakeLink([frame] * 6)
    card = plan_mod.Action(
        kind=plan_mod.CARD, label="王哈桑 出卡（力击 → 迅击）", turn=1,
        actor_slot=1, fills_slot=True,
        choices=(
            {"card": "buster", "position": "any", "engraved_code": None, "crit": False, "label": "力击"},
            {"card": "quick", "position": "any", "engraved_code": None, "crit": False, "label": "迅击"},
        ),
        expect_before=vision.SCENE_CARD_SELECT, expect_after=vision.SCENE_CARD_SELECT,
    )
    plan = plan_mod.ExecutionPlan(quest_id="q", title="偏好链停手", team=[], actions=[card])
    runner = runner_mod.BattleRunner(link, _layout(), run_id="card-chain-stop",
                                     log=lambda _m: None, settle=0.0, sleeper=lambda _s: None)

    with pytest.raises(runner_mod.ExecutionAbort, match="偏好链每一条都挑不到卡"):
        runner.run(plan)

    assert link.taps == [], "挑不到就一下都不能点"
    assert "第 1 条（力击）" in runner.records[-1].note
    assert "第 2 条（迅击）" in runner.records[-1].note


def test_grand_battle_flow_compiles_end_to_end() -> None:
    """用户给的冠位战流程（双杀狐 + T1 宝具/优先红卡 + T2 补刀）能编出完整动作流。

    T2 只在战斗没结束时才跑到——这一点**现有机制已经保证**：T1 后面那个 WAIT 一旦判出
    `battle_over`，`_play_round` 直接返回、后面的动作根本不执行。所以这里只验编译结果。
    """
    spec = {
        "quest_id": "grand-assassin",
        "title": "冠位战 1T/2T",
        "team": [
            {"name": "王哈桑", "class_name": "Assassin"},
            {"name": "光之高扬斯卡娅", "class_name": "Assassin"},
            {"name": "光之高扬斯卡娅", "class_name": "Assassin"},
        ],
        "steps": [
            # T1
            {"turn": 1, "actor_slot": 1, "kind": "skill", "skill_slot": 1},
            {"turn": 1, "actor_slot": 2, "kind": "skill", "skill_slot": 1, "target": "王哈桑"},
            {"turn": 1, "actor_slot": 3, "kind": "skill", "skill_slot": 3, "target": "王哈桑"},
            {"turn": 1, "actor_slot": 1, "kind": "np"},
            {"turn": 1, "actor_slot": 1, "kind": "card",
             "choose": [{"card": "buster"}, {"card": "any", "position": "leftmost"}]},
            {"turn": 1, "actor_slot": 1, "kind": "card", "card": "any", "position": "leftmost"},
            # T2（只有在 T1 没打死时才会执行到）
            {"turn": 2, "actor_slot": 3, "kind": "skill", "skill_slot": 3, "target": "王哈桑"},
            {"turn": 2, "actor_slot": 1, "kind": "np"},
            {"turn": 2, "actor_slot": 1, "kind": "card",
             "choose": [{"card": "buster"}, {"card": "any"}]},
            {"turn": 2, "actor_slot": 1, "kind": "card", "card": "any", "position": "leftmost"},
        ],
    }

    plan = plan_mod.compile_plan(spec, skill_table=_double_fox_table())

    assert plan.turns() == [1, 2]
    chains = [action for action in plan.actions if action.choices]
    assert len(chains) == 2, "两回合各有一次带偏好链的出卡"
    assert all(action.kind == plan_mod.CARD and action.fills_slot for action in chains)
    # 每回合 3 个出手位（宝具占 1）——这是游戏硬约束：不选满 3 张卡不会开始战斗
    for turn in (1, 2):
        filled = [action for action in plan.for_turn(turn) if action.fills_slot]
        assert len(filled) == plan_mod.SLOTS_PER_TURN
    # 技能排在「攻击」之前、出手动作排在之后（界面顺序）
    first_turn = plan.for_turn(1)
    kinds = [action.kind for action in first_turn]
    attack_at = kinds.index(plan_mod.ATTACK)
    assert all(not action.fills_slot for action in first_turn[:attack_at]), "攻击之前只有技能/选目标"
    tail = [action for action in first_turn[attack_at + 1:] if action.kind != plan_mod.WAIT]
    assert tail and all(action.fills_slot for action in tail), "攻击之后才是宝具与指令卡（末尾是等结算）"
    assert first_turn[-1].kind == plan_mod.WAIT


def test_compile_plan_rejects_unknown_skill_and_missing_target() -> None:
    spec = _spec()
    spec["steps"][0]["skill"] = "不存在的技能"
    with pytest.raises(plan_mod.PlanError, match="找不到技能"):
        plan_mod.compile_plan(spec, skill_table=_table())

    spec = _spec()
    del spec["steps"][0]["target"]
    with pytest.raises(plan_mod.PlanError, match="必须给 target"):
        plan_mod.compile_plan(spec, skill_table=_table())


def test_compile_plan_full_90pp_spec_matches_verified_rotation() -> None:
    """今天实机跑通的那份 spec 也要能编译出 3 回合动作流。"""
    from pathlib import Path

    spec_path = Path(config.GAME_ASSISTANT_EXECUTION_DIR) / "runbooks" / "90pp_gudaguda9_oku_merlin_kama.json"
    if not spec_path.exists():
        pytest.skip("缺少 90++ 配队 spec 工件")
    import json

    plan = plan_mod.compile_plan(json.loads(spec_path.read_text(encoding="utf-8")))
    assert plan.turns() == [1, 2, 3]
    first_turn = " → ".join(action.label for action in plan.for_turn(1))
    assert "光之高扬斯卡娅 技能2" in first_turn and "宝具" in first_turn


# ---------- 状态机 ----------


class FakeLink:
    """按脚本吐画面的假设备：不接真机，也不允许意外点击。"""

    def __init__(self, frames: list[np.ndarray]) -> None:
        self.frames = frames
        self.taps: list[tuple[float, float]] = []
        self.display = {"serial": "fake", "logical": 5, "sfid": "0"}
        self._index = 0

    def shot(self, path, settle: float = 0.0) -> dict:
        frame = self.frames[min(self._index, len(self.frames) - 1)]
        self._index += 1
        from pathlib import Path

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(frame.astype(np.uint8)).save(str(path) + ".png")
        return {"path": str(path) + ".png", "luma": float(frame.mean())}

    def tap(self, x, y, settle: float = 0.0) -> dict:
        self.taps.append((x, y))
        return {"x": x, "y": y}


def _layout() -> runner_mod.SessionLayout:
    return runner_mod.SessionLayout(
        skill_x={1: (73, 163, 257), 2: (388, 483, 574)},
        skill_y=582,
        np_cards={1: (400, 205), 2: (700, 205)},
        target_points={1: (325, 388), 2: (610, 388)},
        master_menu=(1190, 290),
        master_skills=((907, 309), (991, 309), (1082, 309)),
        undo=(1170, 684),
        source="测试用",
    )


def test_dry_run_never_taps(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    frame = _add_attack_button(_base_frame())
    link = FakeLink([frame])
    plan = plan_mod.compile_plan(_spec(), skill_table=_table())
    runner = runner_mod.BattleRunner(link, _layout(), run_id="dry", dry_run=True, log=lambda _: None)
    runner.run(plan)
    assert link.taps == []
    assert runner.records[0].verdict == "dry-run"          # 起步自检通过
    assert all(record.verdict in ("dry-run", "skipped") for record in runner.records)
    assert any(record.verdict == "skipped" for record in runner.records)
    assert (tmp_path / "runs" / "dry" / "steps.json").exists()


def test_runner_aborts_when_scene_is_wrong(tmp_path, monkeypatch) -> None:
    """计划第一步要在主战斗界面起步；假设备只给空画面 -> 必须停，不许点。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    link = FakeLink([_base_frame()])
    plan = plan_mod.compile_plan(_spec(), skill_table=_table())
    runner = runner_mod.BattleRunner(link, _layout(), run_id="abort", log=lambda _: None)
    with pytest.raises(runner_mod.ExecutionAbort, match="期望前态"):
        runner.run(plan)
    assert link.taps == []


def test_runner_aborts_when_tap_changes_nothing(tmp_path, monkeypatch) -> None:
    """画面对了，但点了没任何变化（例如布局过期点到空处）-> 重试一次后停。"""
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    frame = _add_attack_button(_base_frame())
    link = FakeLink([frame] * 20)
    plan = plan_mod.compile_plan(_spec(), skill_table=_table())
    runner = runner_mod.BattleRunner(link, _layout(), run_id="noop", log=lambda _: None,
                                     settle=0.0, sleeper=lambda _s: None)
    with pytest.raises(runner_mod.ExecutionAbort, match="没变化|期望后态"):
        runner.run(plan)
    assert len(link.taps) == runner_mod.TAP_RETRY + 1


def test_preflight_reports_not_ready_on_non_battle_screen(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    link = FakeLink([_base_frame()])
    plan = plan_mod.compile_plan(_spec(), skill_table=_table())
    report = runner_mod.preflight(link, plan, _layout(), runner_mod.BattleRunner(
        link, _layout(), run_id="preflight-test", dry_run=True, log=lambda _: None
    ))
    assert report["scene"] == vision.SCENE_OTHER
    assert report["ready"] is False
    assert "不能起步" in report["note"]
    assert link.taps == []


def test_card_slots_are_freed_every_turn(tmp_path, monkeypatch) -> None:
    """「这一回合已经点过的卡位」必须按回合清空。

    2026-10-14 首次整局连跑（--start-at 1）实测：9 张卡一路累积，到第 25 个动作
    （第 3 回合第 2 张卡）已经占掉 5 个卡位，直接报"能用的 any 只有 0 张"并抛裸
    ValueError 崩掉整局。分段跑（每段一个新进程）时它是干净的，所以一直没暴露。
    """
    monkeypatch.setattr(config, "GAME_ASSISTANT_EXECUTION_DIR", tmp_path)
    frame_a = _add_card_bursts(_base_frame(100), ["arts", "buster", "buster", "quick", "arts"])
    frame_b = frame_a.copy()
    frame_b[556:577, :] = 255  # 点一张卡之后画面必有变化（这里整条色带过一遍白）
    link = FakeLink([frame_a, frame_b] * 12)
    plan = plan_mod.ExecutionPlan(
        quest_id="test-cards", title="卡位预算回归", team=[],
        actions=[
            plan_mod.Action(
                kind=plan_mod.CARD, label=f"第 {turn} 回合第 {slot} 张", turn=turn,
                card_color="any", position="leftmost", fills_slot=True,
                expect_before=vision.SCENE_CARD_SELECT, expect_after=vision.SCENE_CARD_SELECT,
            )
            for turn in (1, 2, 3) for slot in (1, 2)
        ],
    )
    runner = runner_mod.BattleRunner(link, _layout(), run_id="turn-budget",
                                     log=lambda _: None, settle=0.0, sleeper=lambda _s: None)

    runner.run(plan)

    xs = [int(x) for x, _y in link.taps]
    assert len(xs) == 6
    for turn in range(3):
        first, second = xs[turn * 2], xs[turn * 2 + 1]
        assert abs(first - 147) <= 2 and abs(second - 401) <= 2, (
            f"第 {turn + 1} 回合应当重新从左往右取（1、2 号卡位），实际 {xs}"
        )
    assert all(record.verdict == "ok" for record in runner.records)
