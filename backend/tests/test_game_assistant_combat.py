from __future__ import annotations

from game_assistant.combat_domain import SimulationRequest
from game_assistant.combat_simulator import simulate
from game_assistant.combat_store import CombatStore
from game_assistant.combat_domain import ExecutionPreflightRequest
from game_assistant.execution_preflight import preflight


def test_mock_90pp_profile_is_structured() -> None:
    store = CombatStore()
    profile = store.get_profile("free_ikeda_1_90pp_mock")
    assert profile is not None
    assert profile.mock is True
    assert [wave.wave_index for wave in profile.waves] == [1, 2, 3]
    assert profile.total_enemy_hp == 1_639_409


def test_mock_plan_clears_by_turn_three() -> None:
    store = CombatStore()
    profile = store.get_profile("free_ikeda_1_90pp_mock")
    plan = store.get_plan("mock-90pp-3t-plan")
    assert profile is not None
    assert plan is not None
    result = simulate(SimulationRequest(profile=profile, plan=plan))
    assert result.status == "success"
    assert result.cleared_by_turn == 3
    assert result.errors == []
    assert len(result.damage_gates) == 5


def test_higher_attack_increases_damage() -> None:
    store = CombatStore()
    profile = store.get_profile("free_ikeda_1_90pp_mock")
    plan = store.get_plan("mock-90pp-3t-plan")
    assert profile is not None and plan is not None
    baseline = simulate(SimulationRequest(profile=profile, plan=plan))
    boosted = plan.model_copy(deep=True)
    boosted.combatants[0].attack *= 2
    stronger = simulate(SimulationRequest(profile=profile, plan=boosted))
    assert stronger.total_damage_avg > baseline.total_damage_avg


def test_insufficient_damage_fails_three_turn_clear() -> None:
    store = CombatStore()
    profile = store.get_profile("free_ikeda_1_90pp_mock")
    plan = store.get_plan("mock-90pp-3t-plan")
    assert profile is not None and plan is not None
    weak = plan.model_copy(deep=True)
    weak.combatants[0].attack = 1
    result = simulate(SimulationRequest(profile=profile, plan=weak))
    assert result.status == "failed"
    assert result.cleared_by_turn is None


def test_3t_foundation_api(client) -> None:
    response = client.get("/api/game-assistant/fgo/3t/foundation")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["combat_profiles"] >= 1
    assert payload["team_plans"] >= 1



def test_execution_preflight_blocks_mock_execution_but_allows_dry_run() -> None:
    result = preflight(
        ExecutionPreflightRequest(
            quest_id="free_ikeda_1_90pp_mock",
            plan_id="mock-90pp-3t-plan",
        )
    )
    assert result.status == "ready_for_dry_run"
    assert result.can_dry_run is True
    assert result.can_execute is False
    assert any(check.check_id == "profile_verified" and check.status == "blocked" for check in result.checks)


def test_execution_preflight_api(client) -> None:
    response = client.post(
        "/api/game-assistant/fgo/3t/preflight",
        json={
            "quest_id": "free_ikeda_1_90pp_mock",
            "plan_id": "mock-90pp-3t-plan",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready_for_dry_run"
    assert payload["can_execute"] is False
