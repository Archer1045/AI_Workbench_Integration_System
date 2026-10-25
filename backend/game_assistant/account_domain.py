"""Private account snapshot contracts for manual and imported data."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ConfidenceState = Literal["confirmed", "candidate", "unknown"]


class ServantRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    class_name: str = Field(default="", max_length=40)
    rarity: int | None = Field(default=None, ge=0, le=5)
    level: int | None = Field(default=None, ge=0, le=999)
    max_level: int | None = Field(default=None, ge=0, le=999)
    np_level: int | None = Field(default=None, ge=1, le=5)
    skill_1: int | None = Field(default=None, ge=1, le=10)
    skill_2: int | None = Field(default=None, ge=1, le=10)
    skill_3: int | None = Field(default=None, ge=1, le=10)
    append_2: int | None = Field(default=None, ge=1, le=10)
    source: str = Field(default="manual", max_length=40)
    confidence: ConfidenceState = "confirmed"
    notes: str = Field(default="", max_length=500)


class ServantRecord(ServantRecordInput):
    record_id: str
    updated_at: str


class MaterialRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="", max_length=60)
    quantity: int = Field(default=0, ge=0, le=99_999_999)
    reserve_quantity: int = Field(default=0, ge=0, le=99_999_999)
    source: str = Field(default="manual", max_length=40)
    confidence: ConfidenceState = "confirmed"
    notes: str = Field(default="", max_length=500)


class MaterialRecord(MaterialRecordInput):
    record_id: str
    updated_at: str


class AccountSnapshotSummary(BaseModel):
    servants: int
    materials: int
    confirmed_servants: int
    candidate_servants: int

class CraftEssenceRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    rarity: int = Field(default=0, ge=0, le=5)
    level: int = Field(default=1, ge=1, le=100)
    max_level: int = Field(default=1, ge=1, le=100)
    limit_break: int = Field(default=0, ge=0, le=4)
    attack: int = Field(default=0, ge=0, le=99999)
    hp: int = Field(default=0, ge=0, le=99999)
    cost: int = Field(default=0, ge=0, le=99)
    effects: list[dict] = Field(default_factory=list)
    source: str = Field(default="manual", max_length=40)
    confidence: ConfidenceState = "confirmed"
    notes: str = Field(default="", max_length=500)


class CraftEssenceRecord(CraftEssenceRecordInput):
    record_id: str
    updated_at: str


class MysticCodeSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str
    name: str = ""
    level: int = Field(default=1, ge=1, le=10)
    cooldown: int = Field(default=0, ge=0, le=99)
    effects: list[dict] = Field(default_factory=list)


class MysticCodeRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    level: int = Field(default=1, ge=1, le=10)
    skills: list[MysticCodeSkill] = Field(default_factory=list)
    source: str = Field(default="manual", max_length=40)
    confidence: ConfidenceState = "confirmed"
    notes: str = Field(default="", max_length=500)


class MysticCodeRecord(MysticCodeRecordInput):
    record_id: str
    updated_at: str


class SupportPreferenceRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    class_name: str = Field(default="", max_length=40)
    np_level: int | None = Field(default=None, ge=1, le=5)
    skill_1: int | None = Field(default=None, ge=1, le=10)
    skill_2: int | None = Field(default=None, ge=1, le=10)
    skill_3: int | None = Field(default=None, ge=1, le=10)
    append_2: int | None = Field(default=None, ge=1, le=10)
    craft_essence_name: str = Field(default="", max_length=120)
    friend_only: bool = False
    source: str = Field(default="manual", max_length=40)
    confidence: ConfidenceState = "confirmed"
    notes: str = Field(default="", max_length=500)


class SupportPreferenceRecord(SupportPreferenceRecordInput):
    record_id: str
    updated_at: str
