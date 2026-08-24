"""SQLite 数据库：记录 Agent 对话、绘画、提示词 Agent 行为。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(r"D:\workSpace\code\骑手招聘助手\AIproduct\rider_studio.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_chat_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    retrieval_score REAL,
    source TEXT
);
CREATE TABLE IF NOT EXISTS draw_records (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      started_at TEXT NOT NULL,
      batch_id TEXT,
      group_index INTEGER,
      finished_at TEXT,
    duration_seconds REAL,
    prompt TEXT,
    prompt_translation TEXT,
    negative_prompt TEXT,
    negative_translation TEXT,
    width INTEGER,
    height INTEGER,
    steps INTEGER,
    cfg REAL,
    model TEXT,
    lora_anima_turbo INTEGER DEFAULT 0,
    lora_high_contrast INTEGER DEFAULT 0,
    image_path TEXT,
    image_url TEXT,
    seed INTEGER,
    status TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS prompt_agent_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_seconds REAL,
    mode TEXT,
    user_input TEXT,
    image_path TEXT,
    description TEXT,
    prompt_result TEXT,
    model TEXT,
    status TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_created ON agent_chat_records(created_at);
CREATE INDEX IF NOT EXISTS idx_draw_started ON draw_records(started_at);
CREATE INDEX IF NOT EXISTS idx_prompt_started ON prompt_agent_records(started_at);
"""

_TABLES = {
    "agent": "agent_chat_records",
    "draw": "draw_records",
    "prompt": "prompt_agent_records",
}


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
  with get_connection() as conn:
      conn.executescript(_SCHEMA)
      _ensure_draw_columns()


def _ensure_draw_columns() -> None:
      """为旧数据库补充 model / batch_id / group_index 列。"""
      with get_connection() as conn:
          columns = [row["name"] for row in conn.execute("PRAGMA table_info(draw_records)").fetchall()]
          if "model" not in columns:
              conn.execute("ALTER TABLE draw_records ADD COLUMN model TEXT")
          if "batch_id" not in columns:
              conn.execute("ALTER TABLE draw_records ADD COLUMN batch_id TEXT")
          if "group_index" not in columns:
              conn.execute("ALTER TABLE draw_records ADD COLUMN group_index INTEGER")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def insert_agent_message(
    session_id: str,
    sender: str,
    content: str,
    retrieval_score: float | None = None,
    source: str | None = None,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO agent_chat_records (session_id, created_at, sender, content, retrieval_score, source) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, now_iso(), sender, content, retrieval_score, source),
        )
        return int(cursor.lastrowid)


def insert_draw_start(
    prompt: str,
    prompt_translation: str,
    negative_prompt: str,
    negative_translation: str,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    model: str,
    lora_anima_turbo: bool,
    lora_high_contrast: bool,
    batch_id: str | None = None,
    group_index: int | None = None,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO draw_records (
                started_at, batch_id, group_index, prompt, prompt_translation, negative_prompt, negative_translation,
                width, height, steps, cfg, model, lora_anima_turbo, lora_high_contrast, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                batch_id,
                group_index,
                prompt,
                prompt_translation,
                negative_prompt,
                negative_translation,
                width,
                height,
                steps,
                cfg,
                model,
                1 if lora_anima_turbo else 0,
                1 if lora_high_contrast else 0,
                "running",
            ),
        )
        return int(cursor.lastrowid)


def finish_draw(
    record_id: int,
    duration_seconds: float,
    image_path: str | None,
    image_url: str | None,
    seed: int | None,
    status: str,
    error: str | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE draw_records
            SET finished_at = ?, duration_seconds = ?, image_path = ?, image_url = ?, seed = ?, status = ?, error = ?
            WHERE id = ?
            """,
            (now_iso(), duration_seconds, image_path, image_url, seed, status, error, record_id),
        )


def insert_prompt_record(
    mode: str,
    user_input: str | None,
    image_path: str | None,
    description: str | None,
    prompt_result: str | None,
    model: str,
    status: str,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO prompt_agent_records (
                started_at, finished_at, duration_seconds, mode, user_input, image_path,
                description, prompt_result, model, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                started_at,
                finished_at,
                duration_seconds,
                mode,
                user_input,
                image_path,
                description,
                prompt_result,
                model,
                status,
            ),
        )
        return int(cursor.lastrowid)


def _date_clause(kind: str, date_from: str | None, date_to: str | None) -> tuple[str, list]:
    column = "started_at" if kind in ("draw", "prompt") else "created_at"
    clauses = []
    params: list[str] = []
    if date_from:
        clauses.append(f"substr({column}, 1, 10) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append(f"substr({column}, 1, 10) <= ?")
        params.append(date_to)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def query_records(
    kind: str,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    table = _TABLES[kind]
    where, params = _date_clause(kind, date_from, date_to)
    with get_connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM {table} {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM {table} {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [dict(row) for row in rows],
    }


def export_records(
    kind: str,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10000,
) -> list[dict]:
    table = _TABLES[kind]
    where, params = _date_clause(kind, date_from, date_to)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM {table} {where} ORDER BY id DESC LIMIT ?",
            params + [limit],
        ).fetchall()
    return [dict(row) for row in rows]


def available_kinds() -> list[str]:
    return list(_TABLES.keys())


def get_setting(key: str, default: str = "") -> str:
    """读取设置项，不存在时返回默认值。"""
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    """写入或更新设置项。"""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
