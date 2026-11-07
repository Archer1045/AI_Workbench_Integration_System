"""File-backed 3T combat profiles and TeamPlans."""
from __future__ import annotations

import json
from pathlib import Path

import config

from .combat_domain import CombatProfile, TeamPlan

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


class CombatStore:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or config.GAME_ASSISTANT_COMBAT_DIR)
        self.root.mkdir(parents=True, exist_ok=True)

    def _profile_paths(self) -> list[Path]:
        paths = list(self.root.glob("*.profile.json"))
        paths.extend(_FIXTURE_DIR.glob("*.profile.json"))
        return sorted(paths, key=lambda item: item.name)

    def _plan_paths(self) -> list[Path]:
        paths = list(self.root.glob("*.plan.json"))
        paths.extend(_FIXTURE_DIR.glob("*.plan.json"))
        return sorted(paths, key=lambda item: item.name)

    def list_profiles(self) -> list[CombatProfile]:
        profiles: list[CombatProfile] = []
        seen: set[str] = set()
        for path in self._profile_paths():
            profile = CombatProfile.model_validate(json.loads(path.read_text(encoding="utf-8")))
            if profile.quest_id not in seen:
                profiles.append(profile)
                seen.add(profile.quest_id)
        return profiles

    def get_profile(self, quest_id: str) -> CombatProfile | None:
        return next((item for item in self.list_profiles() if item.quest_id == quest_id), None)

    def save_profile(self, profile: CombatProfile) -> CombatProfile:
        path = self.root / f"{profile.quest_id}.profile.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
        return profile

    def list_plans(self) -> list[TeamPlan]:
        plans: list[TeamPlan] = []
        for path in self._plan_paths():
            plans.append(TeamPlan.model_validate(json.loads(path.read_text(encoding="utf-8"))))
        return plans

    def get_plan(self, plan_id: str) -> TeamPlan | None:
        return next((item for item in self.list_plans() if item.plan_id == plan_id), None)

    def save_plan(self, plan: TeamPlan) -> TeamPlan:
        path = self.root / f"{plan.plan_id}.plan.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
        return plan


_STORE: CombatStore | None = None


def get_combat_store() -> CombatStore:
    global _STORE
    if _STORE is None:
        _STORE = CombatStore()
    return _STORE


def reset_combat_store() -> None:
    global _STORE
    _STORE = None
