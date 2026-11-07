"""SQLite persistence for the public FGO knowledge bundle and generated guides."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

import config

from .domain import EventBundle, GuideGenerationResult

DB_PATH = config.GAME_ASSISTANT_DB_PATH
_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
_FIXTURE_PATHS = (
    _FIXTURE_DIR / "fgo_current_event.json",
    _FIXTURE_DIR / "fgo_cn_2026_halloween.json",
)
_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ga_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ga_event_bundles (
    event_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    server TEXT NOT NULL,
    title TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (event_id, revision)
);
CREATE TABLE IF NOT EXISTS ga_generation_runs (
    generation_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    event_revision INTEGER NOT NULL,
    provider_requested TEXT NOT NULL,
    provider_used TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL,
    guide_json TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ga_event_active
ON ga_event_bundles(active, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ga_generation_event
ON ga_generation_runs(event_id, event_revision, created_at DESC);
"""


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)


class GameAssistantStore:
    """Store public event facts separately from the studio and private account DB."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or DB_PATH)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            conn.close()

    def initialize(self, *, seed: bool = True) -> None:
        with self.connect() as conn:
            conn.executescript(_SCHEMA)
            row = conn.execute(
                "SELECT value FROM ga_meta WHERE key = 'schema_version'"
            ).fetchone()
            version = int(row["value"]) if row else 0
            if version < _SCHEMA_VERSION:
                conn.execute(
                    "INSERT INTO ga_meta(key, value) VALUES('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(_SCHEMA_VERSION),),
                )
            conn.commit()
        if seed:
            self.ensure_fixture()

    def ensure_fixture(self) -> None:
        for fixture_path in _FIXTURE_PATHS:
            if not fixture_path.exists():
                raise FileNotFoundError(f"fixture not found: {fixture_path}")
            payload = json.loads(fixture_path.read_text(encoding="utf-8"))
            bundle = EventBundle.model_validate(payload)
            current = self.get_bundle(bundle.event_id)
            if current is not None and current.revision >= bundle.revision:
                continue
            self.save_bundle(bundle)
    def save_bundle(self, bundle: EventBundle) -> EventBundle:
        payload = _dump(bundle.model_dump(mode="json"))
        content_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                "UPDATE ga_event_bundles SET active = 0 WHERE event_id = ?",
                (bundle.event_id,),
            )
            conn.execute(
                """
                INSERT INTO ga_event_bundles(
                    event_id, revision, server, title, payload_json,
                    content_hash, active, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(event_id, revision) DO UPDATE SET
                    server=excluded.server,
                    title=excluded.title,
                    payload_json=excluded.payload_json,
                    content_hash=excluded.content_hash,
                    active=1,
                    updated_at=excluded.updated_at
                """,
                (
                    bundle.event_id,
                    bundle.revision,
                    bundle.server,
                    bundle.title,
                    payload,
                    content_hash,
                    now,
                ),
            )
            conn.commit()
        return bundle

    def list_bundles(self, *, active_only: bool = True) -> list[EventBundle]:
        where = "WHERE active = 1" if active_only else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT payload_json FROM ga_event_bundles {where} "
                "ORDER BY updated_at DESC, revision DESC"
            ).fetchall()
        return [EventBundle.model_validate(json.loads(row["payload_json"])) for row in rows]

    def get_bundle(
        self,
        event_id: str | None = None,
        revision: int | None = None,
    ) -> EventBundle | None:
        clauses: list[str] = []
        values: list[object] = []
        if event_id is not None:
            clauses.append("event_id = ?")
            values.append(event_id)
        if revision is not None:
            clauses.append("revision = ?")
            values.append(revision)
        clauses.append("active = 1")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM ga_event_bundles WHERE "
                + " AND ".join(clauses)
                + " ORDER BY updated_at DESC, revision DESC LIMIT 1",
                values,
            ).fetchone()
        if row is None:
            return None
        return EventBundle.model_validate(json.loads(row["payload_json"]))
    def save_generation(self, result: GuideGenerationResult) -> None:
        payload = result.model_dump(mode="json")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ga_generation_runs(
                    generation_id, event_id, event_revision,
                    provider_requested, provider_used, model, prompt_version,
                    guide_json, plan_json, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(generation_id) DO UPDATE SET
                    provider_used=excluded.provider_used,
                    model=excluded.model,
                    guide_json=excluded.guide_json,
                    plan_json=excluded.plan_json,
                    result_json=excluded.result_json
                """,
                (
                    result.generation_id,
                    result.event_id,
                    result.event_revision,
                    result.provider_requested,
                    result.provider_used,
                    result.model,
                    result.prompt_version,
                    _dump(payload["guide"]),
                    _dump(payload["plan"]),
                    _dump(payload),
                    result.created_at.isoformat(timespec="seconds"),
                ),
            )
            conn.commit()

    def get_generation(self, generation_id: str) -> GuideGenerationResult | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT result_json FROM ga_generation_runs WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
        if row is None:
            return None
        return GuideGenerationResult.model_validate(json.loads(row["result_json"]))

    def latest_generation(
        self,
        event_id: str,
        revision: int | None = None,
    ) -> GuideGenerationResult | None:
        clauses = ["event_id = ?"]
        values: list[object] = [event_id]
        if revision is not None:
            clauses.append("event_revision = ?")
            values.append(revision)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT result_json FROM ga_generation_runs WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC LIMIT 1",
                values,
            ).fetchone()
        if row is None:
            return None
        return GuideGenerationResult.model_validate(json.loads(row["result_json"]))
