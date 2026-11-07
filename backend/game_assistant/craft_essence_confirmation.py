"""Per-plan Craft Essence feasibility confirmation.

The 2026-10-08 decision allows recommendation generation to assume that required
Craft Essences are available, but demands an explicit human confirmation step
before a plan may proceed to Dry Run or execution. This module stores that
confirmation per TeamPlan and is consulted by the execution preflight.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import config

from .combat_domain import CraftEssenceConfirmation

CONFIRMATION_FILENAME = "craft_essence_confirmations.json"


class CraftEssenceConfirmationStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or Path(config.GAME_ASSISTANT_CONFIG_DIR) / CONFIRMATION_FILENAME)

    def _read(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        records = payload.get("confirmations") if isinstance(payload, dict) else None
        return {str(key): value for key, value in (records or {}).items() if isinstance(value, dict)}

    def _write(self, records: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temp.write_text(
            json.dumps({"format": 1, "confirmations": records}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(self.path)

    def get(self, plan_id: str) -> CraftEssenceConfirmation | None:
        record = self._read().get(plan_id)
        if record is None:
            return None
        return CraftEssenceConfirmation.model_validate(record)

    def list(self) -> list[CraftEssenceConfirmation]:
        return [CraftEssenceConfirmation.model_validate(item) for item in self._read().values()]

    def save(self, payload: CraftEssenceConfirmation) -> CraftEssenceConfirmation:
        record = payload.model_copy(
            update={"updated_at": datetime.now().astimezone().isoformat(timespec="seconds")}
        )
        records = self._read()
        records[record.plan_id] = record.model_dump(mode="json")
        self._write(records)
        return record

    def delete(self, plan_id: str) -> bool:
        records = self._read()
        if plan_id not in records:
            return False
        records.pop(plan_id)
        self._write(records)
        return True


_STORE: CraftEssenceConfirmationStore | None = None


def get_craft_essence_confirmation_store() -> CraftEssenceConfirmationStore:
    global _STORE
    if _STORE is None:
        _STORE = CraftEssenceConfirmationStore()
    return _STORE


def reset_craft_essence_confirmation_store() -> None:
    global _STORE
    _STORE = None
