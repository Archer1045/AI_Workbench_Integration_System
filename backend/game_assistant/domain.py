"""Typed contracts for the FGO public knowledge and guide-generation domain."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SourceType = Literal["official", "wiki", "guide", "ui_observation", "user_note"]
VerificationStatus = Literal["candidate", "verified", "conflict", "expired"]
PhaseType = Literal["main", "new_guda", "free", "extra", "challenge", "campaign"]
QuestType = Literal["main", "free", "new_guda", "event", "challenge"]
ProviderName = Literal["template", "local", "deepseek", "openai_compatible"]


class SourceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    url: str
    source_type: SourceType
    publisher: str = ""
    fetched_at: datetime
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    verification_status: VerificationStatus = "verified"

    @field_validator("fetched_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("fetched_at must include a timezone")
        return value


class MechanicNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    detail: str
    kind: Literal["fact", "advice"] = "fact"
    source_ids: list[str] = Field(default_factory=list)


class EventBonusServant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    class_name: str
    rarity: int = Field(ge=0, le=5)
    attack_bonus_percent: int = 0
    bond_bonus_percent: int = 0
    source_ids: list[str] = Field(default_factory=list)

class EventPhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase_id: str
    name: str
    phase_type: PhaseType
    opens_at: datetime | None = None
    unlock_condition: str = ""
    summary: str = ""
    quest_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)

    @field_validator("opens_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("opens_at must include a timezone")
        return value


class Quest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quest_id: str
    name: str
    quest_type: QuestType
    location: str = ""
    ap_cost: int = Field(ge=0)
    recommended_level: str = ""
    unlock_condition: str = ""
    available_from: datetime | None = None
    repeatable: bool = True
    first_clear_reward: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    enemy_waves: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)

    @field_validator("available_from")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("available_from must include a timezone")
        return value


class Mission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    mission_no: int | None = None
    name: str
    condition: str
    unlock_condition: str = ""
    opens_at: datetime | None = None
    reward_summary: str = ""
    gates_phase_id: str | None = None
    source_ids: list[str] = Field(default_factory=list)


class ShopItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    name: str
    currency: str
    cost: int | None = None
    stock: int | None = None
    priority: Literal["high", "medium", "low", "infinite"] = "medium"
    notes: str = ""
    source_ids: list[str] = Field(default_factory=list)


class UiObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str
    label: str
    detail: str
    observed_at: datetime
    source_ids: list[str] = Field(default_factory=list)
    account_specific: bool = False


class EventBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    revision: int = Field(ge=1)
    server: str
    title: str
    subtitle: str = ""
    starts_at: datetime
    ends_at: datetime
    exchange_ends_at: datetime | None = None
    participation_requirement: str = ""
    location: str = ""
    tags: list[str] = Field(default_factory=list)
    mechanics: list[MechanicNote] = Field(default_factory=list)
    bonus_servants: list[EventBonusServant] = Field(default_factory=list)
    phases: list[EventPhase] = Field(default_factory=list)
    quests: list[Quest] = Field(default_factory=list)
    missions: list[Mission] = Field(default_factory=list)
    shop_items: list[ShopItem] = Field(default_factory=list)
    sources: list[SourceCitation] = Field(default_factory=list)
    observations: list[UiObservation] = Field(default_factory=list)

    @field_validator("starts_at", "ends_at", "exchange_ends_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("event timestamps must include a timezone")
        return value

    def source_id_set(self) -> set[str]:
        return {source.source_id for source in self.sources}

    def quest_by_id(self, quest_id: str) -> Quest | None:
        return next((quest for quest in self.quests if quest.quest_id == quest_id), None)


class GuideSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    heading: str
    summary: str = ""
    bullets: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)


class GuideDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    summary: str
    current_phase: str = ""
    sections: list[GuideSection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    phase_id: str | None = None
    title: str
    action: str
    availability: Literal["current", "upcoming", "conditional", "final"]
    condition: str = ""
    expected_cost: str = ""
    stop_condition: str = ""
    citation_ids: list[str] = Field(default_factory=list)


class PlanCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    objective: str
    current_phase: str
    steps: list[PlanStep]
    stop_conditions: list[str]
    warnings: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)


class GuideGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: ProviderName = "template"
    event_id: str | None = None
    revision: int | None = None
    goal: str = "生成本期活动的当前阶段攻略和候选执行计划"
    temperature: float = Field(default=0.2, ge=0.0, le=1.5)


class ProviderStatus(BaseModel):
    provider: ProviderName
    available: bool
    model: str = ""
    detail: str = ""


class GuideGenerationResult(BaseModel):
    generation_id: str
    event_id: str
    event_revision: int
    provider_requested: ProviderName
    provider_used: ProviderName
    model: str = ""
    prompt_version: str
    fallback_reason: str | None = None
    guide: GuideDraft
    markdown: str
    plan: PlanCandidate
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime