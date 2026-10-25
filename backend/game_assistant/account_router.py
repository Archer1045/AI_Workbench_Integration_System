"""Local account snapshot CRUD routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .account_domain import (
    AccountSnapshotSummary,
    CraftEssenceRecord,
    CraftEssenceRecordInput,
    MaterialRecord,
    MaterialRecordInput,
    MysticCodeRecord,
    MysticCodeRecordInput,
    ServantRecord,
    ServantRecordInput,
    SupportPreferenceRecord,
    SupportPreferenceRecordInput,
)
from .account_store import AccountSnapshotStore

router = APIRouter(prefix="/api/game-assistant/fgo/account", tags=["game-assistant-account"])
_STORE: AccountSnapshotStore | None = None


def get_store() -> AccountSnapshotStore:
    global _STORE
    if _STORE is None:
        _STORE = AccountSnapshotStore()
    return _STORE


@router.get("/summary", response_model=AccountSnapshotSummary)
def summary() -> AccountSnapshotSummary:
    return get_store().summary()


@router.get("/servants", response_model=list[ServantRecord])
def list_servants() -> list[ServantRecord]:
    return get_store().list_servants()


@router.post("/servants", response_model=ServantRecord)
def create_servant(payload: ServantRecordInput) -> ServantRecord:
    return get_store().upsert_servant(payload)


@router.put("/servants/{record_id}", response_model=ServantRecord)
def update_servant(record_id: str, payload: ServantRecordInput) -> ServantRecord:
    return get_store().upsert_servant(payload, record_id)


@router.delete("/servants/{record_id}")
def delete_servant(record_id: str) -> dict[str, bool]:
    if not get_store().delete_servant(record_id):
        raise HTTPException(status_code=404, detail="servant record not found")
    return {"deleted": True}


@router.get("/materials", response_model=list[MaterialRecord])
def list_materials() -> list[MaterialRecord]:
    return get_store().list_materials()


@router.post("/materials", response_model=MaterialRecord)
def create_material(payload: MaterialRecordInput) -> MaterialRecord:
    return get_store().upsert_material(payload)


@router.put("/materials/{record_id}", response_model=MaterialRecord)
def update_material(record_id: str, payload: MaterialRecordInput) -> MaterialRecord:
    return get_store().upsert_material(payload, record_id)


@router.delete("/materials/{record_id}")
def delete_material(record_id: str) -> dict[str, bool]:
    if not get_store().delete_material(record_id):
        raise HTTPException(status_code=404, detail="material record not found")
    return {"deleted": True}

@router.get("/craft-essences", response_model=list[CraftEssenceRecord])
def list_craft_essences() -> list[CraftEssenceRecord]:
    return get_store().list_craft_essences()


@router.post("/craft-essences", response_model=CraftEssenceRecord)
def create_craft_essence(payload: CraftEssenceRecordInput) -> CraftEssenceRecord:
    return get_store().upsert_craft_essence(payload)


@router.put("/craft-essences/{record_id}", response_model=CraftEssenceRecord)
def update_craft_essence(record_id: str, payload: CraftEssenceRecordInput) -> CraftEssenceRecord:
    return get_store().upsert_craft_essence(payload, record_id)


@router.delete("/craft-essences/{record_id}")
def delete_craft_essence(record_id: str) -> dict[str, bool]:
    if not get_store().delete_craft_essence(record_id):
        raise HTTPException(status_code=404, detail="craft essence record not found")
    return {"deleted": True}


@router.get("/mystic-codes", response_model=list[MysticCodeRecord])
def list_mystic_codes() -> list[MysticCodeRecord]:
    return get_store().list_mystic_codes()


@router.post("/mystic-codes", response_model=MysticCodeRecord)
def create_mystic_code(payload: MysticCodeRecordInput) -> MysticCodeRecord:
    return get_store().upsert_mystic_code(payload)


@router.put("/mystic-codes/{record_id}", response_model=MysticCodeRecord)
def update_mystic_code(record_id: str, payload: MysticCodeRecordInput) -> MysticCodeRecord:
    return get_store().upsert_mystic_code(payload, record_id)


@router.delete("/mystic-codes/{record_id}")
def delete_mystic_code(record_id: str) -> dict[str, bool]:
    if not get_store().delete_mystic_code(record_id):
        raise HTTPException(status_code=404, detail="mystic code record not found")
    return {"deleted": True}


@router.get("/support-preferences", response_model=list[SupportPreferenceRecord])
def list_support_preferences() -> list[SupportPreferenceRecord]:
    return get_store().list_support_preferences()


@router.post("/support-preferences", response_model=SupportPreferenceRecord)
def create_support_preference(payload: SupportPreferenceRecordInput) -> SupportPreferenceRecord:
    return get_store().upsert_support_preference(payload)


@router.put("/support-preferences/{record_id}", response_model=SupportPreferenceRecord)
def update_support_preference(record_id: str, payload: SupportPreferenceRecordInput) -> SupportPreferenceRecord:
    return get_store().upsert_support_preference(payload, record_id)


@router.delete("/support-preferences/{record_id}")
def delete_support_preference(record_id: str) -> dict[str, bool]:
    if not get_store().delete_support_preference(record_id):
        raise HTTPException(status_code=404, detail="support preference record not found")
    return {"deleted": True}
