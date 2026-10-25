"""User-confirmed assumptions used when account inventory is incomplete."""
from __future__ import annotations

import json
import os
from pathlib import Path

import config
from pydantic import BaseModel, ConfigDict, Field


class CombatAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assume_required_craft_essences: bool = True
    craft_essence_confirmation_complete: bool = False
    mystic_codes_default_max_level: bool = True
    current_event_mystic_code_name: str = ""
    current_event_mystic_code_level: int | None = Field(default=None, ge=1, le=10)
    current_event_mystic_code_confirmed: bool = False
    notes: str = ""


class CombatAssumptionsStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or config.GAME_ASSISTANT_CONFIG_DIR / "combat_assumptions.json")

    def get(self) -> CombatAssumptions:
        if not self.path.exists():
            return CombatAssumptions()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return CombatAssumptions.model_validate(payload)

    def update(self, payload: CombatAssumptions) -> CombatAssumptions:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temp.write_text(
            json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(self.path)
        return payload


_STORE: CombatAssumptionsStore | None = None


def get_combat_assumptions() -> CombatAssumptions:
    global _STORE
    if _STORE is None:
        _STORE = CombatAssumptionsStore()
    return _STORE.get()


def update_combat_assumptions(payload: CombatAssumptions) -> CombatAssumptions:
    global _STORE
    if _STORE is None:
        _STORE = CombatAssumptionsStore()
    return _STORE.update(payload)
