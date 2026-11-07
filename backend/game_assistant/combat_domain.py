"""Typed contracts for 3T combat profiles, TeamPlans, and simulation."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ClassRelation = Literal["advantage", "disadvantage", "neutral"]
CardType = Literal["buster", "arts", "quick", "extra"]
ActionType = Literal["skill", "attack", "np", "mystic_code", "switch", "wait"]
EffectType = Literal[
    "attack_up",
    "card_up",
    "np_damage_up",
    "power_modifier",
    "defense_down",
    "special_attack",
    "charge",
    "np_gain_up",
    "critical_up",
    "crit_rate_up",
    "star_weight_up",
    "stars",
    "stars_per_turn",
    "control",
    "flat_damage",
]


class CombatEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effect_id: str
    effect_type: EffectType
    value: float = 0.0
    target_actor_slot: int | None = None
    target_enemy_id: str | None = None
    duration_turns: int | None = Field(default=None, ge=0)
    # 卡色限制：arts / buster / quick / extra / np；空表示对所有卡生效。
    card: str = ""
    source: str = ""
    notes: str = ""
    condition: str = ""
    condition_label: str = ""


class EnemyUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enemy_id: str
    name: str
    class_name: str
    level: int = Field(default=1, ge=1)
    hp: int = Field(gt=0)
    count: int = Field(default=1, ge=1)
    attribute: str = "man"
    traits: list[str] = Field(default_factory=list)
    class_relation: ClassRelation = "neutral"
    break_bars: int = Field(default=0, ge=0, le=3)
    effects: list[CombatEffect] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EnemyWave(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wave_id: str
    wave_index: int = Field(ge=1)
    units: list[EnemyUnit]
    effects: list[CombatEffect] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_units(self) -> "EnemyWave":
        if not self.units:
            raise ValueError("enemy wave must contain at least one unit")
        return self


class CombatProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quest_id: str
    event_id: str = ""
    quest_name: str
    ap_cost: int = Field(default=0, ge=0)
    waves: list[EnemyWave]
    verified: bool = False
    mock: bool = False
    source_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_contiguous_waves(self) -> "CombatProfile":
        """面数必须从 1 开始连续编号，但**不限定必须是 3 面**。

        柱子战／冠位战是「单面 1T」形态，之前的"恰好 3 面"校验会把它们直接拒掉；
        3T 关卡仍然是 1/2/3 面，行为不变。
        """
        indexes = [wave.wave_index for wave in self.waves]
        if not indexes or indexes != list(range(1, len(indexes) + 1)):
            raise ValueError("combat profile waves must be numbered contiguously from 1")
        return self

    @property
    def total_enemy_hp(self) -> int:
        return sum(unit.hp * unit.count for wave in self.waves for unit in wave.units)


class CombatantSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_slot: int = Field(ge=1, le=6)
    servant_record_id: str
    name: str
    class_name: str
    attack: float = Field(gt=0)
    hp: float = Field(gt=0)
    attribute: str = "star"
    class_attack_modifier: float = 1.0
    class_relation: ClassRelation = "neutral"
    card_modifiers: dict[CardType, float] = Field(
        default_factory=lambda: {"buster": 1.5, "arts": 1.0, "quick": 0.8, "extra": 1.0}
    )
    np_multiplier: float = Field(default=6.0, gt=0)
    # 宝具的“个体数”第二成分（每个场上敌人叠加的倍率；用户确认口径=场上敌人数）
    np_special_multiplier: float = Field(default=0.0, ge=0.0)
    np_target: Literal["single", "area"] = "area"
    current_np: float = Field(default=0.0, ge=0.0, le=300.0)
    np_capacity: float = Field(default=100.0, gt=0.0, le=300.0)
    effects: list[CombatEffect] = Field(default_factory=list)


class TeamPlanAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str
    order: int = Field(ge=1)
    turn: int = Field(ge=1, le=3)
    actor_slot: int = Field(ge=1, le=6)
    action_type: ActionType
    skill_id: str = ""
    target_enemy_ids: list[str] = Field(default_factory=list)
    card_type: CardType | None = None
    # 指令卡在本回合 3 个卡位中的位置（1/2/3）：位置不同倍率不同
    # （红卡 1.5/1.8/2.1，蓝卡 1.0/1.2/1.4，绿卡 0.8/0.96/1.12）。
    card_position: int = Field(default=1, ge=1, le=3)
    damage_multiplier: float | None = Field(default=None, gt=0)
    # 该指令卡是否为“必定暴击”下的暴击卡：只有暴击才吃暴击威力（critical_up）。
    is_critical: bool = False
    np_change: float = 0.0
    switch_out_slot: int | None = Field(default=None, ge=1, le=6)
    switch_in_slot: int | None = Field(default=None, ge=1, le=6)
    effects: list[CombatEffect] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class TeamPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    quest_id: str
    title: str
    combatants: list[CombatantSnapshot]
    actions: list[TeamPlanAction]
    # 空列表 = 旧方案兼容口径：所有 combatant 都视为已在前场。
    initial_front_slots: list[int] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_team_and_actions(self) -> "TeamPlan":
        if not self.combatants:
            raise ValueError("TeamPlan must contain at least one combatant")
        if not self.actions:
            raise ValueError("TeamPlan must contain at least one action")
        return self


class DamageGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enemy_id: str
    required_damage: float = Field(gt=0)
    expected_min_damage: float = Field(ge=0)
    expected_avg_damage: float = Field(ge=0)
    passed: bool


class NpGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_slot: int
    turn: int
    required_np: float = Field(ge=0)
    actual_np: float = Field(ge=0)
    passed: bool


class ActionSimulation(BaseModel):
    action_id: str
    order: int
    turn: int
    actor_slot: int
    action_type: ActionType
    target_enemy_ids: list[str]
    damage_min: float = 0.0
    damage_avg: float = 0.0
    damage_max: float = 0.0
    np_after: float = 0.0
    notes: list[str] = Field(default_factory=list)


class TurnSimulation(BaseModel):
    turn: int
    actions: list[ActionSimulation]
    enemies_remaining: int
    total_enemy_hp_remaining: float


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: CombatProfile
    plan: TeamPlan
    damage_variance_min: float = Field(default=0.9, gt=0)
    damage_variance_max: float = Field(default=1.1, gt=0)
    require_three_turn_clear: bool = True

    @model_validator(mode="after")
    def validate_variance(self) -> "SimulationRequest":
        if self.damage_variance_min > self.damage_variance_max:
            raise ValueError("damage variance minimum cannot exceed maximum")
        if self.profile.quest_id != self.plan.quest_id:
            raise ValueError("profile and TeamPlan quest_id must match")
        return self


class SimulationResult(BaseModel):
    status: Literal["success", "failed", "invalid"]
    cleared_by_turn: int | None = None
    total_turns: int
    total_damage_min: float
    total_damage_avg: float
    total_damage_max: float
    turns: list[TurnSimulation]
    damage_gates: list[DamageGate] = Field(default_factory=list)
    np_gates: list[NpGate] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PreflightCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    label: str
    status: Literal["ok", "warning", "blocked"]
    detail: str
    required_for_dry_run: bool = True
    required_for_execution: bool = True


class ExecutionPreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quest_id: str
    plan_id: str
    damage_variance_min: float = Field(default=0.9, gt=0)
    damage_variance_max: float = Field(default=1.1, gt=0)


class ExecutionPreflightResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ready_for_dry_run", "blocked", "ready_for_execution"]
    quest_id: str
    plan_id: str
    simulation_status: Literal["success", "failed", "invalid"]
    clears_by_turn: int | None = None
    checks: list[PreflightCheck]
    can_dry_run: bool
    can_execute: bool
    summary: str


class RecommendationConstraints(BaseModel):
    """用户可调的推荐约束。默认值来自 2026-10-08 的确认：非助战从者尽量 ≤4，留 2-3 个羁绊位。"""

    model_config = ConfigDict(extra="forbid")

    max_required_servants: int = Field(default=4, ge=1, le=6)
    target_bond_slots: int = Field(default=2, ge=0, le=5)
    include_friend_support: bool = False
    exclude_servants: list[str] = Field(default_factory=list)
    max_options: int = Field(default=3, ge=1, le=5)
    # 用户实际刻印的指令纹章（如 ["纹章：爆裂", "龙爪如湖光"]）。默认空 = 不假设任何纹章，
    # 避免静默把暴击卡的伤害抬高；指定后只应用卡色限制满足、且能建模的那部分效果。
    assume_command_codes: list[str] = Field(default_factory=list)


class RecommendedServant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    class_name: str
    level: int | None = None
    np_level: int | None = None
    skills: list[int] = Field(default_factory=list)
    attack: float = Field(gt=0)
    attack_source: Literal["atlas", "class_rarity_median"] = "atlas"
    role: Literal["main_dps", "secondary_dps", "support", "bond"] = "main_dps"
    damage_multiplier: float = 1.0
    np_multiplier: float = Field(default=6.0, gt=0)
    np_card: str = ""
    np_target_type: str = ""
    notes: list[str] = Field(default_factory=list)


class RecommendationOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str
    title: str
    confidence: float = Field(ge=0.0, le=1.0)
    required_servants: list[RecommendedServant]
    bond_slots: int = Field(ge=0, le=6)
    charge_gate_passed: bool = False
    charge_plan: list[str] = Field(default_factory=list)
    crit_gate_passed: bool = False
    crit_plan: list[str] = Field(default_factory=list)
    functional_ce_count: int = Field(default=0, ge=0, le=6)
    drop_ce_slots: int = Field(default=6, ge=0, le=6)
    mystic_code: str = ""
    mystic_code_effect: str = ""
    assumed_craft_essences: list[str] = Field(default_factory=list)
    required_craft_essences: list[str] = Field(default_factory=list)
    plan: TeamPlan
    simulation: SimulationResult
    minimum_investment: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    failure_conditions: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quest_id: str
    constraints: RecommendationConstraints = Field(default_factory=RecommendationConstraints)


class RecommendationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quest_id: str
    quest_name: str
    profile_mock: bool
    profile_verified: bool
    dominant_enemy_class: str = ""
    constraints: RecommendationConstraints
    options: list[RecommendationOption] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    generated_at: str = ""


class CraftEssenceConfirmation(BaseModel):
    """按方案记录的概念礼装可用性确认。

    推荐阶段可以假定必需礼装可用；正式 Dry Run 或执行之前，必须由用户逐项确认，
    未确认的方案在执行预检中保持 blocked。
    """

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    quest_id: str = ""
    required_essences: list[str] = Field(default_factory=list)
    available_essences: list[str] = Field(default_factory=list)
    confirmed: bool = False
    confirmed_by: str = ""
    notes: str = ""
    updated_at: str = ""

    @property
    def missing_essences(self) -> list[str]:
        available = {item.strip() for item in self.available_essences}
        return [item for item in self.required_essences if item not in available]

    @property
    def is_satisfied(self) -> bool:
        return bool(self.confirmed) and not self.missing_essences
