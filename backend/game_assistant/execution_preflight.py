"""Preflight checks for a 3T execution test. No game input is performed."""
from __future__ import annotations

import task_resources

from .combat_domain import (
    ExecutionPreflightRequest,
    ExecutionPreflightResult,
    PreflightCheck,
    SimulationRequest,
)
from .combat_simulator import simulate
from .combat_assumptions import get_combat_assumptions
from .combat_store import CombatStore
from .craft_essence_confirmation import (
    CraftEssenceConfirmationStore,
    get_craft_essence_confirmation_store,
)


class PreflightError(ValueError):
    pass


def preflight(
    request: ExecutionPreflightRequest,
    store: CombatStore | None = None,
    confirmations: CraftEssenceConfirmationStore | None = None,
) -> ExecutionPreflightResult:
    combat_store = store or CombatStore()
    profile = combat_store.get_profile(request.quest_id)
    plan = combat_store.get_plan(request.plan_id)
    if profile is None:
        raise PreflightError("combat profile not found")
    if plan is None:
        raise PreflightError("TeamPlan not found")
    if plan.quest_id != profile.quest_id:
        raise PreflightError("TeamPlan and combat profile quest_id do not match")

    simulation = simulate(
        SimulationRequest(
            profile=profile,
            plan=plan,
            damage_variance_min=request.damage_variance_min,
            damage_variance_max=request.damage_variance_max,
        )
    )
    assumptions = get_combat_assumptions()
    confirmation = (confirmations or get_craft_essence_confirmation_store()).get(plan.plan_id)
    resources = {item["key"]: item for item in task_resources.snapshot()["resources"]}
    emulator_available = bool(resources.get("emulator", {}).get("available"))
    adb_available = bool(resources.get("adb", {}).get("available"))

    if confirmation is None:
        essence_status = (
            "blocked"
            if assumptions.assume_required_craft_essences
            and not assumptions.craft_essence_confirmation_complete
            else "ok"
        )
        essence_detail = (
            "当前按推荐需求假定礼装可用，但尚未完成人工确认。"
            if essence_status == "blocked"
            else "概念礼装假设状态已确认。"
        )
    elif confirmation.is_satisfied:
        essence_status = "ok"
        essence_detail = (
            f"已确认 {len(confirmation.required_essences)} 项必需礼装可用"
            + (f"（{confirmation.confirmed_by}）" if confirmation.confirmed_by else "")
        )
    else:
        essence_status = "blocked"
        missing = confirmation.missing_essences
        essence_detail = (
            "礼装确认未完成。缺少：" + "、".join(missing) if missing else "礼装确认尚未由用户提交。"
        )

    checks = [
        PreflightCheck(
            check_id="profile_verified",
            label="关卡战斗档案已验证",
            status="ok" if profile.verified and not profile.mock else "blocked",
            detail=(
                "战斗档案已标记为 verified。"
                if profile.verified and not profile.mock
                else "当前仍为 mock 或未验证档案，只能做 dry-run。"
            ),
            required_for_dry_run=False,
            required_for_execution=True,
        ),
        PreflightCheck(
            check_id="three_turn_simulation",
            label="模拟器三回合清场",
            status="ok" if simulation.status == "success" and simulation.cleared_by_turn == 3 else "blocked",
            detail=f"simulation={simulation.status}, cleared_by_turn={simulation.cleared_by_turn}",
        ),
        PreflightCheck(
            check_id="plan_confidence",
            label="TeamPlan 置信度",
            status="ok" if plan.confidence >= 0.8 else "warning",
            detail=f"confidence={plan.confidence}",
            required_for_dry_run=False,
        ),
        PreflightCheck(
            check_id="craft_essence_confirmation",
            label="概念礼装可用性已人工确认",
            status=essence_status,
            detail=essence_detail,
            required_for_dry_run=False,
            required_for_execution=True,
        ),
        PreflightCheck(
            check_id="current_event_mystic_code",
            label="本次活动御主礼装已确认",
            status=(
                "blocked"
                if not assumptions.mystic_codes_default_max_level
                or (assumptions.current_event_mystic_code_name and not assumptions.current_event_mystic_code_confirmed)
                else "ok"
            ),
            detail=(
                f"{assumptions.current_event_mystic_code_name} 尚未确认等级。"
                if assumptions.current_event_mystic_code_name and not assumptions.current_event_mystic_code_confirmed
                else "非本次活动御主礼装按满级处理；当前活动礼装状态已确认。"
            ),
            required_for_dry_run=False,
            required_for_execution=True,
        ),
        PreflightCheck(
            check_id="emulator_resource",
            label="模拟器资源可用",
            status="ok" if emulator_available else "blocked",
            detail="emulator resource is available" if emulator_available else "emulator resource is busy or unavailable.",
            required_for_dry_run=False,
        ),
        PreflightCheck(
            check_id="adb_resource",
            label="ADB 资源可用",
            status="ok" if adb_available else "blocked",
            detail="adb resource is available" if adb_available else "adb resource is busy or unavailable.",
            required_for_dry_run=False,
        ),
    ]

    can_dry_run = simulation.status == "success"
    can_execute = all(
        check.status == "ok"
        for check in checks
        if check.required_for_execution
    )
    status = "ready_for_execution" if can_execute else ("ready_for_dry_run" if can_dry_run else "blocked")
    blockers = [check.label for check in checks if check.status == "blocked"]
    summary = (
        "预检通过，可以进入受控执行测试。"
        if can_execute
        else f"当前可做 dry-run；正式执行仍有 {len(blockers)} 项阻塞：" + "、".join(blockers)
    )
    return ExecutionPreflightResult(
        status=status,
        quest_id=request.quest_id,
        plan_id=request.plan_id,
        simulation_status=simulation.status,
        clears_by_turn=simulation.cleared_by_turn,
        checks=checks,
        can_dry_run=can_dry_run,
        can_execute=can_execute,
        summary=summary,
    )
