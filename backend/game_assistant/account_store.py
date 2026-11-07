"""Local-only account snapshot database.

This database is deliberately separate from the public Game Assistant knowledge
database and must never be sent to cloud providers.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

import config

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

DB_PATH = config.GAME_ASSISTANT_PRIVATE_DB_PATH
_SCHEMA = """
CREATE TABLE IF NOT EXISTS ga_private_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ga_account_servants (
    record_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    class_name TEXT NOT NULL DEFAULT '',
    rarity INTEGER,
    level INTEGER,
    max_level INTEGER,
    np_level INTEGER,
    skill_1 INTEGER,
    skill_2 INTEGER,
    skill_3 INTEGER,
    append_2 INTEGER,
    source TEXT NOT NULL DEFAULT 'manual',
    confidence TEXT NOT NULL DEFAULT 'confirmed',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ga_servants_name ON ga_account_servants(name);
CREATE TABLE IF NOT EXISTS ga_account_materials (
    record_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 0,
    reserve_quantity INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    confidence TEXT NOT NULL DEFAULT 'confirmed',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ga_materials_name ON ga_account_materials(name);
CREATE TABLE IF NOT EXISTS ga_account_craft_essences (
    record_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rarity INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 1,
    max_level INTEGER NOT NULL DEFAULT 1,
    limit_break INTEGER NOT NULL DEFAULT 0,
    attack INTEGER NOT NULL DEFAULT 0,
    hp INTEGER NOT NULL DEFAULT 0,
    cost INTEGER NOT NULL DEFAULT 0,
    effects_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'manual',
    confidence TEXT NOT NULL DEFAULT 'confirmed',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ga_craft_essences_name ON ga_account_craft_essences(name);
CREATE TABLE IF NOT EXISTS ga_account_mystic_codes (
    record_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 1,
    skills_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'manual',
    confidence TEXT NOT NULL DEFAULT 'confirmed',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ga_mystic_codes_name ON ga_account_mystic_codes(name);
CREATE TABLE IF NOT EXISTS ga_account_support_preferences (
    record_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    class_name TEXT NOT NULL DEFAULT '',
    np_level INTEGER,
    skill_1 INTEGER,
    skill_2 INTEGER,
    skill_3 INTEGER,
    append_2 INTEGER,
    craft_essence_name TEXT NOT NULL DEFAULT '',
    friend_only INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'manual',
    confidence TEXT NOT NULL DEFAULT 'confirmed',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ga_support_preferences_name ON ga_account_support_preferences(name);
"""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class AccountSnapshotStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or DB_PATH)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT INTO ga_private_meta(key, value) VALUES('schema_version', '1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
            conn.execute(
                "DELETE FROM ga_account_materials WHERE rowid NOT IN ("
                "SELECT MAX(rowid) FROM ga_account_materials GROUP BY name"
                ")"
            )
            conn.commit()

    def list_servants(self) -> list[ServantRecord]:
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ga_account_servants ORDER BY class_name, name, record_id"
            ).fetchall()
        return [ServantRecord.model_validate(dict(row)) for row in rows]

    def upsert_servant(
        self,
        payload: ServantRecordInput,
        record_id: str | None = None,
    ) -> ServantRecord:
        self.initialize()
        identifier = record_id or uuid.uuid4().hex
        updated_at = _now()
        values = payload.model_dump()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ga_account_servants(
                    record_id, name, class_name, rarity, level, max_level,
                    np_level, skill_1, skill_2, skill_3, append_2,
                    source, confidence, notes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    name=excluded.name,
                    class_name=excluded.class_name,
                    rarity=excluded.rarity,
                    level=excluded.level,
                    max_level=excluded.max_level,
                    np_level=excluded.np_level,
                    skill_1=excluded.skill_1,
                    skill_2=excluded.skill_2,
                    skill_3=excluded.skill_3,
                    append_2=excluded.append_2,
                    source=excluded.source,
                    confidence=excluded.confidence,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (
                    identifier,
                    values["name"],
                    values["class_name"],
                    values["rarity"],
                    values["level"],
                    values["max_level"],
                    values["np_level"],
                    values["skill_1"],
                    values["skill_2"],
                    values["skill_3"],
                    values["append_2"],
                    values["source"],
                    values["confidence"],
                    values["notes"],
                    updated_at,
                ),
            )
            conn.commit()
        return ServantRecord(record_id=identifier, updated_at=updated_at, **values)

    def delete_servant(self, record_id: str) -> bool:
        self.initialize()
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM ga_account_servants WHERE record_id = ?",
                (record_id,),
            )
            conn.commit()
        return cursor.rowcount > 0
    def list_materials(self) -> list[MaterialRecord]:
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ga_account_materials ORDER BY category, name, record_id"
            ).fetchall()
        return [MaterialRecord.model_validate(dict(row)) for row in rows]

    def upsert_material(
        self,
        payload: MaterialRecordInput,
        record_id: str | None = None,
    ) -> MaterialRecord:
        self.initialize()
        updated_at = _now()
        values = payload.model_dump()
        with self.connect() as conn:
            identifier = record_id
            if identifier is None:
                existing = conn.execute(
                    "SELECT record_id FROM ga_account_materials WHERE name = ? ORDER BY rowid LIMIT 1",
                    (values["name"],),
                ).fetchone()
                identifier = existing["record_id"] if existing else uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO ga_account_materials(
                    record_id, name, category, quantity, reserve_quantity,
                    source, confidence, notes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    name=excluded.name,
                    category=excluded.category,
                    quantity=excluded.quantity,
                    reserve_quantity=excluded.reserve_quantity,
                    source=excluded.source,
                    confidence=excluded.confidence,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (
                    identifier,
                    values["name"],
                    values["category"],
                    values["quantity"],
                    values["reserve_quantity"],
                    values["source"],
                    values["confidence"],
                    values["notes"],
                    updated_at,
                ),
            )
            conn.commit()
        return MaterialRecord(record_id=identifier, updated_at=updated_at, **values)

    def delete_material(self, record_id: str) -> bool:
        self.initialize()
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM ga_account_materials WHERE record_id = ?",
                (record_id,),
            )
            conn.commit()
        return cursor.rowcount > 0


    def list_craft_essences(self) -> list[CraftEssenceRecord]:
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ga_account_craft_essences ORDER BY rarity DESC, name"
            ).fetchall()
        return [
            CraftEssenceRecord.model_validate(
                {
                    **{key: value for key, value in dict(row).items() if key != "effects_json"},
                    "effects": json.loads(row["effects_json"] or "[]"),
                }
            )
            for row in rows
        ]

    def upsert_craft_essence(
        self,
        payload: CraftEssenceRecordInput,
        record_id: str | None = None,
    ) -> CraftEssenceRecord:
        self.initialize()
        values = payload.model_dump()
        values["effects_json"] = json.dumps(values.pop("effects"), ensure_ascii=False)
        identifier = record_id or uuid.uuid4().hex
        values["record_id"] = identifier
        values["updated_at"] = _now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ga_account_craft_essences(
                    record_id, name, rarity, level, max_level, limit_break,
                    attack, hp, cost, effects_json, source, confidence, notes, updated_at
                ) VALUES (
                    :record_id, :name, :rarity, :level, :max_level, :limit_break,
                    :attack, :hp, :cost, :effects_json, :source, :confidence, :notes, :updated_at
                )
                ON CONFLICT(record_id) DO UPDATE SET
                    name=excluded.name, rarity=excluded.rarity, level=excluded.level,
                    max_level=excluded.max_level, limit_break=excluded.limit_break,
                    attack=excluded.attack, hp=excluded.hp, cost=excluded.cost,
                    effects_json=excluded.effects_json, source=excluded.source,
                    confidence=excluded.confidence, notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                values,
            )
            conn.commit()
        return next(
            item for item in self.list_craft_essences() if item.record_id == identifier
        )

    def delete_craft_essence(self, record_id: str) -> bool:
        self.initialize()
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM ga_account_craft_essences WHERE record_id = ?", (record_id,))
            conn.commit()
        return cursor.rowcount > 0

    def list_mystic_codes(self) -> list[MysticCodeRecord]:
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM ga_account_mystic_codes ORDER BY name").fetchall()
        return [
            MysticCodeRecord.model_validate(
                {
                    **{key: value for key, value in dict(row).items() if key != "skills_json"},
                    "skills": json.loads(row["skills_json"] or "[]"),
                }
            )
            for row in rows
        ]

    def upsert_mystic_code(
        self,
        payload: MysticCodeRecordInput,
        record_id: str | None = None,
    ) -> MysticCodeRecord:
        self.initialize()
        values = payload.model_dump()
        values["skills_json"] = json.dumps(values.pop("skills"), ensure_ascii=False)
        identifier = record_id or uuid.uuid4().hex
        values["record_id"] = identifier
        values["updated_at"] = _now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ga_account_mystic_codes(
                    record_id, name, level, skills_json, source, confidence, notes, updated_at
                ) VALUES (
                    :record_id, :name, :level, :skills_json, :source, :confidence, :notes, :updated_at
                )
                ON CONFLICT(record_id) DO UPDATE SET
                    name=excluded.name, level=excluded.level, skills_json=excluded.skills_json,
                    source=excluded.source, confidence=excluded.confidence,
                    notes=excluded.notes, updated_at=excluded.updated_at
                """,
                values,
            )
            conn.commit()
        return next(item for item in self.list_mystic_codes() if item.record_id == identifier)

    def delete_mystic_code(self, record_id: str) -> bool:
        self.initialize()
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM ga_account_mystic_codes WHERE record_id = ?", (record_id,))
            conn.commit()
        return cursor.rowcount > 0

    def list_support_preferences(self) -> list[SupportPreferenceRecord]:
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ga_account_support_preferences ORDER BY class_name, name"
            ).fetchall()
        return [
            SupportPreferenceRecord.model_validate(
                {**dict(row), "friend_only": bool(row["friend_only"])}
            )
            for row in rows
        ]

    def upsert_support_preference(
        self,
        payload: SupportPreferenceRecordInput,
        record_id: str | None = None,
    ) -> SupportPreferenceRecord:
        self.initialize()
        values = payload.model_dump()
        values["friend_only"] = int(values["friend_only"])
        identifier = record_id or uuid.uuid4().hex
        values["record_id"] = identifier
        values["updated_at"] = _now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ga_account_support_preferences(
                    record_id, name, class_name, np_level, skill_1, skill_2, skill_3,
                    append_2, craft_essence_name, friend_only, source, confidence, notes, updated_at
                ) VALUES (
                    :record_id, :name, :class_name, :np_level, :skill_1, :skill_2, :skill_3,
                    :append_2, :craft_essence_name, :friend_only, :source, :confidence, :notes, :updated_at
                )
                ON CONFLICT(record_id) DO UPDATE SET
                    name=excluded.name, class_name=excluded.class_name, np_level=excluded.np_level,
                    skill_1=excluded.skill_1, skill_2=excluded.skill_2, skill_3=excluded.skill_3,
                    append_2=excluded.append_2, craft_essence_name=excluded.craft_essence_name,
                    friend_only=excluded.friend_only, source=excluded.source,
                    confidence=excluded.confidence, notes=excluded.notes, updated_at=excluded.updated_at
                """,
                values,
            )
            conn.commit()
        return next(
            item for item in self.list_support_preferences() if item.record_id == identifier
        )

    def delete_support_preference(self, record_id: str) -> bool:
        self.initialize()
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM ga_account_support_preferences WHERE record_id = ?", (record_id,))
            conn.commit()
        return cursor.rowcount > 0

    def summary(self) -> AccountSnapshotSummary:
        self.initialize()
        with self.connect() as conn:
            servant_count = conn.execute(
                "SELECT COUNT(*) FROM ga_account_servants"
            ).fetchone()[0]
            material_count = conn.execute(
                "SELECT COUNT(*) FROM ga_account_materials"
            ).fetchone()[0]
            confirmed = conn.execute(
                "SELECT COUNT(*) FROM ga_account_servants WHERE confidence = 'confirmed'"
            ).fetchone()[0]
            candidates = conn.execute(
                "SELECT COUNT(*) FROM ga_account_servants WHERE confidence = 'candidate'"
            ).fetchone()[0]
        return AccountSnapshotSummary(
            servants=int(servant_count),
            materials=int(material_count),
            confirmed_servants=int(confirmed),
            candidate_servants=int(candidates),
        )