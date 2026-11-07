"""把「用户指定配队 + 固定轮转 spec」编译成**可执行动作流**。

与 `rotation_runbook.py` 的分工：
- `rotation_runbook` 回答"这套队伍能不能 3T"（TeamPlan + 数值校验 + 给人看的手册）；
- 本模块回答"这一局具体按什么顺序点哪里"（机器执行用的动作流）。
两者吃**同一份 spec**（`quest_id` / `team[]` / `steps[]`），避免出现两套口径。

spec 的 steps 每项：
  {"turn": 2, "actor": "光之高扬斯卡娅", "kind": "skill", "skill": "兔子革新者 A", "target": "U－奥尔加玛丽"}
  {"turn": 2, "actor": "U－奥尔加玛丽", "kind": "mystic_code", "skill_slot": 3, "target": "U－奥尔加玛丽"}
  {"turn": 2, "actor": "U－奥尔加玛丽", "kind": "np"}
  {"turn": 2, "actor": "U－奥尔加玛丽", "kind": "card", "card": "buster", "position": "leftmost", "crit": true}
  {"turn": 2, "actor": "U－奥尔加玛丽", "kind": "card", "card": "arts", "engraved_code": "花之魔术师"}

`engraved_code`（执行层专用）表示"这一张必须是刻了该指令纹章的那一张卡"：卡位由感知层
`battle_vision` 按锚点+模板现场判定，**不接受**同时写死 position（位置规则不可依赖——
所长技能 1 自带 shuffle，手牌每回合都变）。判不出来时执行器停下来等人工，不猜。
注意与伤害模型的 `command_code` / `command_code_charge` 区分：那两个是算数值用的。

不猜的原则（与 decisions.md 一致）：
- 从者名 / 技能名必须能在本地资料库里唯一解析，否则编译阶段就报错；
- 「这个技能要不要选目标」由资料库里的效果目标域（ally_one 等）决定，不靠人记；
- 每回合必须正好填满 3 个卡位（宝具占 1 位），否则编译失败。
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import config

# 动作种类（执行器按这个分发）
SKILL = "skill"
TARGET = "target"
ATTACK = "attack"
NP = "np"
CARD = "card"
MASTER_SKILL = "master_skill"
MASTER_MENU = "master_menu"
UNDO = "undo"
WAIT = "wait"

# 每个动作执行完后期望处于的界面（感知层 battle_vision.read_scene 的取值）
SCENE_BATTLE_MAIN = "battle_main"
SCENE_CARD_SELECT = "card_select"
SCENE_OVERLAY = "overlay"
SCENE_ANY = "any"

SLOTS_PER_TURN = 3

# 编译期白名单：spec 里可以点名的指令纹章（名字取自本地资料库 `command_codes_cn.json`）。
# 这里只挡"把纹章名写错"；几何、模板与命中门槛由感知层 `battle_vision` 负责。
COMMAND_CODES = {"花之魔术师": "8400460"}
POSITION_COMMAND_CODE = "command_code"
# 技能表里"同名多只从者"的占位标记（见 load_skill_table）。编译期撞上它就报错。
AMBIGUOUS_MARK = "__ambiguous__"


class PlanError(ValueError):
    """spec 有问题时立刻失败，绝不下场猜。"""


@dataclass(frozen=True)
class Action:
    kind: str
    label: str
    turn: int
    actor_slot: int | None = None
    skill_index: int | None = None
    target_slot: int | None = None
    card_color: str | None = None
    position: str = "any"
    crit: bool = False
    command_code: str | None = None  # 指定"必须是刻了这个纹章的那张卡"
    # 选卡偏好链（2026-10-15）：按顺序试，**第一条能在当前手牌挑到卡的生效**；全挑不到才停手。
    # 每条是 {"card": buster/arts/quick/any, "position": any/leftmost/rightmost/command_code,
    # "engraved_code": 名字或 None, "crit": bool, "label": 给人看的短描述}。
    choices: tuple[dict[str, Any], ...] = ()
    expect_before: str = SCENE_ANY
    expect_after: str = SCENE_ANY
    fills_slot: bool = False  # np / card 会占用一个出手卡位
    note: str = ""


@dataclass
class ExecutionPlan:
    quest_id: str
    title: str
    team: list[dict[str, Any]]
    actions: list[Action] = field(default_factory=list)
    # 编译期"替你做的默认"会写在这里（例如辅助技能没写 target ⇒ 默认给打手）。
    # 用户口径（2026-10-16）：默认可以这么来，但**必须通知**，所以他要在日志/摘要里看得见。
    notes: list[str] = field(default_factory=list)

    def turns(self) -> list[int]:
        return sorted({action.turn for action in self.actions})

    def for_turn(self, turn: int) -> list[Action]:
        return [action for action in self.actions if action.turn == turn]

    def summary(self) -> str:
        lines = [f"{self.title or self.quest_id}：{len(self.actions)} 个动作，{len(self.turns())} 个回合"]
        for note in self.notes:
            lines.append(f"⚠ {note}")
        for turn in self.turns():
            steps = " → ".join(action.label for action in self.for_turn(turn))
            lines.append(f"  第 {turn} 回合: {steps}")
        return "\n".join(lines)


def _skill_table_path() -> Path:
    return Path(config.GAME_ASSISTANT_COMBAT_DIR) / "servant_skills_cn.json"


def _norm(text: str) -> str:
    """名字归一：全角英数与符号折成半角（「Ｕ－奥尔加玛丽」==「U-奥尔加玛丽」），
    并去掉空格差异。用户写哪种写法都能对上，但**不做模糊匹配**。"""
    return unicodedata.normalize("NFKC", str(text)).replace(" ", "").strip()


def load_skill_table(path: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """从本地资料库读出技能表，键有两套：

    * `名字`：**只有该名字唯一对应一只从者时**才写；同名多只（泳装 / Alter 等，
      实测 35 组）写 `AMBIGUOUS_MARK`，让编译期报错并列出候选，**不静默取一只**；
    * `名字(职阶)`：同名多只时逐只写入，spec 里写「莫德雷德(Rider)」就能精确命中。
    """
    target = path or _skill_table_path()
    if not target.exists():
        raise PlanError(f"缺少技能资料库：{target}（先跑 servant_skills 生成）")
    payload = json.loads(target.read_text(encoding="utf-8"))
    servants = list(payload.get("servants") or [])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for servant in servants:
        grouped.setdefault(_norm(str(servant.get("name"))), []).append(servant)
    table: dict[str, list[dict[str, Any]]] = {}
    for name, entries in grouped.items():
        if len(entries) == 1:
            table[name] = list(entries[0].get("skills") or [])
            continue
        variants = [f"{entry.get('name')}({entry.get('class_name') or '?'})" for entry in entries]
        table[name] = [{AMBIGUOUS_MARK: variants}]
        for entry in entries:
            qualified = f"{entry.get('name')}({entry.get('class_name') or ''})"
            table[_norm(qualified)] = list(entry.get("skills") or [])
    return table


def resolve_skill(
    skills: list[dict[str, Any]],
    skill_name: str,
    explicit_slot: int | None = None,
) -> tuple[int, bool]:
    """技能名 -> (第几格, 是否需要选目标)。"""
    if explicit_slot is not None:
        candidates = [entry for entry in skills if int(entry.get("slot") or 0) == int(explicit_slot)]
        if not candidates:
            raise PlanError(f"资料库里没有第 {explicit_slot} 格技能")
        return int(explicit_slot), _needs_target(candidates[0])
    if not skill_name:
        raise PlanError("skill 步骤必须给技能名或 skill_slot")
    wanted = _norm(skill_name)
    exact = [entry for entry in skills if _norm(str(entry.get("name"))) == wanted]
    hits = exact or [entry for entry in skills if wanted in _norm(str(entry.get("name") or ""))]
    if not hits:
        available = "、".join(sorted({str(entry.get("name")) for entry in skills}))
        raise PlanError(f"资料库里找不到技能「{skill_name}」；可选：{available}")
    slots = {int(entry.get("slot") or 0) for entry in hits}
    if len(slots) > 1:
        raise PlanError(
            f"技能「{skill_name}」在资料库里有多个形态（slot {sorted(slots)}），"
            "请在 spec 里直接给 skill_slot"
        )
    return int(hits[0].get("slot") or 0), _needs_target(hits[0])


def _needs_target(skill: dict[str, Any]) -> bool:
    """单体友方技能必然弹「请选择对象」；自身 / 全体技能不弹。"""
    for effect in skill.get("effects") or []:
        if str(effect.get("target") or "") == "ally_one":
            return True
    return False


def _slot_of(team: list[dict[str, Any]], name: str) -> int:
    wanted = _norm(name)
    for index, member in enumerate(team, start=1):
        if _norm(str(member.get("name"))) == wanted:
            return index
    known = "、".join(str(member.get("name")) for member in team)
    raise PlanError(f"团队里没有「{name}」（现有：{known}）")


def _name_of(team: list[dict[str, Any]], slot: int | None) -> str:
    """站位号 → 名字（日志与标签用；越界/空给空串）。"""
    if slot is None or not 1 <= slot <= len(team):
        return ""
    return str(team[slot - 1].get("name") or "")


def _actor_label(team: list[dict[str, Any]], slot: int | None, name: str) -> str:
    """动作标签里的演员写法：**同名占多个站位时带上站位号**（双杀狐/双 C呆否则分不清）。"""
    if slot is None:
        return name
    same_name = sum(1 for member in team if _norm(str(member.get("name"))) == _norm(name))
    return f"{name}(站位{slot})" if same_name > 1 else name


def _actor_slot_of(team: list[dict[str, Any]], step: dict[str, Any]) -> int | None:
    """解析这一步由**谁**出：可以写 `actor: 名字`，也可以写 `actor_slot: 站位号`。

    为什么必须支持站位号（2026-10-15 用户实测场景）：**双杀狐 / 双 C呆**这种"同一只从者占两个
    站位"的编成很常见，而按名字找站位只能命中第一个 ⇒「3 号位的杀狐」根本写不出来。
    """
    explicit = step.get("actor_slot")
    if explicit is None:
        explicit = step.get("slot")
    if explicit is None or explicit == "":
        actor = str(step.get("actor") or "")
        return _slot_of(team, actor) if actor else None
    slot = int(explicit)
    if not 1 <= slot <= len(team):
        raise PlanError(f"actor_slot 必须是 1..{len(team)} 的站位号（收到 {slot}）")
    return slot


# 选卡偏好链：允许的颜色 / 位置写法
CARD_COLOR_LABELS = {"buster": "力击", "arts": "技击", "quick": "迅击", "any": "任意卡"}
_CARD_COLORS_ALLOWED = ("buster", "arts", "quick", "any")
_CARD_POSITIONS_ALLOWED = ("any", "leftmost", "rightmost")


def _compile_card_choices(raw: Any) -> list[dict[str, Any]]:
    """把 `choose` 偏好链编译成规范化条目。**没实现的能力在编译期就报错，不静默忽略。**"""
    if not isinstance(raw, list) or not raw:
        raise PlanError("card 的 choose 必须是非空列表，例如 [{\"card\": \"buster\"}, {\"card\": \"any\"}]")
    chain: list[dict[str, Any]] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise PlanError(f"card 偏好链第 {index} 条必须是对象，收到 {entry!r}")
        # 「按卡主挑卡」（2026-10-16 落地）：卡面窗口的指纹匹配决定这张卡属于谁。
        # 用户口径：冠位战里"优先红卡"必须先是**打手的**红卡，否则会挑到辅助的红卡。
        owner = str(entry.get("owner") or "").strip()
        if entry.get("owner_slot") is not None:
            raise PlanError(
                f"card 偏好链第 {index} 条写了 owner_slot：请写从者名（`owner`），"
                "卡主识别是按从者名登记的指纹"
            )
        # 只写 owner 不写 card ⇒ 就是"这个从者的任意卡"（用户口径里的"王哈的卡"那一档）
        color = str(entry.get("card") or ("any" if owner else ""))
        if color not in _CARD_COLORS_ALLOWED:
            raise PlanError(
                f"card 偏好链第 {index} 条的 card 必须是 buster/arts/quick/any（收到「{color}」）"
            )
        position = str(entry.get("position") or "any")
        engraved = entry.get("engraved_code")
        if engraved:
            engraved = str(engraved)
            if engraved not in COMMAND_CODES:
                known = "、".join(sorted(COMMAND_CODES))
                raise PlanError(f"不认识的指令纹章「{engraved}」（现有：{known}）")
            if position not in ("any", POSITION_COMMAND_CODE):
                raise PlanError(
                    f"card 偏好链第 {index} 条同时给了 engraved_code 和 position："
                    "纹章是「认卡」、位置是「取第几张」，混在一起没法判"
                )
            position = POSITION_COMMAND_CODE
        elif position == POSITION_COMMAND_CODE:
            raise PlanError(f"card 偏好链第 {index} 条：position=command_code 必须配 engraved_code")
        elif position not in _CARD_POSITIONS_ALLOWED:
            raise PlanError(
                f"card 偏好链第 {index} 条的 position 必须是 any/leftmost/rightmost（收到「{position}」）"
            )
        chain.append(
            {
                "card": color,
                "position": position,
                "engraved_code": engraved or None,
                "crit": bool(entry.get("crit")),
                "owner": owner or None,
                "label": (
                    f"刻「{engraved}」的那张"
                    if engraved
                    else (f"{owner}的" if owner else "")
                    + CARD_COLOR_LABELS.get(color, color)
                    + ("" if position == "any" else f"·{position}")
                ),
            }
        )
    return chain


def compile_plan(spec: dict[str, Any], skill_table: dict[str, list[dict[str, Any]]] | None = None) -> ExecutionPlan:
    """把 spec 编译成动作流；任何歧义都在这里失败（不进入执行阶段）。"""
    team = list(spec.get("team") or [])
    if not team:
        raise PlanError("spec 里没有 team")
    steps = list(spec.get("steps") or [])
    if not steps:
        raise PlanError("spec 里没有 steps")

    table = skill_table if skill_table is not None else load_skill_table()
    # 角色约定（2026-10-16 用户口径）：spec 里可以写 `"dps": "打手名"`。**辅助位**（不是打手的
    # 那两位）放单体友方技能时如果没写 `target`，就默认指向打手，并把这件事写进 plan.notes
    # ——"默认可以这么来，但必须通知"。打手自己的技能不套这个默认（自己给自己加是另一回事，
    # 真需要就显式写 target）。
    dps_name = str(spec.get("dps") or "")
    plan = ExecutionPlan(
        quest_id=str(spec.get("quest_id") or ""),
        title=str(spec.get("title") or ""),
        team=team,
    )
    if dps_name:
        _slot_of(team, dps_name)   # 不在 team 里会在这里抛错（错误信息已经够清楚）

    by_turn: dict[int, list[dict[str, Any]]] = {}
    for step in steps:
        by_turn.setdefault(int(step.get("turn") or 1), []).append(step)

    for turn in sorted(by_turn):
        slots_used = 0
        pending: list[Action] = []
        for step in by_turn[turn]:
            actor_slot = _actor_slot_of(team, step)
            # 站位号优先：标签/技能表查找都用**那个站位上的名字**，这样双杀狐也能分开写
            actor = _name_of(team, actor_slot) or str(step.get("actor") or "")
            kind = str(step.get("kind") or "")

            if kind == SKILL:
                skills = table.get(_norm(actor))
                if skills and len(skills) == 1 and AMBIGUOUS_MARK in skills[0]:
                    variants = "、".join(str(v) for v in skills[0][AMBIGUOUS_MARK])
                    raise PlanError(
                        f"「{actor}」在资料库里有 {len(skills[0][AMBIGUOUS_MARK])} 只同名从者："
                        f"{variants}。请把 spec 里的名字写成「名字(职阶)」——不猜是哪一只"
                    )
                if not skills:
                    raise PlanError(f"资料库里没有从者「{actor}」的技能表")
                index, needs_target = resolve_skill(
                    skills, str(step.get("skill") or ""), step.get("skill_slot")
                )
                # 标签里带上**资料库里的技能名**：执行时日志/步骤流会写清"这一格是哪个技能"，
                # 方便人工核对槽位顺序（2026-10-16：用户核冠位战技能槽位时正需要这个）。
                named = next(
                    (
                        str(entry.get("name"))
                        for entry in skills
                        if int(entry.get("slot") or 0) == int(index)
                    ),
                    "",
                )
                pending.append(
                    Action(kind=SKILL,
                           label=f"{_actor_label(team, actor_slot, actor)} 技能{index}"
                                 + (f"（{named}）" if named else ""),
                           turn=turn,
                           actor_slot=actor_slot, skill_index=index,
                           expect_before=SCENE_BATTLE_MAIN,
                           expect_after=SCENE_OVERLAY if needs_target else SCENE_BATTLE_MAIN)
                )
                if needs_target:
                    target_name = str(step.get("target") or "")
                    if not target_name and dps_name and actor_slot is not None:
                        # 辅助位的单体友方技能没写 target ⇒ 默认给打手（并在 plan.notes 里留痕）
                        dps_slot = _slot_of(team, dps_name)
                        if int(actor_slot) != int(dps_slot):
                            target_name = dps_name
                            plan.notes.append(
                                f"第 {turn} 回合 {actor} 的「{named or f'技能{index}'}」没写 target："
                                f"按辅助→打手的默认指向了「{dps_name}」（要改成别人就显式写 target）"
                            )
                    if not target_name:
                        raise PlanError(f"{actor} 技能{index} 是单体友方技能，spec 里必须给 target")
                    pending.append(
                        Action(kind=TARGET, label=f"选目标 {target_name}", turn=turn,
                               actor_slot=actor_slot, target_slot=_slot_of(team, target_name),
                               expect_before=SCENE_OVERLAY, expect_after=SCENE_BATTLE_MAIN)
                    )
            elif kind in (MASTER_SKILL, "mystic_code"):  # 两种写法都收（rotation_runbook 用 mystic_code）
                skill_slot = int(step.get("skill_slot") or 0)
                if skill_slot not in (1, 2, 3):
                    raise PlanError("mystic_code 步骤必须给 1/2/3 的 skill_slot")
                pending.append(
                    Action(kind=MASTER_MENU, label="打开御主技能菜单", turn=turn,
                           expect_before=SCENE_BATTLE_MAIN, expect_after=SCENE_BATTLE_MAIN,
                           note="菜单只是浮在右侧，不压暗按钮，所以画面判定仍是 battle_main；"
                                "是否真的打开靠点击点附近的变化量证明")
                )
                pending.append(
                    Action(kind=MASTER_SKILL, label=f"御主礼装技能{skill_slot}", turn=turn,
                           skill_index=skill_slot,
                           expect_before=SCENE_BATTLE_MAIN, expect_after=SCENE_OVERLAY)
                )
                target_name = str(step.get("target") or "")
                if target_name:
                    pending.append(
                        Action(kind=TARGET, label=f"选目标 {target_name}", turn=turn,
                               target_slot=_slot_of(team, target_name),
                               expect_before=SCENE_OVERLAY, expect_after=SCENE_BATTLE_MAIN)
                    )
            elif kind == NP:
                slots_used += 1
                pending.append(
                    Action(kind=NP, label=f"{_actor_label(team, actor_slot, actor)} 宝具",
                           turn=turn, actor_slot=actor_slot,
                           expect_before=SCENE_CARD_SELECT, expect_after=SCENE_CARD_SELECT,
                           fills_slot=True)
                )
            elif kind == CARD:
                color = str(step.get("card") or "")
                # 偏好链（2026-10-15）：`{"kind": "card", "choose": [{...}, {...}]}`
                # 按顺序试，**第一条能在当前手牌挑到卡的生效**；全挑不到才 fail-stop。
                # 典型用法：「优先打手红卡 → 没有就打手任意卡 → 再没有就任意卡」。
                if step.get("choose") is not None:
                    if color:
                        raise PlanError("card 步骤不能同时写 card 和 choose：choose 本身就是偏好链，第一条即首选")
                    chain = _compile_card_choices(step.get("choose"))
                    slots_used += 1
                    pending.append(
                        Action(kind=CARD,
                               label=f"{_actor_label(team, actor_slot, actor)} 出卡（"
                                     + " → ".join(entry["label"] for entry in chain) + "）",
                               turn=turn, actor_slot=actor_slot,
                               card_color=str(chain[0]["card"]), position=str(chain[0]["position"]),
                               crit=any(bool(entry["crit"]) for entry in chain),
                               command_code=chain[0]["engraved_code"],
                               choices=tuple(chain),
                               expect_before=SCENE_CARD_SELECT, expect_after=SCENE_CARD_SELECT,
                               fills_slot=True)
                    )
                    continue
                # any = 任意一张还没用掉的指令卡（第 1 回合只要宝具打出去，补位卡是谁无所谓）
                if color not in ("buster", "arts", "quick", "any"):
                    raise PlanError(f"card 步骤的 card 必须是 buster/arts/quick/any，收到「{color}」")
                slots_used += 1
                position = str(step.get("position") or "any")
                # 执行层专用键（与伤害模型的 `command_code` / `command_code_charge` 区分开：
                # 那两个是在算数值，这里是"这一张必须是刻了该纹章的那一张"）。
                engraved = step.get("engraved_code")
                if engraved:
                    engraved = str(engraved)
                    if engraved not in COMMAND_CODES:
                        known = "、".join(sorted(COMMAND_CODES))
                        raise PlanError(f"不认识的指令纹章「{engraved}」（现有：{known}）")
                    if position not in ("any", POSITION_COMMAND_CODE):
                        raise PlanError(
                            f"这张卡同时给了 engraved_code=「{engraved}」和 position=「{position}」："
                            "执行层靠纹章识别定卡位，请把 position 删掉（位置规则不可依赖）"
                        )
                    position = POSITION_COMMAND_CODE
                label = (
                    f"{_actor_label(team, actor_slot, actor)} {color} 卡（刻「{engraved}」的那张）"
                    if engraved
                    else f"{_actor_label(team, actor_slot, actor)} {color} 卡（{position}）"
                )
                pending.append(
                    Action(kind=CARD, label=label, turn=turn,
                           actor_slot=actor_slot, card_color=color, position=position,
                           crit=bool(step.get("crit")),
                           command_code=engraved,
                           expect_before=SCENE_CARD_SELECT, expect_after=SCENE_CARD_SELECT,
                           fills_slot=True)
                )
            else:
                raise PlanError(f"不支持的步骤类型：{kind}")

        if slots_used == 0:
            plan.actions.extend(pending)
            continue
        if slots_used != SLOTS_PER_TURN:
            raise PlanError(
                f"第 {turn} 回合排了 {slots_used} 个出手卡位，必须正好 {SLOTS_PER_TURN} 个"
                "（宝具占 1 位）"
            )
        # 技能在前、然后进选牌界面、再按 spec 顺序出宝具与指令卡；
        # 填满第 3 个卡位的那个动作会自动触发执行。
        card_actions = [action for action in pending if action.fills_slot]
        skill_actions = [action for action in pending if not action.fills_slot]
        # 填满第 3 个卡位的那个动作会立刻触发执行，界面随即进入演出，不能再要求它是选牌界面
        card_actions[-1] = replace(card_actions[-1], expect_after=SCENE_ANY)
        attack = Action(kind=ATTACK, label="攻击（进入选牌界面）", turn=turn,
                        expect_before=SCENE_BATTLE_MAIN, expect_after=SCENE_CARD_SELECT)
        plan.actions.extend(skill_actions)
        plan.actions.append(attack)
        plan.actions.extend(card_actions)
        plan.actions.append(
            Action(kind=WAIT, label="等这一回合结算完", turn=turn,
                   expect_before=SCENE_ANY, expect_after=SCENE_BATTLE_MAIN, note="auto_execute")
        )
    return plan


def main(argv: list[str] | None = None) -> int:
    """CLI：读一份 spec JSON，打印编译出的动作流（不驱动设备）。"""
    import argparse

    parser = argparse.ArgumentParser(description="编译固定轮转 spec -> 可执行动作流")
    parser.add_argument("spec", help="spec JSON 文件路径")
    args = parser.parse_args(argv if argv is not None else None)
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    plan = compile_plan(spec)
    print(plan.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
