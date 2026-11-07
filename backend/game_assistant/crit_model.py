"""必定暴击（guaranteed critical）闸门。

用户规则（2026-10-08 定稿）：概率性方案不可接受，只有同时满足下列条件才能把暴击
当成方案的一部分，否则必须如实报告闸门未通过。

1. **确定的暴击星收入 ≥ 50**：技能即时出星、每回合出星、御主礼装出星。攻击产生的
   暴击星是随机的（受暴击星发生率与随机分布影响），因此**不计入保证**。
   星会跨回合保留，所以补刀回合前累计即可。
2. **星要集中到预定打手**：打手自身带集中度提升，或有队友/御主礼装给他上集中度，
   或其他人被排除抽卡（``donotSelectCommandcard``，手牌里只剩打手自己的卡，
   星自然集中在他身上）。
3. **指令卡抽取必须确定**：手牌固定（``fixCommandcard``）或其他人被排除抽卡。
4. **顺序必须自洽**：洗牌会移除此前的手牌固定（奥尔加玛丽「空前绝后 EX」自带重抽，
   泳装 BB 的「无貌之月 EX」手牌固定必须在他之后使用）；换人同样会移除（换人尚未建模）。

攻击产生的星、暴击星发生率（``star_drop_up``）都只作为**信息**报告，不参与判定。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .combat_domain import TeamPlanAction

STAR_THRESHOLD = 50.0
CRIT_DAMAGE_MULTIPLIER = 2.0

# 用户 2026-10-09 确认的机制：
# - 每回合可以出 3 张卡，宝具卡与普通指令卡各占 1 个卡位（两发宝具后仍能出 1 张卡补刀）。
# - 单张指令卡最多 10 颗暴击星 = 100% 暴击率（1 颗星 = 10%），单卡上限 100%。
# - 因此 50 颗星 = 5 张卡各 10 颗 = 全手牌满暴；一张暴击卡最多消耗 10 颗星。
# - 宝具卡不会暴击，也不消耗暴击星。
CARDS_PER_TURN = 3
CRIT_STARS_PER_CARD = 10.0
CRIT_RATE_PER_STAR = 0.10
MAX_CRIT_RATE_PER_CARD = 1.0

CONTROL_HAND_FIXED = "hand_fixed"
CONTROL_OTHERS_LOCKED = "others_locked"
CONTROL_SHUFFLE = "shuffle"

CONTROL_LABELS = {
    CONTROL_HAND_FIXED: "手牌固定",
    CONTROL_OTHERS_LOCKED: "其他人无法选择指令卡",
    CONTROL_SHUFFLE: "重新抽取指令卡（洗牌）",
}


@dataclass
class StarTick:
    turn: int
    gained: float
    source: str


@dataclass
class CritGate:
    crit_slot: int = 0
    crit_turn: int = 3
    passed: bool = False
    stars_available: float = 0.0
    star_threshold: float = STAR_THRESHOLD
    planned_crit_cards: int = 1
    stars_consumed: float = 0.0
    crit_card_position: int = 1
    star_ticks: list[StarTick] = field(default_factory=list)
    concentrated: bool = False
    concentration_source: str = ""
    card_access: str = ""
    control_order_notes: list[str] = field(default_factory=list)
    crit_rate_up: float = 0.0
    crit_damage_up: float = 0.0
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def crit_damage_multiplier(self) -> float:
        return CRIT_DAMAGE_MULTIPLIER * (1.0 + self.crit_damage_up)

    def plan(self, attacker_name: str, card_type: str, card_position: int = 1) -> list[str]:
        """生成给人的判定说明（每一项都对应一条已定稿规则）。"""
        lines = [
            f"必定暴击闸门：{'通过' if self.passed else '未通过'}"
            f"（第 {self.crit_turn} 回合由 {attacker_name} 补刀）",
            f"暴击星：确定来源合计 {self.stars_available:.0f}／门槛 {self.star_threshold:.0f}",
            f"星消耗：本次安排 {self.planned_crit_cards} 张暴击卡，"
            f"每张最多消耗 {CRIT_STARS_PER_CARD:.0f} 颗（1 颗 = {CRIT_RATE_PER_STAR * 100:.0f}% 暴击率，"
            f"单卡上限 {MAX_CRIT_RATE_PER_CARD * 100:.0f}%），合计 {self.stars_consumed:.0f} 颗",
            f"卡位：每回合 {CARDS_PER_TURN} 张，宝具卡也占 1 个卡位；"
            "宝具不会暴击、也不消耗暴击星",
            f"门槛含义：{self.star_threshold:.0f} 星 = 5 张卡各 {CRIT_STARS_PER_CARD:.0f} 星 = 全部满暴",
        ]
        for tick in self.star_ticks:
            lines.append(f"　第 {tick.turn} 回合：{tick.source} +{tick.gained:.0f} 星")
        if self.concentrated:
            lines.append(f"集中：{self.concentration_source}")
        else:
            lines.append("集中：没有集中手段，星会分摊给队友")
        if self.card_access:
            lines.append(f"指令卡：{self.card_access}")
        else:
            lines.append("指令卡：无法确定为打手拿到需要的卡")
        for note in self.control_order_notes:
            lines.append(f"　顺序：{note}")
        lines.append(
            f"暴击威力：基础 ×{CRIT_DAMAGE_MULTIPLIER:.1f}，暴击威力提升 {self.crit_damage_up * 100:.0f}%"
            f" → ×{self.crit_damage_multiplier:.2f}"
            f"；暴击发生率提升 {self.crit_rate_up * 100:.0f}%"
        )
        lines.append(f"补刀卡色：{card_type}（本回合第 {card_position} 个卡位，按该位置倍率计算）")
        for blocker in self.blockers:
            lines.append(f"未通过原因：{blocker}")
        lines.extend(self.notes)
        return lines


def _control_events(actions: list[TeamPlanAction]) -> list[tuple[int, int, int, str, str, int]]:
    """收集发牌控制事件：``(回合, 顺序, 施放者, 控制类型, 目标域, 持续回合)``。"""
    events: list[tuple[int, int, int, str, str, int]] = []
    for action in actions:
        if action.action_type == "switch":
            events.append((action.turn, action.order, action.actor_slot, "switch", "", 0))
        for effect in action.effects:
            if effect.effect_type != "control":
                continue
            raw = str(effect.notes or effect.source)
            slug, _, tail = raw.partition("|")
            target = tail.partition("=")[2].strip() if "=" in tail else ""
            slug = slug.strip()
            if slug:
                events.append(
                    (
                        action.turn,
                        action.order,
                        action.actor_slot,
                        slug,
                        target,
                        int(effect.duration_turns or 1) or 1,
                    )
                )
    events.sort(key=lambda item: (item[0], item[1]))
    return events


def effective_card_control(
    actions: list[TeamPlanAction],
    crit_turn: int = 3,
) -> tuple[set[int], set[int], list[str]]:
    """按施放顺序折叠发牌控制。

    返回 ``(手牌固定仍有效的施放者, 唯一可被选卡的从者集合, 顺序说明)``。

    目标域决定语义（这一步不能省）：

    - ``fixCommandcard``（手牌固定）作用于施放者自己，但锁的是**整副手牌**，
      官方文本写明「若队员变更或手牌被洗牌则强制解除」——所以洗牌会让它失效。
    - ``donotSelectCommandcard`` 若目标是 ``ally_other``（例：奥尔加玛丽「空前绝后 EX」
      的 ptOther），表示**其他人无法选择指令卡**，于是只有施放者本人能被选，
      这才是给自己做必定暴击的手段；若目标是自己，那是对自己的惩罚，对暴击没有帮助。

    洗牌会让此前的手牌固定失效——这是用户点名要校验的冲突
    （泳装 BB 的手牌固定遇上奥尔加玛丽的重抽）。
    """
    fixed_actors: set[int] = set()
    exclusive_actors: set[int] = set()
    notes: list[str] = []
    expired: list[str] = []
    for turn, _order, actor, slug, target, duration in _control_events(actions):
        expiry = turn + max(1, duration) - 1
        if duration > 0 and expiry < crit_turn and slug in {CONTROL_HAND_FIXED, CONTROL_OTHERS_LOCKED}:
            expired.append(
                f"第 {turn} 回合的「{CONTROL_LABELS.get(slug, slug)}」只持续到第 {expiry} 回合，"
                f"补刀回合（第 {crit_turn} 回合）已失效——必须把该技能留到补刀回合使用"
            )
            continue
        if slug == CONTROL_HAND_FIXED:
            fixed_actors.add(actor)
            notes.append(f"第 {turn} 回合：手牌固定生效，持续到第 {expiry} 回合（洗牌或换人会解除）")
        elif slug == CONTROL_OTHERS_LOCKED:
            if target in {"ally_other", "ptOther", ""}:
                exclusive_actors.add(actor)
                notes.append(
                    f"第 {turn} 回合：其他人无法选择指令卡 → 只有该从者能被选（持续到第 {expiry} 回合）"
                )
            else:
                notes.append(f"第 {turn} 回合：施放者自己的卡被锁（对暴击没有帮助）")
        elif slug == CONTROL_SHUFFLE:
            if fixed_actors:
                fixed_actors.clear()
                notes.append(f"第 {turn} 回合：洗牌移除了此前的手牌固定（顺序冲突，必须把洗牌放在手牌固定之前）")
            else:
                notes.append(f"第 {turn} 回合：洗牌（未影响手牌固定）")
        elif slug == "switch":
            if fixed_actors or exclusive_actors:
                fixed_actors.clear()
                exclusive_actors.clear()
                notes.append(f"第 {turn} 回合：换人解除了此前的手牌固定/选卡限制")
            else:
                notes.append(f"第 {turn} 回合：换人（未影响手牌固定）")
    notes.extend(expired)
    return fixed_actors, exclusive_actors, notes


def _star_ticks(actions: list[TeamPlanAction], crit_turn: int, names: dict[int, str]) -> list[StarTick]:
    ticks: list[StarTick] = []
    for action in actions:
        if action.turn > crit_turn:
            continue
        actor = names.get(action.actor_slot, f"槽位{action.actor_slot}")
        for effect in action.effects:
            if effect.effect_type == "stars":
                ticks.append(StarTick(turn=action.turn, gained=effect.value, source=f"{actor} 即时出星"))
            elif effect.effect_type == "stars_per_turn":
                remaining = max(1, crit_turn - action.turn + 1)
                active = min(remaining, int(effect.duration_turns or remaining) or remaining)
                ticks.append(
                    StarTick(
                        turn=action.turn,
                        gained=effect.value * active,
                        source=f"{actor} 每回合 {effect.value:.0f} 星 × {active} 回合",
                    )
                )
    return ticks


def _targeted_buff(
    actions: list[TeamPlanAction],
    crit_slot: int,
    kinds: tuple[str, ...],
    card: str = "",
) -> float:
    """统计指向打手的增益。``card`` 非空时，只统计通用与该卡色的效果。"""
    total = 0.0
    for action in actions:
        for effect in action.effects:
            if effect.effect_type not in kinds:
                continue
            effect_card = str(effect.card or "")
            if card and effect_card and effect_card != card:
                continue
            recipient = effect.target_actor_slot or action.actor_slot
            if recipient == crit_slot:
                total += effect.value
    return total


def evaluate_crit(
    *,
    actions: list[TeamPlanAction],
    crit_slot: int,
    names: dict[int, str],
    crit_turn: int = 3,
    mystic_code: Any | None = None,
    star_threshold: float = STAR_THRESHOLD,
    crit_card: str = "",
    planned_crit_cards: int = 1,
    command_code_stars: list[tuple[str, float]] | None = None,
    command_code_focus: float = 0.0,
    command_code_focus_source: str = "",
    command_code_critical_up: float = 0.0,
    command_code_critical_source: str = "",
) -> CritGate:
    """按用户规则判定是否**必定暴击**。"""
    gate = CritGate(
        crit_slot=crit_slot,
        crit_turn=crit_turn,
        star_threshold=star_threshold,
        planned_crit_cards=max(1, planned_crit_cards),
    )
    gate.stars_consumed = CRIT_STARS_PER_CARD * gate.planned_crit_cards
    gate.star_ticks = _star_ticks(actions, crit_turn, names)
    for source, value in command_code_stars or []:
        if value > 0:
            gate.star_ticks.append(
                StarTick(turn=1, gained=value, source=f"指令纹章 {source}（前序卡出星）")
            )

    if mystic_code is not None:
        mc_stars = float(mystic_code.stars())
        if mc_stars:
            gate.star_ticks.append(
                StarTick(turn=1, gained=mc_stars, source=f"御主礼装 {mystic_code.name} 出星")
            )
        mc_weight = sum(
            effect.value
            for effect in getattr(mystic_code, "effects", [])
            if effect.kind == "star_weight_up"
            and (not crit_card or not effect.card or effect.card == crit_card)
        )
        mc_weight_card = next(
            (
                effect.card
                for effect in getattr(mystic_code, "effects", [])
                if effect.kind == "star_weight_up"
                and (not crit_card or not effect.card or effect.card == crit_card)
            ),
            "",
        )
    else:
        mc_weight = 0.0
        mc_weight_card = ""

    gate.stars_available = sum(tick.gained for tick in gate.star_ticks)

    fixed_actors, exclusive_actors, order_notes = effective_card_control(actions, crit_turn)
    gate.control_order_notes = order_notes
    exclusive = crit_slot in exclusive_actors
    if exclusive:
        gate.card_access = "其他人无法选择指令卡：只有补刀手本人能被选，必定拿到自己的卡"
    elif crit_slot in fixed_actors:
        gate.card_access = "手牌固定（牌面内容需人工确认）"

    weight_up = _targeted_buff(actions, crit_slot, ("star_weight_up",), card=crit_card)
    total_weight = weight_up + mc_weight + max(0.0, command_code_focus)
    if total_weight > 0:
        gate.concentrated = True
        parts = []
        if weight_up > 0:
            parts.append(f"队友/自身集中度提升 {weight_up * 100:.0f}%")
        if mc_weight > 0:
            suffix = f"（{mc_weight_card}卡）" if mc_weight_card else ""
            parts.append(f"御主礼装 {getattr(mystic_code, 'name', '')} 集中度提升 {mc_weight * 100:.0f}%{suffix}")
        if command_code_focus > 0:
            parts.append(
                f"指令纹章 {command_code_focus_source or '集中纹章'} "
                f"集中度提升 {command_code_focus * 100:.0f}%"
            )
        gate.concentration_source = "，".join(parts)
    elif exclusive:
        gate.concentrated = True
        gate.concentration_source = "其他人无法选择指令卡，星只能落在该从者的卡上"

    gate.crit_rate_up = _targeted_buff(actions, crit_slot, ("crit_rate_up",), card=crit_card)
    gate.crit_damage_up = _targeted_buff(
        actions, crit_slot, ("critical_up",), card=crit_card
    ) + max(0.0, command_code_critical_up)
    if command_code_critical_up > 0:
        gate.notes.append(
            f"指令纹章 {command_code_critical_source or '暴伤纹章'} "
            f"暴击威力 +{command_code_critical_up * 100:.0f}%"
        )

    if gate.stars_available + 1e-9 < star_threshold:
        gate.blockers.append(
            f"确定的暴击星只有 {gate.stars_available:.0f}，低于门槛 {star_threshold:.0f}"
            f"（{star_threshold:.0f} 星 = 5 张卡各 {CRIT_STARS_PER_CARD:.0f} 星 = 全部满暴；"
            "攻击产生的星是随机的，不计入保证）"
        )
    if not gate.concentrated:
        gate.blockers.append("没有把暴击星集中到补刀手身上的手段（需要集中度提升，或让其他人无法选择指令卡）")
    if not gate.card_access:
        gate.blockers.append("无法确定为补刀手抽到需要的指令卡（需要手牌固定，或让其他人无法选择指令卡）")
    if gate.crit_rate_up <= 0 and gate.stars_available < star_threshold:
        gate.notes.append("打手没有暴击发生率提升，完全依赖星数达标。")

    gate.passed = not gate.blockers
    return gate
