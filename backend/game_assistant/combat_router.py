"""Read-only 3T foundation routes and simulations."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .combat_domain import (
    CraftEssenceConfirmation,
    CombatProfile,
    ExecutionPreflightRequest,
    ExecutionPreflightResult,
    RecommendationRequest,
    RecommendationResult,
    SimulationRequest,
    SimulationResult,
    TeamPlan,
)
from .combat_assumptions import CombatAssumptions, get_combat_assumptions, update_combat_assumptions
from .combat_recommender import recommend
from .combat_simulator import simulate
from .combat_store import get_combat_store
from .craft_essence_confirmation import get_craft_essence_confirmation_store
from .execution_preflight import PreflightError, preflight
from . import quest_profile_import

router = APIRouter(prefix="/api/game-assistant/fgo/3t", tags=["game-assistant-3t"])


@router.get("/foundation")
def foundation() -> dict:
    store = get_combat_store()
    profiles = store.list_profiles()
    plans = store.list_plans()
    return {
        "status": "ready",
        "contracts": [
            "CombatProfile",
            "EnemyWave",
            "EnemyUnit",
            "CombatantSnapshot",
            "TeamPlan",
            "TeamPlanAction",
            "SimulationResult",
        ],
        "combat_profiles": len(profiles),
        "team_plans": len(plans),
        "mock_profiles": sum(1 for item in profiles if item.mock),
        "simulator": {
            "available": True,
            "accuracy": "mvp_simplified",
            "supports": ["damage_range", "class_relation", "buffs", "np_change", "three_turn_clear_gate"],
        },
    }


@router.get("/combat-profiles", response_model=list[CombatProfile])
def list_combat_profiles() -> list[CombatProfile]:
    return get_combat_store().list_profiles()


@router.get("/combat-profiles/{quest_id}", response_model=CombatProfile)
def get_combat_profile(quest_id: str) -> CombatProfile:
    profile = get_combat_store().get_profile(quest_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="combat profile not found")
    return profile


class CombatProfileImportRequest(BaseModel):
    """从 Mooncell 关卡配置表导入一份战斗档案。

    执行**不需要**档案（runbook 自带动作流）；档案是给 3T 推荐用的。导入一律
    `mock=False` / `verified=False`：数字来自公开 wiki，要人游戏内实测确认后才算数。
    """

    model_config = ConfigDict(extra="forbid")

    quest_id: str = Field(min_length=1, max_length=120)
    quest_name: str = Field(min_length=1, max_length=200)
    heading_id: str = Field(
        min_length=1, max_length=200, description="Mooncell 页面里那一节的锚点 id（URL 里 # 后面那截）"
    )
    event_id: str = Field(default="", max_length=120)
    url: str = Field(default="", max_length=500, description="Mooncell 页面链接；与 html 二选一")
    html: str = Field(default="", description="直接贴页面 HTML（离线或抓不到时兜底）")
    source_ids: list[str] = Field(default_factory=list)
    overwrite: bool = Field(default=False, description="已有同名 quest_id 时是否覆盖（默认 409 拦住）")


@router.post("/combat-profiles/import")
def import_combat_profile(request: CombatProfileImportRequest) -> dict:
    """把 Mooncell 的一张关卡表解析成 `CombatProfile` 存进档案库（不覆盖已有档案，除非显式 overwrite）。

    解析器是**窄口**的：只认标准「关卡配置」战斗表，读不出的字段一律报 warning，**不猜数值**。
    """
    store = get_combat_store()
    existing = store.get_profile(request.quest_id)
    if existing is not None and not request.overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"已经有 {request.quest_id} 的档案了；要覆盖请带 overwrite=true",
        )
    try:
        page = request.html.strip()
        if not page:
            if not request.url.strip():
                raise quest_profile_import.QuestParseError("需要给 Mooncell 页面链接，或直接贴页面 HTML")
            page = quest_profile_import.load_page(request.url)
        section = quest_profile_import.find_quest_section(page, request.heading_id)
        parsed = quest_profile_import.parse_quest_section(section)
        profile = quest_profile_import.build_profile(
            parsed,
            quest_id=request.quest_id,
            event_id=request.event_id,
            quest_name=request.quest_name,
            source_ids=request.source_ids,
            source_url=request.url,
        )
    except quest_profile_import.QuestParseError as exc:
        raise HTTPException(status_code=400, detail=f"解析失败：{exc}") from exc
    except Exception as exc:   # 抓页面失败（网络/404）：502，让调用方知道是上游的问题
        raise HTTPException(status_code=502, detail=f"抓 Mooncell 页面失败：{exc}") from exc
    store.save_profile(profile)
    return {
        "profile": profile.model_dump(mode="json"),
        "warnings": list(parsed.warnings),
        "note": "档案来自公开 wiki（mock=false / verified=false）：推荐可以用，但开刷前仍需人工确认数字。",
    }


@router.get("/team-plans", response_model=list[TeamPlan])
def list_team_plans() -> list[TeamPlan]:
    return get_combat_store().list_plans()


@router.post("/simulate", response_model=SimulationResult)
def simulate_team_plan(request: SimulationRequest) -> SimulationResult:
    try:
        return simulate(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/preflight", response_model=ExecutionPreflightResult)
def execution_preflight(request: ExecutionPreflightRequest) -> ExecutionPreflightResult:
    try:
        return preflight(request, get_combat_store())
    except PreflightError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/recommend", response_model=RecommendationResult)
def recommend_team(request: RecommendationRequest) -> RecommendationResult:
    """按关卡生成 3T 候选队伍：选人、每回合行动、伤害/宝具闸门、最低练度与失败条件。"""
    try:
        return recommend(request, store=get_combat_store())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/craft-essence-confirmation/{plan_id}", response_model=CraftEssenceConfirmation)
def read_craft_essence_confirmation(plan_id: str) -> CraftEssenceConfirmation:
    record = get_craft_essence_confirmation_store().get(plan_id)
    if record is None:
        raise HTTPException(status_code=404, detail="craft essence confirmation not found")
    return record


@router.put("/craft-essence-confirmation", response_model=CraftEssenceConfirmation)
def write_craft_essence_confirmation(payload: CraftEssenceConfirmation) -> CraftEssenceConfirmation:
    """登记某个方案的概念礼装可用性确认；未确认或仍缺项时执行预检保持 blocked。"""
    return get_craft_essence_confirmation_store().save(payload)


@router.get("/assumptions", response_model=CombatAssumptions)
def read_assumptions() -> CombatAssumptions:
    return get_combat_assumptions()


@router.put("/assumptions", response_model=CombatAssumptions)
def write_assumptions(payload: CombatAssumptions) -> CombatAssumptions:
    return update_combat_assumptions(payload)
