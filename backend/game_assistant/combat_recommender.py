"""Quest-specific 3T team recommendation: main DPS + supports + charge gate.

Scope and honesty rules
-----------------------
The plan structure is ``主输出 + 辅助 + 羁绊位`` instead of three attackers. A
support is ranked by what it actually gives the main damage dealer (instant NP
charge and ally-targeted buffs), taken from real catalog skill data at the
servant's *current* skill levels.

The simplified simulator still does not model attack-based NP gain, critical
stars, or enemy actions, so the charge gate combines real skill charge with one
documented assumption constant (``ASSUMED_NP_GAIN_PER_TURN``). Every assumption
is reported on the option, and any unmodeled remainder is listed in
``missing_data`` / ``failure_conditions`` rather than being hidden.

This module never writes to the account database and never starts a battle.
"""
from __future__ import annotations

from pathlib import Path

import config
from dataclasses import dataclass, field
from datetime import datetime

from .account_store import AccountSnapshotStore
from .combat_assumptions import get_combat_assumptions
from .combat_traits import (
    ATLAS_ATTRIBUTE_TAGS,
    ATLAS_CLASS_TAGS,
    common_enemy_traits,
    condition_is_resolvable,
    condition_satisfied,
    enemy_trait_set,
)
from .combat_domain import (
    CombatEffect,
    CombatProfile,
    CombatantSnapshot,
    RecommendationConstraints,
    RecommendationOption,
    RecommendationRequest,
    RecommendationResult,
    RecommendedServant,
    SimulationRequest,
    TeamPlan,
    TeamPlanAction,
)
from .combat_simulator import simulate
from .damage_constants import combined_class_multiplier
from . import command_codes
from .combat_store import CombatStore
from .servant_stats import (
    NP_CARD_NAME,
    ServantStatsStore,
    get_servant_stats,
    np_multiplier,
    np_special_multiplier,
)
from .skill_effects import SkillTableStore, get_skill_table
from .mystic_code import MysticCodeProfile, MysticCodeTable
from .crit_model import (
    CONTROL_HAND_FIXED,
    CONTROL_OTHERS_LOCKED,
    CRIT_DAMAGE_MULTIPLIER,
    evaluate_crit,
)
from .craft_essence import get_craft_essence_store

# --- 可见假设常量（不是隐藏调参）------------------------------------------
ASSUMED_CE_ATTACK = 2000.0        # 每名出战从者按一张 +2000 攻击力的礼装计算
ASSUMED_ATK_FOU = 2000.0          # 满级 2000/2000 芙芙（与已验证实机配置一致）
# 本期倍卡礼装（用户 2026-10-09 确认）：满破提供 +100% 攻击威力（伤害翻倍）与开局 +50% 宝具值。
# 它不是“假设可用”的通用礼装，而是本期确定在用的资源：默认打在打手身上，并占用 1 个礼装位。
EVENT_DAMAGE_CE_NAME = "本期倍卡礼装（满破）"
EVENT_DAMAGE_CE_DAMAGE_UP = 1.0   # +100% 伤害
EVENT_DAMAGE_CE_START_NP = 0.5    # 开局 +50% 宝具值
ASSUMED_START_NP = 1.0            # 第 1 回合由开局充能礼装/追加技能假定的宝具值
ASSUMED_NP_GAIN_PER_TURN = 0.2    # 攻击回收宝具值的保守估计（模拟器未建模）
NOMINAL_COMBATANT_HP = 10000.0    # 模拟器不使用我方生命值
NP_COST = 1.0                     # 每次宝具消耗 100% 宝具值
SUPPORT_SLOTS = 3                 # 非羁绊从者上限 4（1 主输出 + 3 辅助），留 ≥2 个羁绊位
SECONDARY_SLOTS = 1               # 第二个输出点：负责补掉主输出覆盖不到的敌人
# 补刀回合最多用几张暴击卡：每回合 3 个卡位，宝具各占 1 个，剩下的都能出卡。
MAX_CRIT_CARDS = 2
APPEND_START_NP_MIN = 0.10        # 追加技能2「魔力装填」Lv1：开局 +10% 宝具值
APPEND_START_NP_MAX = 0.20        # Lv10：开局 +20%
# 开局充能礼装档位。使用礼装会占用一个“掉落加成位”，所以方案优先不用礼装。
CHARGE_CE_TIERS = (
    (0.5, "开局充能礼装（+50% 宝具值）"),
    (1.0, "满破开局充能礼装（+100% 宝具值）"),
)
DROP_CE_SLOTS_TOTAL = 6           # 六名出战位都可挂礼装
MAX_BUFF_SUM = 3.0                # 增益合计上限，避免叠加失控
CRIT_TURN = 3                     # 暴击补刀固定在最后一回合
# 每回合 3 个卡位（用户确认：宝具卡与指令卡各占 1 个卡位）。
CARDS_PER_TURN = 3
# 指令纹章「花之魔术师」：**打出带该纹章的指令卡即无条件获得 +10% 宝具值**，
# 与卡色、是否暴击都无关（用户 2026-10-10 澄清）。纹章是“打在具体某张卡上”的配置，
# 所以这里按 从者 → 卡色 记录实际配置；本场景打在所长的蓝卡上，其它活动可能换人/换卡。
# 指令纹章的「使用该卡攻击时宝具值 +N%」按**点数**记（与 np_change 同一口径：100 = 100%）。
# 此前这里写的是 0.10，等于只加 0.1 点，实际是 0 效果（2026-10-12 修正）。
COMMAND_CODE_CHARGE: dict[str, dict[str, object]] = {
    "U－奥尔加玛丽": {"card": "arts", "charge": 10.0, "code": "花之魔术师"},
}

_COMMAND_CODE_LIBRARY: dict[str, object] | None = None


def _command_code_library() -> dict[str, object]:
    """惰性加载指令纹章库（只有用户指定了纹章时才读）。"""
    global _COMMAND_CODE_LIBRARY
    if _COMMAND_CODE_LIBRARY is None:
        _COMMAND_CODE_LIBRARY = command_codes.load_codes(
            Path(config.GAME_ASSISTANT_KB_DIR) / "command_codes_cn.json"
        )
    return _COMMAND_CODE_LIBRARY


SUPPORT_CHARGE_WEIGHT = 2.0       # 辅助排序：充能权重高于增伤
SUPPORT_BUFF_WEIGHT = 1.0
SUPPORT_STAR_WEIGHT = 0.5
# 能自己做成必定暴击的辅助（例：奥尔加玛丽的「空前绝后 EX」让其他人无法选择指令卡）
# 在宝具打不完血量时能补刀，所以单独给权重。
CRIT_FINISHER_WEIGHT = 1.5
CRIT_HAND_FIX_WEIGHT = 0.5

TRIANGLE = {
    "Saber": "Lancer",
    "Lancer": "Archer",
    "Archer": "Saber",
    "Rider": "Caster",
    "Caster": "Assassin",
    "Assassin": "Rider",
}
BERSERKER_TARGETS = {"Saber", "Archer", "Lancer", "Rider", "Caster", "Assassin"}
EXTRA_CLASSES = {"Ruler", "Avenger", "Alterego", "MoonCancer", "Pretender", "Foreigner", "Shielder", "Beast"}

NP_BUFF_KINDS = ("attack_up", "card_up", "np_damage_up", "power_modifier", "card_resist_down", "np_resist_down")
CRIT_BUFF_KINDS = ("critical_up", "crit_rate_up", "star_weight_up", "star_drop_up")
ALLY_TARGETS = {"ally_one", "ally_all"}

# 解析层效果 -> 契约效果类型
EFFECT_TO_DOMAIN = {
    "attack_up": "attack_up",
    "card_up": "card_up",
    "card_resist_down": "card_up",
    "np_damage_up": "np_damage_up",
    "np_resist_down": "np_damage_up",
    "power_modifier": "power_modifier",
    "flat_damage": "flat_damage",
    "critical_up": "critical_up",
    "crit_rate_up": "crit_rate_up",
    "star_weight_up": "star_weight_up",
    "stars": "stars",
    "stars_per_turn": "stars_per_turn",
    "control": "control",
    "defense_down": "defense_down",
    "charge": "charge",
    "np_regen": "charge",
}

# 这些效果的数值不是百分数：充能与宝具值是比例、出星是星数、发牌控制没有数值。
RAW_EFFECT_KINDS = {"charge", "flat_damage", "stars", "stars_per_turn", "control"}
# 还没建模、但确实会抬高伤害的效果：必须报给用户，而不是只留一个未建模计数。
UNMODELED_DAMAGE_LABELS = {
    "upChagetd": "过量充能阶级提升（宝具 OC 提高）",
    "upDropnp": "宝具值获取提升",
    "pierceInvincible": "无敌贯通",
    "pierceDefence": "防御贯通",
    "addIndividuality": "赋予特性",
    "commandattackAfterFunction": "指令卡追加效果",
}

# 指令卡：1=Arts 2=Buster 3=Quick（与图鉴 np_card 同一套编码）。
CARD_ID_TO_TYPE = {"1": "arts", "2": "buster", "3": "quick"}
FACE_CARD_LABELS = {"buster": "Buster", "arts": "Arts", "quick": "Quick", "extra": "Extra"}
# 补刀优先红卡：第 1 张位置的倍率 Buster 1.5 > Arts 1.0 > Quick 0.8。
FACE_CARD_PREFERENCE = ("buster", "arts", "quick")


def candidate_crit_cards(cards: list[str], np_card: str = "") -> list[str]:
    """补刀卡色候选：按伤害倍率从高到低（保守取第 1 张位置倍率）。

    同时给出多个候选是为了配合集中度：御主礼装/队友的集中度可能只覆盖某一卡色
    （例：夏日街头的 Arts 集中度对红卡补刀无效），选错卡色会把闸门判成通过。
    """
    owned = {CARD_ID_TO_TYPE.get(str(card), "") for card in cards or []}
    ordered = [card_type for card_type in FACE_CARD_PREFERENCE if card_type in owned]
    return ordered or [np_card or "buster"]


def best_crit_card(cards: list[str], np_card: str = "") -> str:
    return candidate_crit_cards(cards, np_card)[0]


def control_cast_turn(skill: dict, crit_turn: int = CRIT_TURN) -> int:
    """含发牌控制的技能要排在「补刀回合仍然生效」的时点。

    例：奥尔加玛丽的「空前绝后 EX」只锁 1 回合，必须留到补刀回合用；
    泳装 BB 的「无貌之月 EX」手牌固定 3 回合，第 1 回合用就能覆盖到第 3 回合。
    """
    turns = [
        max(1, crit_turn - max(1, int(effect.get("duration") or 1) or 1) + 1)
        for effect in skill.get("effects") or []
        if str(effect.get("kind")) == "control"
    ]
    return min(turns) if turns else 1


def shorten_total(item: dict, supports: list[dict], mystic_code: MysticCodeProfile | None) -> float:
    """打手能吃到的技能冷却缩减合计（回合数）。

    用户 2T 操作依赖三个来源叠加：所长技能 1 自身 −2、杀狐技能 1 给队友 −2、
    阿特拉斯院制服技能 3 再 −2，合计 −6，于是 7 回合冷却的技能能连续两回合使用。
    """
    total = 0.0
    for skill in item["summary"].buff_skills + item["summary"].charge_skills:
        for effect in skill.get("effects") or []:
            if str(effect.get("source")) == "shortenSkill" and str(effect.get("target")) == "self":
                total += float(effect.get("value") or 0)
    for support in supports:
        for skill in support["summary"].buff_skills + support["summary"].charge_skills:
            for effect in skill.get("effects") or []:
                if str(effect.get("source")) == "shortenSkill" and str(effect.get("target")) in {"ally_one", "ally_all"}:
                    total += float(effect.get("value") or 0)
    if mystic_code is not None:
        total += sum(
            effect.value for effect in getattr(mystic_code, "effects", []) if effect.kind == "shorten_skill"
        )
    return total


def skill_cooldown(skill: dict) -> int:
    cooldowns = [int(value) for value in (skill.get("cooldowns") or []) if isinstance(value, (int, float))]
    return cooldowns[-1] if cooldowns else 0


def class_multiplier(attacker_class: str, defender_class: str) -> float:
    """Atlas 职阶攻击率 × 职阶克制倍率（含 Beast 等额外职阶）。"""
    return combined_class_multiplier(attacker_class, defender_class)


def relation_encoding(multiplier: float) -> tuple[str, float]:
    """把 FGO 倍率拆成模拟器支持的 关系桶 + class_attack_modifier。"""
    if multiplier > 1.0:
        return "advantage", multiplier / 2.0
    if multiplier < 1.0:
        return "disadvantage", multiplier / 0.5
    return "neutral", 1.0


def dominant_enemy_class(profile: CombatProfile) -> str:
    weights: dict[str, int] = {}
    for wave in profile.waves:
        for unit in wave.units:
            weights[unit.class_name] = weights.get(unit.class_name, 0) + unit.hp * unit.count
    if not weights:
        return ""
    return max(weights.items(), key=lambda item: item[1])[0]


@dataclass
class FriendServant:
    """目录侧（未持有）的从者，用于「借好友助战」评估。

    账号快照里没有他的练度，所以投入按**保守假设**处理并写进方案说明：
    Lv90 / 宝具 1 / 技能 10 / 追加技能未解锁。
    """

    name: str
    class_name: str
    rarity: int = 5
    level: int = 90
    np_level: int = 1
    skill_1: int = 10
    skill_2: int = 10
    skill_3: int = 10
    append_2: int = 0


FRIEND_SUPPORT_ASSUMPTION = (
    "好友助战按目录数据评估（Lv90 / 宝具1 / 技能10 / 追加技能未解锁），"
    "实际强度取决于好友的练度，正式执行前必须确认。"
)

@dataclass
class SkillSummary:
    """一个从者当前练度下能提供/享有的效果汇总。"""

    ally_charge: float = 0.0
    self_charge: float = 0.0
    ally_buffs: dict[str, float] = field(default_factory=dict)
    self_buffs: dict[str, float] = field(default_factory=dict)
    defense_down: float = 0.0
    stars: float = 0.0
    stars_per_turn: float = 0.0
    control: list[str] = field(default_factory=list)
    charge_skills: list[dict] = field(default_factory=list)
    buff_skills: list[dict] = field(default_factory=list)
    unmodeled: int = 0
    modelling_notes: list[str] = field(default_factory=list)

    @staticmethod
    def _sum(buffs: dict[str, float], kinds: tuple[str, ...], card: str) -> float:
        """只累计通用效果与匹配卡色的效果。

        key 形如 `card_up`（通用）或 `card_up@buster`（只对红卡生效）。
        卡色不匹配的效果必须被排除——这是“红卡辅助配绿卡打手”这类错误的根源。
        """
        total = 0.0
        for key, value in buffs.items():
            kind, _, restricted = key.partition("@")
            if kind not in kinds:
                continue
            if restricted and restricted != card:
                continue
            total += value
        return min(MAX_BUFF_SUM, total)

    def ally_np_buff_sum(self, card: str) -> float:
        return self._sum(self.ally_buffs, NP_BUFF_KINDS, card)

    def self_np_buff_sum(self, card: str) -> float:
        return self._sum(self.self_buffs, NP_BUFF_KINDS, card)

    def ally_crit_buff_sum(self, card: str) -> float:
        return self._sum(self.ally_buffs, CRIT_BUFF_KINDS, card)

    def self_crit_buff_sum(self, card: str) -> float:
        return self._sum(self.self_buffs, CRIT_BUFF_KINDS, card)


def summarize_skills(
    entry: dict | None,
    levels: dict[int, int],
    enemy_traits: set[str] | None = None,
) -> SkillSummary:
    """按从者当前技能等级汇总效果；目标域严格区分 self 与队友。

    同一技能槽会有多个再临形态的变体（例如奥尔加玛丽的 6 条记录＝3 槽 × 2 形态）。
    这里**每个槽只取第一条**（第一/第二再临形态），并把该假定写进方案说明；
    否则两种形态的效果会被同时累加，数值直接翻倍。
    """
    summary = SkillSummary()
    if not entry:
        return summary
    seen_slots: set[int] = set()
    for skill in entry.get("skills") or []:
        slot = int(skill.get("slot") or 0)
        if slot in seen_slots:
            continue
        seen_slots.add(slot)
        level = int(levels.get(slot, 10) or 10)
        skill_has_charge = False
        repeated: dict[tuple, int] = {}
        for effect in skill.get("effects") or []:
            kind = str(effect.get("kind"))
            target = str(effect.get("target") or "")
            values = effect.get("values") or []
            value = float(values[level - 1]) if len(values) >= level else float(effect.get("value") or 0.0)
            condition = str(effect.get("condition") or "")
            # 条件增益（特攻/场地/血量阈值）没有敌人特性数据可核对，不能按固定收益算。
            counted_condition = condition and condition_satisfied(condition, enemy_traits)
            if counted_condition:
                label = str(effect.get("condition_label") or "")
                note = f"{skill.get('name')}：{label or condition} 本次关卡满足条件，已计入收益"
                if note not in summary.modelling_notes:
                    summary.modelling_notes.append(note)
            elif condition and kind not in {"charge", "stars", "control"}:
                label = str(effect.get("condition_label") or "")
                note = f"{skill.get('name')}：{label or kind} 只在满足条件时生效，未计入收益"
                if note not in summary.modelling_notes:
                    summary.modelling_notes.append(note)
                continue
            if kind == "charge":
                skill_has_charge = True
                if target in ALLY_TARGETS:
                    summary.ally_charge += value
                elif target == "self":
                    summary.self_charge += value
            elif kind in NP_BUFF_KINDS or kind in CRIT_BUFF_KINDS:
                # 与 emit 阶段保持一致：增益统一换算成小数（30% -> 0.3），
                # 否则评分用的百分数会与实际伤害口径不一致。
                value = value / 100.0
                card = str(effect.get("card") or "")
                key = f"{kind}@{card}" if card else kind
                repeated[(kind, card, target, tuple(values))] = repeated.get((kind, card, target, tuple(values)), 0) + 1
                if target in ALLY_TARGETS:
                    summary.ally_buffs[key] = summary.ally_buffs.get(key, 0.0) + value
                elif target == "self":
                    summary.self_buffs[key] = summary.self_buffs.get(key, 0.0) + value
            elif kind == "defense_down":
                summary.defense_down += value / 100.0
                repeated[(kind, "", target, tuple(values))] = repeated.get((kind, "", target, tuple(values)), 0) + 1
            elif kind == "stars":
                summary.stars += value
            elif kind == "stars_per_turn":
                summary.stars_per_turn += value
            elif kind == "control":
                # 目标域必须一起记下来：donotSelectCommandcard 作用于队友才是
                # “其他人无法选择指令卡”（自己必定能做暴击），作用于自己则相反。
                summary.control.append(f"{effect.get('source')}|{target}")
            elif kind in {"unmodeled", "unmapped"}:
                summary.unmodeled += 1
                # 会影响伤害但没建模的效果必须显式报出来，不能只留一个计数。
                label = UNMODELED_DAMAGE_LABELS.get(str(effect.get("source") or ""))
                if label:
                    note = f"{skill.get('name')}：{label}（未建模，实际收益高于估算）"
                    if note not in summary.modelling_notes:
                        summary.modelling_notes.append(note)
        # 图鉴里同一条增益可能出现多次（叠加/多形态）。数量不确定时明确提示，而不是默默取一个数。
        for (dup_kind, _dup_card, _dup_target, dup_values), count in repeated.items():
            if count < 2 or not any(dup_values):
                continue
            note = (
                f"{skill.get('name')}：图鉴里同一条「{dup_kind}」增益重复 {count} 次，"
                "当前按累加计入，实际层数需人工确认"
            )
            if note not in summary.modelling_notes:
                summary.modelling_notes.append(note)
        if skill_has_charge:
            summary.charge_skills.append(
                {
                    "slot": slot,
                    "level": level,
                    "name": skill.get("name"),
                    "effects": skill.get("effects"),
                    "cooldowns": list(skill.get("cooldowns") or []),
                }
            )
        else:
            summary.buff_skills.append(
                {
                    "slot": slot,
                    "level": level,
                    "name": skill.get("name"),
                    "effects": skill.get("effects"),
                    "cooldowns": list(skill.get("cooldowns") or []),
                }
            )
    return summary


def _skill_levels(servant) -> dict[int, int]:
    return {
        1: servant.skill_1 or 1,
        2: servant.skill_2 or 1,
        3: servant.skill_3 or 1,
    }


def append_start_np(level: int | None) -> float:
    """追加技能2「魔力装填」提供的开局宝具值（Lv1 +10% → Lv10 +20%）。

    这是账号自带的、不占用礼装位的充能来源，所以方案应优先依赖它。
    """
    value = int(level or 0)
    if value <= 0:
        return 0.0
    ratio = (min(value, 10) - 1) / 9.0
    return APPEND_START_NP_MIN + (APPEND_START_NP_MAX - APPEND_START_NP_MIN) * ratio


def _ce_requirements(functional_ce: int) -> list[str]:
    """按实际需要列出礼装要求；不指定功能礼装时明确说明掉落位全可用。"""
    items = [
        f"主输出：{EVENT_DAMAGE_CE_NAME}"
        f"（+{int(EVENT_DAMAGE_CE_DAMAGE_UP * 100)}% 伤害、开局 +{int(EVENT_DAMAGE_CE_START_NP * 100)}% 宝具值）"
    ]
    if functional_ce > 0:
        items.append(
            f"开局充能礼装 × {functional_ce}（与倍卡合计占用 {functional_ce + 1} 个位置，"
            f"仅 {max(0, DROP_CE_SLOTS_TOTAL - functional_ce - 1)} 个位置可挂本期氪金礼装）"
        )
    else:
        items.append(
            f"无需额外充能礼装：扣掉倍卡后还有 {DROP_CE_SLOTS_TOTAL - 1} 个位置可挂本期氪金礼装"
        )
    return items


def recommend(
    request: RecommendationRequest,
    store: CombatStore | None = None,
    account_store: AccountSnapshotStore | None = None,
    stats: ServantStatsStore | None = None,
    skills: SkillTableStore | None = None,
) -> RecommendationResult:
    combat_store = store or CombatStore()
    accounts = account_store or AccountSnapshotStore()
    stats_store = stats or get_servant_stats()
    skill_store = skills or get_skill_table()
    constraints = request.constraints

    profile = combat_store.get_profile(request.quest_id)
    if profile is None:
        raise ValueError(f"没有找到战斗档案：{request.quest_id}")

    enemy_class = dominant_enemy_class(profile)
    enemy_traits = common_enemy_traits(profile)
    # 每面敌人数量（含同种敌人的叠加数量），用于衡量宝具的覆盖面。
    wave_sizes = [sum(unit.count for unit in wave.units) for wave in profile.waves]
    average_wave_size = sum(wave_sizes) / len(wave_sizes) if wave_sizes else 1.0
    notes: list[str] = []
    if profile.mock:
        notes.append("当前战斗档案是 mock 数据，推荐结果只能作为流程演示。")
    if not profile.verified:
        notes.append("战斗档案尚未经游戏内实测确认，推荐结果属于候选方案。")
    if not skill_store.available():
        notes.append("缺少本地技能表，辅助增益与充能将全部按 0 计算。")

    excluded = {name.strip() for name in constraints.exclude_servants if name.strip()}
    missing_attack: list[str] = []
    extra_class_used: set[str] = set()
    ambiguous_matches: dict[str, str] = {}

    # 1) 先给所有从者算出：基础攻击、宝具倍率、自身增益、以及能给队友的充能/增伤
    pool: list[dict] = []
    for servant in accounts.list_servants():
        if servant.name in excluded:
            continue
        entry = stats_store.find(servant.name, servant.class_name, servant.rarity)
        attack_source = "atlas"
        if entry is None:
            attack = stats_store.median_attack(servant.class_name, servant.rarity) or 8000.0
            attack_source = "class_rarity_median"
            missing_attack.append(servant.name)
        else:
            attack = (
                stats_store.attack_at_level(entry, servant.level)
                or float(entry.get("atk_max") or 0.0)
            )
            if attack <= 0:
                attack = stats_store.median_attack(servant.class_name, servant.rarity) or 8000.0
                attack_source = "class_rarity_median"
                missing_attack.append(servant.name)
            attack += ASSUMED_ATK_FOU

        np_damage = np_multiplier(entry, servant.np_level) if entry else None
        # 宝具的「个体数」第二成分（例：所长宝具的〔拥有人、星之力〕特攻）。
        # 它的生效条件写在宝具文案里；本关敌人属性为「人」，因此成立。
        # 过量充能等级 = 1 + 自身的「过量充能阶级提升」合计（例：所长技能 2 给 +2 → OC3）。
        # 技能表在下面才取，所以这里先从技能表按名字查一次。
        skill_lookup = skill_store.find(servant.name, servant.class_name, servant.rarity)
        overcharge_bonus = 0
        if skill_lookup:
            for skill in skill_lookup.get("skills") or []:
                for effect in skill.get("effects") or []:
                    if str(effect.get("source")) == "upChagetd":
                        overcharge_bonus += int(float(effect.get("value") or 0))
        overcharge_level = min(5, 1 + overcharge_bonus)
        np_special = np_special_multiplier(entry, overcharge_level) if entry else 0.0
        if np_special and not (enemy_traits & {"attributeHuman", "attributeMan", "attributeSky"}):
            np_special = 0.0
        has_damage_np = bool(entry and (entry.get("np_damage_values") or []))
        if np_damage is None:
            np_damage = 6.0
        if entry and not has_damage_np:
            np_damage = 0.0  # 辅助型宝具：不能当主输出，但可以做辅助

        skill_entry = skill_store.find(servant.name, servant.class_name, servant.rarity)
        # 图鉴里存在同名同职阶的记录（如两条 `BB`：4★ 原版 / 5★ 水着），
        # 已经用账号稀有度消歧，但必须让用户看得见这件事本身。
        candidates = skill_store.candidates(servant.name, servant.class_name)
        distinct_numbers = {item.get("collection_no") for item in candidates}
        if len(distinct_numbers) > 1:
            chosen = skill_entry.get("collection_no") if skill_entry else None
            ambiguous_matches[servant.name] = (
                f"{servant.name}（{servant.class_name}）：图鉴有 {len(distinct_numbers)} 条同名记录 "
                f"{sorted(no for no in distinct_numbers if no is not None)}，"
                f"已按稀有度 {servant.rarity} 取 collection {chosen}"
            )
        summary = summarize_skills(skill_entry, _skill_levels(servant), enemy_traits)
        multiplier = class_multiplier(servant.class_name, enemy_class)
        if servant.class_name in EXTRA_CLASSES or enemy_class in EXTRA_CLASSES:
            extra_class_used.add(servant.class_name)
        pool.append(
            {
                "servant": servant,
                "entry": entry,
                "attack": attack,
                "attack_source": attack_source,
                "np_damage": np_damage,
                "np_special_multiplier": np_special,
                "has_damage_np": has_damage_np,
                "summary": summary,
                "multiplier": multiplier,
                "np_card": NP_CARD_NAME.get(int(entry["np_card"]), "") if entry and entry.get("np_card") else "",
                "card": (NP_CARD_NAME.get(int(entry["np_card"]), "") if entry and entry.get("np_card") else "").lower(),
                "np_target_type": str(entry.get("np_target_type") or "") if entry else "",
                "np_target": str((entry or {}).get("np_target") or "area"),
                "coverage": 1.0 if str((entry or {}).get("np_target") or "area") == "single" else max(1.0, average_wave_size),
                "levels": _skill_levels(servant),
                "cards": list((skill_entry or {}).get("cards") or []),
            }
        )

    if not pool:
        return RecommendationResult(
            quest_id=profile.quest_id,
            quest_name=profile.quest_name,
            profile_mock=profile.mock,
            profile_verified=profile.verified,
            dominant_enemy_class=enemy_class,
            constraints=constraints,
            options=[],
            notes=notes + ["没有可用从者，无法生成推荐方案。"],
            generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )

    # 借好友助战：把目录侧「未持有」的从者也放进候选池（`include_friend_support`）。
    if constraints.include_friend_support and skill_store.available():
        owned_keys = {(item["servant"].name, item["servant"].class_name) for item in pool}
        for entry in skill_store.servants:
            name = str(entry.get("name") or "")
            class_name = str(entry.get("class_name") or "")
            if not name or (name, class_name) in owned_keys or name in excluded:
                continue
            stats_entry = stats_store.find(name, class_name, entry.get("rarity"))
            if stats_entry is None:
                continue
            friend = FriendServant(name=name, class_name=class_name, rarity=int(entry.get("rarity") or 5))
            attack = (
                stats_store.attack_at_level(stats_entry, friend.level)
                or float(stats_entry.get("atk_max") or 0.0)
            ) + ASSUMED_ATK_FOU
            np_damage = np_multiplier(stats_entry, friend.np_level) or 6.0
            if not (stats_entry.get("np_damage_values") or []):
                np_damage = 0.0
            summary = summarize_skills(
                skill_store.find(name, class_name, entry.get("rarity")),
                _skill_levels(friend),
                enemy_traits,
            )
            multiplier = class_multiplier(class_name, enemy_class)
            pool.append(
                {
                    "servant": friend,
                    "entry": stats_entry,
                    "attack": attack,
                    "attack_source": "atlas",
                    "np_damage": np_damage,
                    "has_damage_np": bool(stats_entry.get("np_damage_values") or []),
                    "summary": summary,
                    "multiplier": multiplier,
                    "np_card": NP_CARD_NAME.get(int(stats_entry["np_card"]), "")
                    if stats_entry.get("np_card")
                    else "",
                    "card": (
                        NP_CARD_NAME.get(int(stats_entry["np_card"]), "").lower()
                        if stats_entry.get("np_card")
                        else ""
                    ),
                    "np_target_type": str(stats_entry.get("np_target_type") or ""),
                    "np_target": str(stats_entry.get("np_target") or "area"),
                    "coverage": 1.0
                    if str(stats_entry.get("np_target") or "area") == "single"
                    else max(1.0, average_wave_size),
                    "levels": _skill_levels(friend),
                    "cards": list(entry.get("cards") or []),
                    "friend": True,
                }
            )

    max_required = max(1, constraints.max_required_servants)
    remaining_slots = max(0, max_required - 1)
    secondary_count = min(SECONDARY_SLOTS, remaining_slots)
    support_count = max(0, min(SUPPORT_SLOTS, remaining_slots - secondary_count))

    def support_contribution(item: dict, dps_card: str) -> float:
        """某辅助对一个指定卡色主输出的实际贡献（卡色不匹配的增益不计入）。"""
        summary: SkillSummary = item["summary"]
        return (
            SUPPORT_CHARGE_WEIGHT * summary.ally_charge
            + SUPPORT_BUFF_WEIGHT * (summary.ally_np_buff_sum(dps_card) + summary.defense_down)
            + SUPPORT_STAR_WEIGHT * (summary.stars / 50.0)
            + crit_kit_value(summary)
        )

    def crit_kit_value(summary: SkillSummary) -> float:
        """辅助自带的“必定暴击”手段价值（可在宝具不足时补刀）。"""
        value = 0.0
        for entry in summary.control:
            slug, _, target = str(entry).partition("|")
            if slug == CONTROL_OTHERS_LOCKED and target in {"ally_other", ""}:
                value += CRIT_FINISHER_WEIGHT
            elif slug == CONTROL_HAND_FIXED:
                value += CRIT_HAND_FIX_WEIGHT
        return value

    dps_pool = [item for item in pool if item["has_damage_np"]] or pool

    def attacker_damage(item: dict, card: str, buff: float, defense_down: float) -> float:
        return (
            (item["attack"] + ASSUMED_CE_ATTACK)
            * item["multiplier"]
            * item["np_damage"]
            * item["coverage"]
            * (1.0 + min(MAX_BUFF_SUM, item["summary"].self_np_buff_sum(card) + buff))
            * (1.0 + min(MAX_BUFF_SUM, item["summary"].defense_down + defense_down))
        )

    # 2) 主输出 + 第二输出 + 辅助必须一起评估：
    #    同一辅助对不同卡色的价值不同，且第二输出要能补上主输出覆盖不到的目标
    #    （单体打手配光炮副手，或反之）。所以对每个主输出候选单独组队再比较。
    combos: list[tuple[float, dict, dict | None, list[dict]]] = []
    for dps in dps_pool:
        card = dps["card"]
        ranked = sorted(
            [
                item
                for item in pool
                if item["servant"].name != dps["servant"].name and support_contribution(item, card) > 0
            ],
            key=lambda item: (-support_contribution(item, card), item["servant"].name),
        )
        team = ranked[:support_count]
        team_buff = min(MAX_BUFF_SUM, sum(item["summary"].ally_np_buff_sum(card) for item in team))
        team_defense_down = min(MAX_BUFF_SUM, sum(item["summary"].defense_down for item in team))
        main_damage = attacker_damage(dps, card, team_buff, team_defense_down)

        secondary: dict | None = None
        secondary_damage = 0.0
        if secondary_count:
            excluded = {dps["servant"].name} | {item["servant"].name for item in team}
            best: tuple[float, dict] | None = None
            for candidate in dps_pool:
                if candidate["servant"].name in excluded:
                    continue
                # 副手只吃全体增益，且优先选择与主输出覆盖面互补的宝具类型
                complement = 1.35 if candidate["np_target"] != dps["np_target"] else 1.0
                value = (
                    attacker_damage(candidate, candidate["card"], 0.0, team_defense_down)
                    * complement
                )
                if best is None or value > best[0]:
                    best = (value, candidate)
            if best is not None:
                secondary = best[1]
                secondary_damage = best[0]
        combos.append((main_damage + secondary_damage, dps, secondary, team))
        # 单输出结构：不带第二输出，多带一名辅助。每回合只有 1 发宝具，
        # 于是第 3 回合空出 2 个卡位可以出双暴击卡（用户实测队伍就是这种结构：
        # 所长一个人输出 + 梅林 + 杀狐）。
        single_slots = max(0, remaining_slots)
        if single_slots > len(team):
            single_team = ranked[: min(SUPPORT_SLOTS + 1, single_slots)]
            single_buff = min(
                MAX_BUFF_SUM, sum(item["summary"].ally_np_buff_sum(card) for item in single_team)
            )
            single_defense_down = min(
                MAX_BUFF_SUM, sum(item["summary"].defense_down for item in single_team)
            )
            combos.append(
                (attacker_damage(dps, card, single_buff, single_defense_down), dps, None, single_team)
            )
    combos.sort(key=lambda row: (-row[0], row[1]["servant"].name))

    assumptions = [
        f"每名出战从者按满级 +{int(ASSUMED_ATK_FOU)} ATK 芙芙与一张 "
        f"+{int(ASSUMED_CE_ATTACK)} 攻击力的礼装计算。",
        "职阶攻击率与克制倍率使用 Atlas 全量表（含 Beast 等额外职阶），不再是额外职阶全按中性。",
        f"第 1 回合宝具按开局充能礼装/追加技能假定为 {int(ASSUMED_START_NP * 100)}%。",
        f"攻击回收宝具值按每回合 +{int(ASSUMED_NP_GAIN_PER_TURN * 100)}% 保守估计（模拟器未建模）。",
        "减伤、无敌、毅力等防御类效果未建模，只统计数量。",
        "宝具倍率取自图鉴并已乘卡色修正；技能增益按当前技能等级取值。",
    ]
    if constraints.include_friend_support:
        assumptions.append(FRIEND_SUPPORT_ASSUMPTION)
    assumed_ce_policy = (
        ["当前策略允许在推荐阶段假定必需礼装可用，正式执行前必须人工确认。"]
        if get_combat_assumptions().assume_required_craft_essences
        else []
    )
    required_ce_roles = [
        f"攻击力礼装（约 +{int(ASSUMED_CE_ATTACK)} ATK）",
        "开局充能礼装（第 1 回合宝具）",
        "充能/回收类礼装（若方案依赖连续宝具）",
    ]

    # 用户偏好：90++ 方案应尽量不指定礼装，好把位置留给本期掉落加成礼装。
    # 所以先按伤害取一批候选，生成计划后用“充能闸门 → 礼装占用更少 → 伤害更高”重排。
    candidates = combos[: max(constraints.max_options * 3, constraints.max_options)]
    built: list[tuple[RecommendationOption, bool, int]] = []
    for index, (_, primary, secondary, supports) in enumerate(candidates, start=1):
        lineup = [(primary, "main_dps")]
        if secondary is not None:
            lineup.append((secondary, "secondary_dps"))
        lineup += [(item, "support") for item in supports]
        mc_table = MysticCodeTable()
        # 优先用账号当前装备的御主礼装：实测操作依赖它的技能（阿特拉斯院制服冷却 −2）。
        mc_profile = mc_table.equipped() if mc_table.available() else None
        if mc_profile is None:
            mc_profile = mc_table.best_for(primary["card"], 1.0) if mc_table.available() else None
        (
            plan,
            option_servants,
            charge_plan,
            charge_ok,
            functional_ce,
            mc_name,
            mc_effect,
            crit_gate,
            crit_card_type,
        ) = _build_plan(
            profile=profile,
            lineup=lineup,
            index=index,
            enemy_class=enemy_class,
            mystic_code=mc_profile,
            enemy_traits=enemy_traits,
            assume_command_codes=list(constraints.assume_command_codes),
        )
        # 条件增益（特攻/场地/血量阈值）与图鉴重复条目的提示：不猜数值，交给人判断。
        modelling_notes: list[str] = []
        for note_item, _note_role in lineup:
            for note in note_item["summary"].modelling_notes:
                text = f"{note_item['servant'].name} {note}"
                if text not in modelling_notes:
                    modelling_notes.append(text)
            ambiguity = ambiguous_matches.get(note_item["servant"].name)
            if ambiguity and ambiguity not in modelling_notes:
                modelling_notes.append(ambiguity)
        simulation = simulate(SimulationRequest(profile=profile, plan=plan))
        combat_store.save_plan(plan)
        bond_slots = max(0, 6 - len(option_servants))
        built.append(
            (
            RecommendationOption(
                option_id=f"{request.quest_id}-opt{index}",
                title=f"方案 {index}：{primary['servant'].name} 为主输出"
                + (f" + {'、'.join(item['servant'].name for item in supports)}" if supports else ""),
                confidence=_confidence(
                    profile=profile,
                    simulation_status=simulation.status,
                    charge_ok=charge_ok,
                    fallback_count=sum(1 for item in option_servants if item.attack_source == "class_rarity_median"),
                    missing_attack=bool(missing_attack),
                ),
                required_servants=option_servants,
                bond_slots=bond_slots,
                charge_gate_passed=charge_ok,
                charge_plan=charge_plan,
                crit_gate_passed=crit_gate.passed,
                crit_plan=crit_gate.plan(
                    next(
                        (
                            combatant.name
                            for combatant in plan.combatants
                            if combatant.actor_slot == crit_gate.crit_slot
                        ),
                        primary["servant"].name,
                    ),
                    FACE_CARD_LABELS.get(crit_card_type, crit_card_type),
                    crit_gate.crit_card_position,
                ),
                functional_ce_count=functional_ce,
                drop_ce_slots=max(0, DROP_CE_SLOTS_TOTAL - functional_ce),
                mystic_code=mc_name,
                mystic_code_effect=mc_effect,
                assumed_craft_essences=list(required_ce_roles),
                required_craft_essences=_ce_requirements(functional_ce),
                plan=plan,
                simulation=simulation,
                minimum_investment=_minimum_investment(option_servants),
                alternatives=[
                    f"方案 {n}：{combos[n - 1][1]['servant'].name} 为主输出"
                    for n in range(1, len(combos[: constraints.max_options]) + 1)
                    if n != index
                ],
                failure_conditions=_failure_conditions(simulation, profile, charge_plan, charge_ok)
                + (
                    []
                    if crit_gate.passed
                    else ["必定暴击闸门未通过：" + "；".join(crit_gate.blockers)]
                ),
                missing_data=_missing_data(
                    missing_attack, extra_class_used, stats_store, skill_store, modelling_notes
                ),
                assumptions=assumptions + assumed_ce_policy,
            ),
                charge_ok,
                functional_ce,
            )
        )

    built.sort(key=lambda row: (not row[1], row[2], -row[0].simulation.total_damage_avg))
    options = [row[0] for row in built[: constraints.max_options]]
    for index, option in enumerate(options, start=1):
        option.option_id = f"{request.quest_id}-opt{index}"
        option.title = f"方案 {index}：" + option.title.split("：", 1)[-1]

    if support_count == 0:
        notes.append("约束限制没有辅助位，当前方案只有主输出。")
    elif options and not options[0].required_servants[1:]:
        notes.append("账号中没有能给队友充能或增伤的辅助型从者。")
    support_only = [item["servant"].name for item in pool if not item["has_damage_np"]]
    if support_only:
        preview = "、".join(sorted(support_only)[:8])
        notes.append(
            f"以下 {len(support_only)} 名从者的宝具没有伤害倍率（辅助型），不参与输出位排序："
            + preview
            + ("…" if len(support_only) > 8 else "")
        )
    if ambiguous_matches:
        preview = "；".join(sorted(ambiguous_matches.values())[:3])
        notes.append(
            f"以下 {len(ambiguous_matches)} 名从者在图鉴里同名，已按账号稀有度消歧：{preview}"
        )

    return RecommendationResult(
        quest_id=profile.quest_id,
        quest_name=profile.quest_name,
        profile_mock=profile.mock,
        profile_verified=profile.verified,
        dominant_enemy_class=enemy_class,
        constraints=constraints,
        options=options,
        notes=notes,
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def _build_plan(
    *,
    profile: CombatProfile,
    lineup: list[tuple[dict, str]],
    index: int,
    enemy_class: str,
    mystic_code: MysticCodeProfile | None = None,
    enemy_traits: set[str] | None = None,
    assume_command_codes: list[str] | None = None,
) -> tuple[TeamPlan, list[RecommendedServant], list[str], bool, int, str, str, object, str]:
    """构建 主输出 + 第二输出 + 辅助 的三回合计划，并计算双输出充能闸门。

    第二输出点用于补掉主输出覆盖不到的敌人：单体主输出打不掉的多人面，
    由光炮副手处理；反之亦然。
    """
    combatants: list[CombatantSnapshot] = []
    actions: list[TeamPlanAction] = []
    recommended: list[RecommendedServant] = []
    order = 0
    slot_of: dict[str, int] = {}
    card_of_slot: dict[int, str] = {}
    attackers: list[tuple[dict, str]] = []

    for slot, (item, role) in enumerate(lineup, start=1):
        servant = item["servant"]
        summary: SkillSummary = item["summary"]
        relation, modifier = relation_encoding(item["multiplier"])
        slot_of[servant.name] = slot
        card_of_slot[slot] = item["card"]
        if role in {"main_dps", "secondary_dps"}:
            attackers.append((item, role))
        combatants.append(
            CombatantSnapshot(
                actor_slot=slot,
                servant_record_id=("friend-" if item.get("friend") else "owned-") + servant.name,
                name=servant.name,
                class_name=servant.class_name,
                attack=item["attack"] + ASSUMED_CE_ATTACK,
                hp=NOMINAL_COMBATANT_HP,
                attribute=str((item.get("entry") or {}).get("attribute") or "star"),
                class_attack_modifier=modifier,
                class_relation=relation,  # type: ignore[arg-type]
                np_multiplier=item["np_damage"] or 6.0,
                np_special_multiplier=float(item.get("np_special_multiplier") or 0.0),
                np_target=item["np_target"],  # type: ignore[arg-type]
            )
        )
        recommended.append(
            RecommendedServant(
                name=servant.name,
                class_name=servant.class_name,
                level=servant.level,
                np_level=servant.np_level,
                skills=[servant.skill_1 or 0, servant.skill_2 or 0, servant.skill_3 or 0],
                attack=item["attack"],
                attack_source=item["attack_source"],  # type: ignore[arg-type]
                role=role,  # type: ignore[arg-type]
                damage_multiplier=item["multiplier"],
                np_multiplier=item["np_damage"] or 6.0,
                np_card=item["np_card"],
                np_target_type=item["np_target_type"],
                notes=(
                    [f"职阶倍率 {item['multiplier']:g}（对 {enemy_class}）"]
                    + ([f"宝具倍率 {item['np_damage']:g}｜{item['np_card']}"] if item["np_card"] else [])
                    + [
                        f"宝具范围：{'单体' if item['np_target'] == 'single' else '光炮'}"
                        f"（设定名 {item['np_target_type'] or '未记录'}）"
                    ]
                    + [f"清场覆盖：约 {item['coverage']:.1f} 个敌人/回合"]
                    + (
                        [
                            f"辅助：充能 {summary.ally_charge * 100:.0f}%，"
                            f"对{card_of_slot[slot] or '该'}卡的增伤合计 "
                            f"{(summary.ally_np_buff_sum(card_of_slot[slot]) + summary.defense_down) * 100:.0f}%"
                        ]
                        if role == "support"
                        else []
                    )
                    + (
                        ["无本地基础攻击数据，使用同职阶同稀有度中位数"]
                        if item["attack_source"] == "class_rarity_median"
                        else []
                    )
                ),
            )
        )

    main_item = attackers[0][0]
    main_slot = slot_of[main_item["servant"].name]
    attacker_slots = [slot_of[item["servant"].name] for item, _ in attackers]
    # 全体效果要覆盖全部前排（辅助也可能成为必定暴击的补刀手），
    # 但充能占用与宝具计算仍只针对输出位。
    ally_slots = sorted(slot_of[item["servant"].name] for item, _role in lineup)

    def skill_action(item: dict, skill: dict, turn: int, target_slots: list[int] | None) -> None:
        """写出一次技能施放。

        ``target_slots`` 是本次施放指向的我方目标（``None`` 表示只作用于自己）。
        规则：

        - 一个技能在一回合只产生**一个**动作：游戏里技能有冷却，不能同一回合对两名
          输出各放一次；全体效果在同一个动作里给每名受益输出各记一条效果。
        - 目标域按图鉴逐条生效：``self`` 只写给施放者自己（泳装 BB 的自我改造这类
          自身增益绝不能被算到别人头上），``ally_all`` 写给所有输出，``ally_one``
          写给本次指定的目标。
        - 条件增益（特攻/场地/血量阈值）不进入方案，只作为建模提示。
        """
        nonlocal order
        actor_slot = slot_of[item["servant"].name]
        targets = sorted(set(target_slots)) if target_slots else []
        level = int(skill.get("level") or 10)
        effects = []
        for effect in skill.get("effects") or []:
            kind = str(effect.get("kind"))
            domain_type = EFFECT_TO_DOMAIN.get(kind)
            if domain_type is None:
                continue
            condition = str(effect.get("condition") or "")
            if condition and not condition_is_resolvable(condition):
                continue
            if domain_type == "control":
                # 发牌控制没有数值，但必须在方案里留下顺序，供必定暴击闸门校验冲突。
                effects.append(
                    CombatEffect(
                        effect_id=f"opt{index}-{item['servant'].name}-{skill['slot']}-control-{actor_slot}",
                        effect_type="control",
                        value=0.0,
                        target_actor_slot=actor_slot,
                        duration_turns=int(effect.get("duration") or 1) or 1,
                        source=f"{item['servant'].name} {skill.get('name')}",
                        notes=f"{effect.get('source')}|target={effect.get('target')}",
                    )
                )
                continue
            values = effect.get("values") or []
            value = float(values[level - 1]) if len(values) >= level else float(effect.get("value") or 0.0)
            if not value:
                continue
            if domain_type not in RAW_EFFECT_KINDS:
                value = value / 100.0
            effect_target = str(effect.get("target") or "")
            if effect_target == "self":
                recipients = [actor_slot]
            elif effect_target == "ally_all":
                recipients = ally_slots
            elif effect_target == "ally_one":
                recipients = targets or [actor_slot]
            else:
                continue  # 敌方目标等不在本阶段建模
            # 卡色不匹配的效果不能进入方案（红卡辅助的红卡性能对绿卡宝具无效）
            effect_card = str(effect.get("card") or "")
            for recipient in recipients:
                if effect_card and effect_card != card_of_slot.get(recipient, ""):
                    continue
                effects.append(
                    CombatEffect(
                        effect_id=f"opt{index}-{item['servant'].name}-{skill['slot']}-{kind}-{recipient}",
                        effect_type=domain_type,  # type: ignore[arg-type]
                        value=value,
                        target_actor_slot=recipient,
                        duration_turns=int(effect.get("duration") or 1) or 1,
                        card=str(effect.get("card") or ""),
                        source=f"{item['servant'].name} {skill.get('name')}",
                        condition=condition,
                        condition_label=str(effect.get("condition_label") or ""),
                    )
                )
        if not effects:
            return
        order += 1
        actions.append(
            TeamPlanAction(
                action_id=f"opt{index}-t{turn}-{actor_slot}-skill{skill['slot']}",
                order=order,
                turn=turn,
                actor_slot=actor_slot,
                action_type="skill",
                skill_id=str(skill.get("name") or ""),
                effects=effects,
                notes=[f"{item['servant'].name} 使用 {skill.get('name')}（Lv{skill.get('level')}）"],
            )
        )

    # 第 1 回合：辅助增益指向主输出；输出自身的增益作用于自己
    # 倍卡礼装：装备者（打手）整场 +100% 伤害。写成施放者自己的增益，
    # 这样宝具与后续暴击卡都会吃到，且能在方案里显示出来。
    order += 1
    actions.append(
        TeamPlanAction(
            action_id=f"opt{index}-t1-{main_slot}-event-ce",
            order=order,
            turn=1,
            actor_slot=main_slot,
            action_type="skill",
            skill_id=EVENT_DAMAGE_CE_NAME,
            effects=[
                CombatEffect(
                    effect_id=f"opt{index}-event-ce-damage",
                    effect_type="power_modifier",
                    value=EVENT_DAMAGE_CE_DAMAGE_UP,
                    target_actor_slot=main_slot,
                    duration_turns=3,
                    source=EVENT_DAMAGE_CE_NAME,
                    notes="+100% 攻击威力（满破倍卡）",
                )
            ],
            notes=[
                f"{main_item['servant'].name} 携带{EVENT_DAMAGE_CE_NAME}：伤害 +100%、开局宝具值 +50%"
            ],
        )
    )
    charge_skills: list[tuple[dict, dict]] = []
    support_items = [item for item, role in lineup if role == "support"]
    main_item_ref = next(item for item, role in lineup if role == "main_dps")
    main_shorten = shorten_total(main_item_ref, support_items, mystic_code)
    cooldown_notes: list[str] = []
    for item, role in lineup:
        summary: SkillSummary = item["summary"]
        for skill in summary.buff_skills:
            first_turn = control_cast_turn(skill)
            skill_action(
                item,
                skill,
                turn=first_turn,
                target_slots=[main_slot] if role == "support" else None,
            )
            # 冷却缩减到位时，打手的星/锁技能可以再早放一次（例：第 2、3 回合各一次）。
            if item is main_item_ref and role == "main_dps":
                has_control = any(str(e.get("kind")) == "control" for e in skill.get("effects") or [])
                cooldown = skill_cooldown(skill)
                effective = max(1, cooldown - int(main_shorten))
                if has_control and cooldown and effective <= CRIT_TURN - 1 and first_turn - effective >= 1:
                    skill_action(
                        item,
                        skill,
                        turn=first_turn - effective,
                        target_slots=[main_slot],
                    )
                    cooldown_notes.append(
                        f"{item['servant'].name} 的「{skill.get('name')}」冷却 {cooldown} − 缩减 {int(main_shorten)} "
                        f"= {effective} 回合，因此第 {first_turn - effective} 与 {first_turn} 回合各可用一次"
                    )
        for skill in summary.charge_skills:
            charge_skills.append((item, skill))
        if role == "support" and summary.defense_down:
            order += 1
            actions.append(
                TeamPlanAction(
                    action_id=f"opt{index}-t1-{slot_of[item['servant'].name]}-debuff",
                    order=order,
                    turn=1,
                    actor_slot=slot_of[item["servant"].name],
                    action_type="skill",
                    effects=[
                        CombatEffect(
                            effect_id=f"opt{index}-{item['servant'].name}-defdown",
                            effect_type="defense_down",
                            value=min(MAX_BUFF_SUM, summary.defense_down),
                            target_actor_slot=main_slot,
                            duration_turns=3,
                            source=f"{item['servant'].name} 减防",
                        )
                    ],
                    notes=[f"{item['servant'].name} 对敌方减防 {summary.defense_down * 100:.0f}%"],
                )
            )

    # 充能来源：记录每个技能对各个输出位的充能值
    sources: list[tuple[dict, dict, dict[int, float]]] = []
    for item, skill in charge_skills:
        actor_slot = slot_of[item["servant"].name]
        level = int(skill.get("level") or 10)
        amounts: dict[int, float] = {}
        for effect in skill.get("effects") or []:
            if str(effect.get("kind")) != "charge":
                continue
            target = str(effect.get("target") or "")
            value = _effect_value_at(effect, level)
            if target == "ally_all":
                for slot in attacker_slots:
                    amounts[slot] = amounts.get(slot, 0.0) + value
            elif target == "ally_one":
                amounts[main_slot] = amounts.get(main_slot, 0.0) + value
            elif target == "self" and actor_slot in attacker_slots:
                amounts[actor_slot] = amounts.get(actor_slot, 0.0) + value
        if amounts:
            sources.append((item, skill, amounts))
        else:
            # 充能对输出位无贡献，但技能本身可能有增益
            skill_action(item, skill, turn=1, target_slots=[main_slot])
    sources.sort(key=lambda row: -max(row[2].values()))

    # 双输出充能闸门。
    # 第 1 回合用追加技能2「魔力装填」带来的开局宝具值（免费、不占礼装位）；
    # 第 2/3 回合只能靠技能充能与攻击回收——**开局充能礼装对这两回合无效**，
    # 所以礼装只能补第 1 回合的缺口，且用一张就少一个掉落加成位。
    start_np = {
        slot_of[item["servant"].name]: append_start_np(item["servant"].append_2)
        for item, _ in attackers
    }
    # 倍卡礼装的开局宝具值只作用于装备者（打手），一次战斗只补第 1 回合。
    event_ce_start_np = {slot: (EVENT_DAMAGE_CE_START_NP if slot == main_slot else 0.0) for slot in start_np}
    deficits: dict[tuple[int, int], float] = {}
    for slot in attacker_slots:
        deficits[(slot, 1)] = max(0.0, NP_COST - start_np[slot] - event_ce_start_np.get(slot, 0.0))
        deficits[(slot, 2)] = NP_COST - ASSUMED_NP_GAIN_PER_TURN
        deficits[(slot, 3)] = NP_COST - ASSUMED_NP_GAIN_PER_TURN

    assignments: dict[int, list[tuple[dict, dict, dict[int, float]]]] = {}
    for item, skill, amounts in sources:
        # 选择“剩余缺口最大”的回合；全体充能（ally_all）要同时补给该回合的两名输出，
        # 否则会白白浪费一个受益位（已实测：两名 80% 全体充能只能喂饱一名输出）。
        turn = max((1, 2, 3), key=lambda candidate: sum(deficits[(slot, candidate)] for slot in attacker_slots))
        if sum(deficits[(slot, turn)] for slot in attacker_slots) <= 0:
            break
        applied: dict[int, float] = {}
        for slot in attacker_slots:
            gain = min(amounts.get(slot, 0.0), max(0.0, deficits[(slot, turn)]))
            if gain > 0:
                deficits[(slot, turn)] -= gain
                applied[slot] = gain
        if applied:
            assignments.setdefault(turn, []).append((item, skill, applied))

    # 御主礼装的充能技能是免费资源（换礼装不占掉落位），先用它补缺口。
    mc_charge = mystic_code.charge_for() if mystic_code else 0.0
    mc_note = ""
    mc_turn = 0
    mc_gain = 0.0
    mc_slot = 0
    if mc_charge > 0:
        for turn in (2, 3, 1):
            key = max(
                ((slot, turn) for slot in attacker_slots),
                key=lambda item_key: deficits[item_key],
            )
            gain = min(mc_charge, max(0.0, deficits[key]))
            if gain <= 0:
                continue
            deficits[key] -= gain
            mc_turn, mc_slot, mc_gain = turn, key[0], gain
            mc_note = (
                f"{mystic_code.name}（Lv{mystic_code.level}）"
                f"第 {turn} 回合给输出位充能 +{gain * 100:.0f}%"
            )
            break

    # 剩余的第 1 回合缺口才用开局充能礼装补齐（要记入礼装成本）
    ce_for_slot: dict[int, tuple[float, str]] = {}
    for slot in attacker_slots:
        shortfall = deficits[(slot, 1)]
        if shortfall <= 1e-9:
            continue
        tier = next((row for row in CHARGE_CE_TIERS if row[0] + 1e-9 >= shortfall), None)
        if tier is None:
            tier = (CHARGE_CE_TIERS[-1][0], CHARGE_CE_TIERS[-1][1] + "（仍不足）")
        ce_for_slot[slot] = tier
        deficits[(slot, 1)] = max(0.0, shortfall - tier[0])

    charge_plan: list[str] = []
    charge_ok = True
    # 充能技能同样一回合只施放一次：全体充能在同一个动作里给每名受益输出各记一条，
    # 单体充能只写给本次充的那一名输出。
    for turn in (1, 2, 3):
        for item, skill, amounts in assignments.get(turn, []):
            skill_action(item, skill, turn=turn, target_slots=sorted(amounts))
    for turn in (1, 2, 3):
        parts: list[str] = []
        for slot in attacker_slots:
            name = next(item["servant"].name for item, _ in attackers if slot_of[item["servant"].name] == slot)
            if turn == 1:
                available = start_np[slot]
                base = f"追加技能开局 {start_np[slot] * 100:.0f}%"
            else:
                available = ASSUMED_NP_GAIN_PER_TURN
                base = f"攻击回收 {ASSUMED_NP_GAIN_PER_TURN * 100:.0f}%"
            used: list[str] = []
            if turn == 1 and event_ce_start_np.get(slot):
                available += event_ce_start_np[slot]
                used.append(
                    f"{EVENT_DAMAGE_CE_NAME}(+{event_ce_start_np[slot] * 100:.0f}%)"
                )
            for item, skill, amounts in assignments.get(turn, []):
                gain = amounts.get(slot, 0.0)
                if gain <= 0:
                    continue
                available += gain
                used.append(f"{item['servant'].name} {skill.get('name')}(+{gain * 100:.0f}%)")
            if turn == 1 and slot in ce_for_slot:
                value, label = ce_for_slot[slot]
                available += value
                used.append(f"{label}(+{value * 100:.0f}%)")
            if turn == mc_turn and slot == mc_slot and mc_gain > 0 and mystic_code is not None:
                available += mc_gain
                used.append(f"{mystic_code.name}(+{mc_gain * 100:.0f}%)")
            covered = available + 1e-9 >= NP_COST
            if not covered:
                charge_ok = False
            detail = "".join(f" + {entry}" for entry in used)
            tail = "" if covered else f"（缺口 {(NP_COST - available) * 100:.0f}%）"
            parts.append(f"{name}：{base}{detail} = {available * 100:.0f}%{tail}")
        charge_plan.append(f"第 {turn} 回合：" + "；".join(parts))

    # 打手固定携带满破倍卡礼装（占用 1 个位置），叠加上额外的开局充能礼装。
    functional_ce_count = len(ce_for_slot) + 1
    if mystic_code is not None:
        card_buff = mystic_code.buff_sum(card_of_slot.get(main_slot, ""))
        mc_note = mc_note or f"{mystic_code.name}（Lv{mystic_code.level}）未提供充能"
        if card_buff > 0:
            mc_note += f"；对主输出卡色增伤 +{card_buff * 100:.0f}%"
        charge_plan.append(f"御主礼装：{mc_note}")
    if functional_ce_count:
        # 礼装名尽量用真实存在的礼装（来自概念礼装库），库里没有才退回抽象描述。
        ce_store = get_craft_essence_store() if get_craft_essence_store().available() else None
        charge_labels = {
            (ce_store.label_for_charge(value) if ce_store is not None else label)
            for value, label in ce_for_slot.values()
        }
        labels = [EVENT_DAMAGE_CE_NAME] + sorted(charge_labels)
        charge_plan.append(
            f"礼装占用：{functional_ce_count} 张（{'、'.join(labels)}），"
            f"剩余可挂掉落加成礼装 {max(0, DROP_CE_SLOTS_TOTAL - functional_ce_count)} 张"
        )
    else:
        charge_plan.append(
            f"礼装占用：0 张（无需指定礼装），{DROP_CE_SLOTS_TOTAL} 个位置都可挂掉落加成礼装"
        )

    # 每回合两名输出各放一次宝具；光炮先打，单体再补最高血量目标
    for note in cooldown_notes:
        charge_plan.append(f"冷却缩减：{note}")
    for turn in (1, 2, 3):
        for item, _ in sorted(attackers, key=lambda row: 0 if row[0]["np_target"] == "area" else 1):
            order += 1
            np_effects: list[CombatEffect] = []
            # 御主礼装的卡性能提升只持续 1 回合，按惯例用在处理尾王的第 3 回合
            if turn == 3 and mystic_code is not None and item["servant"].name == main_item["servant"].name:
                buff = mystic_code.buff_sum(item["card"])
                if buff > 0:
                    np_effects.append(
                        CombatEffect(
                            effect_id=f"opt{index}-mc-buff",
                            effect_type="card_up",
                            value=min(MAX_BUFF_SUM, buff),
                            target_actor_slot=slot_of[item["servant"].name],
                            duration_turns=1,
                            source=f"御主礼装 {mystic_code.name}",
                        )
                    )
            actions.append(
                TeamPlanAction(
                    action_id=f"opt{index}-t{turn}-np-{slot_of[item['servant'].name]}",
                    order=order,
                    turn=turn,
                    actor_slot=slot_of[item["servant"].name],
                    action_type="np",
                    effects=np_effects,
                    notes=[
                        f"{item['servant'].name} 的"
                        f"{'光炮' if item['np_target'] == 'area' else '单体'}宝具对 {enemy_class}"
                    ],
                )
            )

    # 必定暴击：只有闸门通过才允许把暴击当成方案的一部分（概率方案不可接受）。
    # 补刀目标就是主输出：宝具打完剩下的血量由他的一张指令卡收尾。
    name_of_slot = {slot_of[item["servant"].name]: item["servant"].name for item, _role in lineup}
    cards_of_slot = {
        slot_of[item["servant"].name]: list(item.get("cards") or []) for item, _role in lineup
    }
    # 补刀手候选：主输出优先；辅助若能自己保证暴击也可以补刀
    # （例：奥尔加玛丽的「空前绝后 EX」让其他人无法选择指令卡，她自己才是必定暴击的那一个）。
    finisher_order: list[int] = [main_slot]
    finisher_order += [slot for slot in attacker_slots if slot != main_slot]
    finisher_order += [
        slot_of[item["servant"].name] for item, role in lineup if role == "support"
    ]
    # 第 3 回合的卡位：宝具各占 1 个，剩余位置可以出暴击卡（单输出结构就有 2 个空位）。
    turn3_np_count = sum(1 for action in actions if action.turn == CRIT_TURN and action.action_type == "np")
    free_card_slots = max(0, CARDS_PER_TURN - turn3_np_count)
    planned_crit_cards = min(free_card_slots, MAX_CRIT_CARDS)
    crit_gate = None
    crit_slot = main_slot
    crit_card_type = "buster"
    for slot in finisher_order:
        for candidate_card in candidate_crit_cards(cards_of_slot.get(slot, []), card_of_slot.get(slot, "")):
            code_summary = command_codes.assumed_command_code_effects(
                _command_code_library(),
                list(assume_command_codes or []),
                candidate_card,
            )
            gate = evaluate_crit(
                actions=actions,
                crit_slot=slot,
                names=name_of_slot,
                crit_turn=3,
                mystic_code=mystic_code,
                crit_card=candidate_card,
                planned_crit_cards=max(1, planned_crit_cards),
                command_code_stars=[
                    (item["name"], float(item["value"]))
                    for item in code_summary.get("stars") or []
                ],
                command_code_focus=float((code_summary.get("focus") or {}).get("value") or 0.0)
                / 100.0,
                command_code_focus_source=str((code_summary.get("focus") or {}).get("name") or ""),
                command_code_critical_up=float(
                    (code_summary.get("critical") or {}).get("value") or 0.0
                )
                / 100.0,
                command_code_critical_source=str(
                    (code_summary.get("critical") or {}).get("name") or ""
                ),
            )
            if crit_gate is None or (gate.passed and not crit_gate.passed):
                crit_gate, crit_slot, crit_card_type = gate, slot, candidate_card
            if gate.passed:
                break
        if crit_gate is not None and crit_gate.passed:
            break
    assert crit_gate is not None
    code_stars: list[dict[str, Any]] = []
    if crit_gate.passed:
        # 补刀卡依次排在宝具之后：位置越靠后倍率越高（红卡 1.5/1.8/2.1）。
        crit_gate.crit_card_position = min(CARDS_PER_TURN, turn3_np_count + 1)
        code_assignment = COMMAND_CODE_CHARGE.get(name_of_slot.get(crit_slot, ""))
        # 用户可指定"我实际刻印了哪些纹章"（`assume_command_codes`）：把能建模的暴击威力类
        # 纹章挂到暴击卡上。卡色限制（"仅当被刻印在迅指令卡上时"）不满足就不挂，并在备注里
        # 说明原因——不静默加权，也不因为没指定就假装有加成。
        picked_code = command_codes.best_critical_code(
            _command_code_library(), list(assume_command_codes or []), crit_card_type or ""
        )
        final_code_summary = command_codes.assumed_command_code_effects(
            _command_code_library(), list(assume_command_codes or []), crit_card_type or ""
        )
        code_critical_up = float((picked_code or {}).get("critical_up") or 0.0)
        code_focus = float((final_code_summary.get("focus") or {}).get("value") or 0.0) / 100.0
        code_focus_source = str((final_code_summary.get("focus") or {}).get("name") or "")
        code_stars = list(final_code_summary.get("stars") or [])
        code_note = ""
        if assume_command_codes and crit_card_type:
            if picked_code:
                code_note = (
                    f"暴击卡带「{picked_code['name']}」纹章：暴击威力 +{code_critical_up:g}%"
                )
            else:
                code_note = (
                    f"指定的纹章（{'、'.join(assume_command_codes)}）不适合"
                    f"{FACE_CARD_LABELS.get(crit_card_type, crit_card_type)}卡，未计入"
                )
            if code_focus > 0:
                code_note += (
                    f"；「{code_focus_source}」提供暴击星集中度 +{code_focus * 100:.0f}%"
                )
            if code_stars:
                code_note += "；前序卡出星：" + "、".join(
                    f"「{item['name']}」+{float(item['value']):.0f}" for item in code_stars
                )
        for card_index in range(crit_gate.planned_crit_cards):
            order += 1
            position = min(CARDS_PER_TURN, turn3_np_count + 1 + card_index)
            crit_effects: list[CombatEffect] = []
            if code_assignment and crit_card_type == code_assignment["card"]:
                crit_effects.append(
                    CombatEffect(
                        effect_id=f"opt{index}-flower-magus-{card_index + 1}",
                        effect_type="charge",
                        value=float(code_assignment["charge"]),
                        target_actor_slot=crit_slot,
                        duration_turns=0,
                        source=f"指令纹章 {code_assignment['code']}",
                    )
                )
            if picked_code and code_critical_up:
                crit_effects.append(
                    CombatEffect(
                        effect_id=f"opt{index}-code-crit-{card_index + 1}",
                        effect_type="critical_up",
                        value=code_critical_up / 100.0,
                        target_actor_slot=crit_slot,
                        duration_turns=0,
                        source=f"指令纹章 {picked_code['name']}",
                    )
                )
            if code_focus > 0:
                crit_effects.append(
                    CombatEffect(
                        effect_id=f"opt{index}-code-focus-{card_index + 1}",
                        effect_type="star_weight_up",
                        value=code_focus,
                        target_actor_slot=crit_slot,
                        duration_turns=0,
                        source=f"指令纹章 {code_focus_source}",
                    )
                )
            crit_notes = [
                f"{name_of_slot.get(crit_slot, '')} 用 {FACE_CARD_LABELS.get(crit_card_type, crit_card_type)} "
                f"指令卡暴击补刀（第 {position} 位，必定暴击闸门通过）"
            ]
            if code_note:
                crit_notes.append(code_note)
            actions.append(
                TeamPlanAction(
                    action_id=f"opt{index}-t3-attack-{crit_slot}-{card_index + 1}",
                    order=order,
                    turn=3,
                    actor_slot=crit_slot,
                    action_type="attack",
                    card_type=crit_card_type,  # type: ignore[arg-type]
                    card_position=position,
                    is_critical=True,
                    effects=crit_effects,
                    notes=crit_notes,
                )
            )

    # 第 5 步：把每个回合的卡位补满（攻略结构是「宝具 + 2 张指令卡」）。
    # 规则（用户 2026-10-10 确认）：每回合 3 个卡位、宝具占 1 位。
    # 之前只排了第 3 回合的暴击补刀，前两回合的空位被浪费，估算里也就少了这部分真实伤害。
    # 保守口径：补位卡按**普通指令卡**计（不吃暴击加成、不算首卡/链加成），
    # 「花之魔术师」的 +10% 充能仍由暴击卡那一次承担，避免同一纹章被重复计入。
    filler_candidates = candidate_crit_cards(
        cards_of_slot.get(main_slot, []), card_of_slot.get(main_slot, "")
    ) or ["buster"]
    main_name = name_of_slot.get(main_slot, "")
    for fill_turn in range(1, CRIT_TURN + 1):
        used_slots = sum(
            1
            for action in actions
            if action.turn == fill_turn and action.action_type in {"np", "attack"}
        )
        for offset in range(max(0, CARDS_PER_TURN - used_slots)):
            position = min(CARDS_PER_TURN, used_slots + offset + 1)
            card_type = filler_candidates[offset % len(filler_candidates)]
            order += 1
            actions.append(
                TeamPlanAction(
                    action_id=f"opt{index}-t{fill_turn}-fill-{main_slot}-{offset + 1}",
                    order=order,
                    turn=fill_turn,
                    actor_slot=main_slot,
                    action_type="attack",
                    card_type=card_type,  # type: ignore[arg-type]
                    card_position=position,
                    is_critical=False,
                    notes=[
                        f"{main_name} 的 {FACE_CARD_LABELS.get(card_type, card_type)} 指令卡补位"
                        f"（第 {position} 位，按普通指令卡计，不按暴击计算）"
                    ],
                )
            )

    if code_stars:
        star_target = next(
            (
                action
                for action in actions
                if action.action_type == "attack" and not action.is_critical
            ),
            None,
        )
        if star_target is not None:
            for code_star in code_stars:
                star_target.effects.append(
                    CombatEffect(
                        effect_id=f"opt{index}-code-stars-{code_star['name']}",
                        effect_type="stars",
                        value=float(code_star["value"]),
                        target_actor_slot=crit_slot,
                        duration_turns=0,
                        source=f"指令纹章 {code_star['name']}",
                    )
                )

    plan = TeamPlan(
        plan_id=f"{profile.quest_id}-rec-opt{index}",
        quest_id=profile.quest_id,
        title=f"{profile.quest_name} 3T 推荐方案 {index}",
        combatants=combatants,
        actions=actions,
        assumptions=[
            "队伍结构为主输出 + 第二输出 + 辅助；辅助技能作用于主输出。",
            "技能按第一/第二再临形态取值（同一槽位的其他再临形态不参与计算）。",
            "两名输出各按一张开局充能礼装假定第 1 回合可用宝具。",
            f"每回合宝具按 {int(NP_COST * 100)}% 充能计算；攻击回收按 {int(ASSUMED_NP_GAIN_PER_TURN * 100)}% 保守估计。",
            "推荐阶段可以忽略好友助战，正式执行前必须选定并校验一名助战。",
            "暴击只按「必定暴击闸门」处理：确定出星 ≥50、集中到主输出、指令卡抽取确定，"
            "且洗牌不得发生在手牌固定之后；攻击产生的暴击星是随机的，不计入保证。",
            "每回合可出 3 张卡，宝具卡与指令卡各占 1 个卡位，所以第 3 回合两发宝具后仍留 1 个卡位补刀；"
            "宝具不会暴击、也不消耗暴击星。",
            "暴击补刀按第 3 回合 1 张指令卡、该卡色第 1 张位置的倍率（保守）计算；"
            "单张指令卡最多 10 颗星 = 100% 暴击率，50 颗星 = 全部 5 张卡满暴。",
        ],
        warnings=["简化模拟器不建模攻击回收宝具值与敌方行动；暴击仅在必定暴击闸门通过时计入。"],
        source_ids=list(profile.source_ids),
        confidence=0.6,
    )
    mc_name = f"{mystic_code.name} Lv{mystic_code.level}" if mystic_code is not None else ""
    return (
        plan,
        recommended,
        charge_plan,
        charge_ok,
        functional_ce_count,
        mc_name,
        mc_note,
        crit_gate,
        crit_card_type,
    )


def _effect_value_at(effect: dict, level: int) -> float:
    values = effect.get("values") or []
    if len(values) >= level:
        return float(values[level - 1])
    return float(effect.get("value") or 0.0)


def _confidence(
    *,
    profile: CombatProfile,
    simulation_status: str,
    charge_ok: bool,
    fallback_count: int,
    missing_attack: bool,
) -> float:
    score = 0.3
    if not profile.mock:
        score += 0.2
    if charge_ok:
        score += 0.15
    if simulation_status == "success":
        score += 0.15
    if fallback_count == 0:
        score += 0.1
    if not missing_attack:
        score += 0.1
    return round(min(1.0, score), 2)


def _minimum_investment(servants: list[RecommendedServant]) -> list[str]:
    items: list[str] = []
    for servant in servants:
        if servant.role == "support":
            items.append(
                f"{servant.name}（辅助）：当前技能 {'/'.join(str(v) for v in servant.skills)}，"
                "充能与增伤数值随技能等级提升，建议按方案所需等级补满"
            )
            continue
        note = f"{servant.name}（主输出）：当前 Lv{servant.level or '?'}"
        if (servant.level or 0) < 90:
            note += "，建议至少 Lv90"
        items.append(note)
        if (servant.np_level or 0) < 1:
            items.append(f"{servant.name}：需要至少宝具 1")
        weak = [index + 1 for index, value in enumerate(servant.skills) if value < 10]
        if weak:
            items.append(f"{servant.name}：技能 {'/'.join(str(item) for item in weak)} 未满级")
    return items or ["当前练度已满足方案记录的最低要求。"]


def _failure_conditions(simulation, profile: CombatProfile, charge_plan: list[str], charge_ok: bool) -> list[str]:
    conditions = [
        "战斗档案与游戏内不一致时方案失效（实时校验档已标记 verified）。",
        "礼装可用性未人工确认前不得进入执行。",
        "攻击回收宝具值与敌方行动未建模，实际结果可能偏离估算。",
    ]
    if not charge_ok:
        shortfalls = [line for line in charge_plan if "缺口" in line]
        conditions.append("充能闸门未通过：" + "；".join(shortfalls))
    if simulation.status != "success":
        last = simulation.turns[-1] if simulation.turns else None
        if last is not None:
            conditions.append(
                f"当前估算在第 {last.turn} 回合仍剩 {last.enemies_remaining} 个敌人、"
                f"约 {int(last.total_enemy_hp_remaining)} 点血量。"
            )
    for warning in simulation.warnings:
        conditions.append(warning)
    return conditions


def _missing_data(
    missing_attack: list[str],
    extra_class_used: set[str],
    stats_store: ServantStatsStore,
    skill_store: SkillTableStore,
    modelling_notes: list[str] | None = None,
) -> list[str]:
    items = [
        "攻击回收宝具值与敌方行动未建模；暴击只在「必定暴击闸门」通过时才计入，"
        "攻击产生的暴击星是随机的、不计入保证，暴击补刀按 1 张卡的保守倍率估算。",
        "减伤/无敌/毅力等防御类效果只统计数量，不参与计算。",
        "礼装效果未结构化，按假设的攻击力与开局充能礼装计算。",
    ]
    if modelling_notes:
        preview = "；".join(modelling_notes[:4])
        tail = f"（共 {len(modelling_notes)} 项）" if len(modelling_notes) > 4 else ""
        items.append(f"以下增益有条件或层数不确定，未计入伤害估算：{preview}{tail}")
    if not stats_store.available():
        items.append("本地从者基础数据表缺失，攻击力使用中位数回退。")
    if not skill_store.available():
        items.append("本地技能表缺失，辅助增益与充能按 0 计算。")
    if missing_attack:
        preview = "、".join(sorted(set(missing_attack))[:6])
        items.append(f"以下从者没有匹配到基础数据，已用中位数回退：{preview}")
    if extra_class_used:
        items.append("额外职阶克制未建模，按 neutral 处理：" + "、".join(sorted(extra_class_used)))
    return items
