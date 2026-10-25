"""Contracts for URL source ingestion and event revision drafts."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain import (
    EventBonusServant,
    EventPhase,
    MechanicNote,
    Mission,
    Quest,
    ShopItem,
    SourceType,
)


class SourceIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = None
    text: str | None = None
    source_type: SourceType = "guide"
    title: str = ""
    publisher: str = ""
    event_id: str | None = None
    revision: int | None = None

    @model_validator(mode="after")
    def require_content(self) -> "SourceIngestRequest":
        if not (self.url or "").strip() and not (self.text or "").strip():
            raise ValueError("URL 和正文至少填写一项")
        return self


class SourceDiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)
    count: int = Field(default=8, ge=1, le=20)
    days: int = Field(default=60, ge=0, le=730)


class SourceDiscoverItem(BaseModel):
    title: str = ""
    url: str
    summary: str = ""
    date: str | None = None
    authority: int | None = None
    site_name: str | None = None
    source_type: SourceType = "guide"


class SourceDiscoverResult(BaseModel):
    provider: str
    cached: bool = False
    query: str
    results: list[SourceDiscoverItem] = Field(default_factory=list)
    filtered_out: int = 0


class SourceDiscoverIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    source_type: SourceType = "guide"
    title: str = ""
    event_id: str | None = None
    revision: int | None = None




class SourceImageAsset(BaseModel):
    image_id: str
    url: str
    local_path: str = ""
    mime_type: str = ""
    byte_size: int = 0
    sha256: str = ""
    status: Literal["pending", "downloaded", "failed"] = "pending"
    error: str = ""
    analysis_status: Literal["pending", "completed", "failed"] = "pending"
    analysis_text: str = ""
    analysis_facts: list[dict] = Field(default_factory=list)
    analysis_error: str = ""


class SourceImagePrepareResult(BaseModel):
    source_id: str
    total: int
    downloaded: int
    failed: int
    images: list[SourceImageAsset]


class SourceImageAnalysisResult(BaseModel):
    source_id: str
    model: str
    completed: int
    failed: int
    combined_text: str
    images: list[SourceImageAsset]

class SourceExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["local", "deepseek", "openai_compatible"] = "deepseek"


class SourcePublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False


class SourceSnapshot(BaseModel):
    source_id: str
    url: str
    final_url: str
    source_type: SourceType
    title: str
    publisher: str
    fetched_at: datetime
    fetched_via: Literal["url", "manual"]
    content_type: str = ""
    http_status: int | None = None
    content_hash: str
    text_length: int
    excerpt: str
    text: str
    images: list[str] = Field(default_factory=list)
    image_assets: list[SourceImageAsset] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    event_id: str | None = None
    base_revision: int | None = None


class EventRevisionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: dict[str, Any] = Field(default_factory=dict)
    mechanics: list[MechanicNote] = Field(default_factory=list)
    bonus_servants: list[EventBonusServant] = Field(default_factory=list)
    phases: list[EventPhase] = Field(default_factory=list)
    quests: list[Quest] = Field(default_factory=list)
    missions: list[Mission] = Field(default_factory=list)
    shop_items: list[ShopItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RevisionDiff(BaseModel):
    added: dict[str, int] = Field(default_factory=dict)
    updated: dict[str, int] = Field(default_factory=dict)
    conflicts: list[str] = Field(default_factory=list)
    summary: str = ""


class SourceExtractionResult(BaseModel):
    source_id: str
    provider_used: str
    model: str = ""
    patch: EventRevisionPatch
    diff: RevisionDiff
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime


class SourceRecord(SourceSnapshot):
    extraction: SourceExtractionResult | None = None
    published_revision: int | None = None
