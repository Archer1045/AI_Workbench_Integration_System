"""SQLite 数据库：记录 Agent 对话、绘画、提示词 Agent 行为。"""
from __future__ import annotations

import sqlite3
import json
import time
import uuid
from datetime import datetime, timedelta

import character_presets
import character_prompt_presets
import config

DB_PATH = config.DB_PATH


class ResourceConflictError(RuntimeError):
    """Raised when a task cannot atomically acquire all requested resources."""

    def __init__(self, conflicts: list[dict]) -> None:
        self.conflicts = list(conflicts)
        super().__init__("task resource conflict")

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
    prompt_document_json TEXT DEFAULT '{}',
    width INTEGER,
    height INTEGER,
    steps INTEGER,
    cfg REAL,
    loras_json TEXT DEFAULT '[]',
    model TEXT,
    lora_anima_turbo INTEGER DEFAULT 0,
    lora_high_contrast INTEGER DEFAULT 0,
    image_path TEXT,
    image_url TEXT,
    seed INTEGER,
    status TEXT,
    error TEXT,
    edit_mode TEXT DEFAULT 'generate',
    source_record_id INTEGER,
    source_image_path TEXT,
    mask_image_path TEXT,
    masked_prompt TEXT,
    inpaint_denoise REAL,
    edit_params_json TEXT DEFAULT '{}'
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
CREATE TABLE IF NOT EXISTS prompt_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT '其他',
    content TEXT NOT NULL,
    translation TEXT DEFAULT '',
    description TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    composition_json TEXT DEFAULT '{}',
    prompt_document_json TEXT DEFAULT '{}',
    use_count INTEGER DEFAULT 0,
    last_used_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batch_jobs (
    batch_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    total INTEGER DEFAULT 0,
    done INTEGER DEFAULT 0,
    current_group INTEGER DEFAULT 0,
    results TEXT DEFAULT '[]',
    error TEXT,
    created_at TEXT,
    finished_at TEXT,
    stop_requested INTEGER DEFAULT 0,
    mode TEXT DEFAULT 'generate'
);
CREATE TABLE IF NOT EXISTS companion_personas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source TEXT DEFAULT '',
    relationship TEXT DEFAULT '恋人',
    gender TEXT DEFAULT '',
    personality TEXT DEFAULT '',
    tone TEXT DEFAULT '',
    appearance TEXT DEFAULT '',
    catchphrases TEXT DEFAULT '',
    avatar TEXT DEFAULT '',
    config_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS companion_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id INTEGER NOT NULL,
    title TEXT DEFAULT '新会话',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS companion_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    persona_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    emotion TEXT DEFAULT '',
    image_path TEXT DEFAULT '',
    image_description TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS companion_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding TEXT DEFAULT '',
    importance INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS companion_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS lora_protections (
    name TEXT PRIMARY KEY,
    source TEXT DEFAULT 'loras',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS train_jobs (
    job_id TEXT PRIMARY KEY,
    output_name TEXT,
    status TEXT,
    dit TEXT,
    resolution INTEGER,
    repeats INTEGER,
    batch_size INTEGER,
    network_dim INTEGER,
    network_alpha INTEGER,
    learning_rate REAL,
    epochs INTEGER,
    save_every INTEGER,
    max_steps INTEGER,
    auto_convert INTEGER DEFAULT 0,
    error TEXT,
    steps_done INTEGER,
    steps_total INTEGER,
    latest_loss REAL,
    min_loss REAL,
    best_step INTEGER,
    created_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS video_scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_input TEXT NOT NULL,
    script_json TEXT NOT NULL DEFAULT '{}',
    model TEXT DEFAULT '',
    content_limited INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS video_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    script_id INTEGER,
    keyframe_name TEXT,
    video_name TEXT,
    prompt TEXT DEFAULT '',
    negative_prompt TEXT DEFAULT '',
    model TEXT DEFAULT '',
    loras TEXT DEFAULT '[]',
    seed INTEGER,
    width INTEGER,
    height INTEGER,
    frames INTEGER,
    fps INTEGER DEFAULT 24,
    status TEXT DEFAULT 'running',
    error TEXT,
    duration_seconds REAL,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS character_appearance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_name TEXT NOT NULL COLLATE NOCASE,
    work TEXT NOT NULL DEFAULT '' COLLATE NOCASE,
    appearance_tags TEXT NOT NULL DEFAULT '',
    clothing_tags TEXT NOT NULL DEFAULT '',
    full_prompt TEXT NOT NULL DEFAULT '',
    confidence REAL DEFAULT 0,
    source TEXT DEFAULT 'llm',
    note TEXT DEFAULT '',
    corrected INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(character_name, work)
);
CREATE TABLE IF NOT EXISTS character_appearance_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preset_id TEXT NOT NULL,
    name TEXT NOT NULL,
    work TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '自由备注',
    appearance_tags TEXT NOT NULL DEFAULT '[]',
    clothing_tags TEXT NOT NULL DEFAULT '[]',
            expression_tags TEXT NOT NULL DEFAULT '[]',
            outfit_id TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'user',
    version INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(preset_id, version)
);
CREATE INDEX IF NOT EXISTS idx_agent_created ON agent_chat_records(created_at);
CREATE INDEX IF NOT EXISTS idx_draw_started ON draw_records(started_at);
CREATE INDEX IF NOT EXISTS idx_prompt_started ON prompt_agent_records(started_at);
CREATE INDEX IF NOT EXISTS idx_prompt_sets_created ON prompt_sets(created_at);
CREATE INDEX IF NOT EXISTS idx_companion_sessions_persona ON companion_sessions(persona_id);
CREATE INDEX IF NOT EXISTS idx_companion_messages_session ON companion_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_companion_memories_persona ON companion_memories(persona_id);
CREATE INDEX IF NOT EXISTS idx_character_appearance_presets_lookup
    ON character_appearance_presets(preset_id, version);
CREATE INDEX IF NOT EXISTS idx_character_appearance_presets_filter
    ON character_appearance_presets(category, source, enabled);
"""

_TABLES = {
    "agent": "agent_chat_records",
    "draw": "draw_records",
    "prompt": "prompt_agent_records",
    "video": "video_records",
}

# SQLite 版本化迁移：新库与旧库都从 user_version=0 开始依次执行。
SCHEMA_VERSION = 31


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migration_001_compat(conn: sqlite3.Connection) -> None:
    """迁移 1：旧库补齐此前以散装 ensure 方式添加的列（幂等）。"""
    draw_columns = _table_columns(conn, "draw_records")
    if "loras_json" not in draw_columns:
        conn.execute("ALTER TABLE draw_records ADD COLUMN loras_json TEXT DEFAULT '[]'")
    if "model" not in draw_columns:
        conn.execute("ALTER TABLE draw_records ADD COLUMN model TEXT")
    if "batch_id" not in draw_columns:
        conn.execute("ALTER TABLE draw_records ADD COLUMN batch_id TEXT")
    if "group_index" not in draw_columns:
        conn.execute("ALTER TABLE draw_records ADD COLUMN group_index INTEGER")

    persona_columns = _table_columns(conn, "companion_personas")
    if "gender" not in persona_columns:
        conn.execute("ALTER TABLE companion_personas ADD COLUMN gender TEXT DEFAULT ''")
    if "appearance" not in persona_columns:
        conn.execute("ALTER TABLE companion_personas ADD COLUMN appearance TEXT DEFAULT ''")

    message_columns = _table_columns(conn, "companion_messages")
    if "image_path" not in message_columns:
        conn.execute("ALTER TABLE companion_messages ADD COLUMN image_path TEXT DEFAULT ''")
    if "image_description" not in message_columns:
        conn.execute("ALTER TABLE companion_messages ADD COLUMN image_description TEXT DEFAULT ''")


def _migration_002_background_jobs(conn: sqlite3.Connection) -> None:
    """迁移 2：统一任务注册表持久化表。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS background_jobs (
            job_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            total INTEGER DEFAULT 0,
            done INTEGER DEFAULT 0,
            current TEXT DEFAULT '',
            error TEXT,
            stop_requested INTEGER DEFAULT 0,
            payload TEXT DEFAULT '{}',
            created_at TEXT,
            updated_at TEXT,
            finished_at TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_background_jobs_kind_status ON background_jobs(kind, status)"
    )


def _migration_003_video(conn: sqlite3.Connection) -> None:
    """迁移 3：AI 视频剧本与成片业务表（任务状态仍走 background_jobs）。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_scripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_input TEXT NOT NULL,
            script_json TEXT NOT NULL DEFAULT '{}',
            model TEXT DEFAULT '',
            content_limited INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT,
            script_id INTEGER,
            keyframe_name TEXT,
            video_name TEXT,
            prompt TEXT DEFAULT '',
            negative_prompt TEXT DEFAULT '',
            model TEXT DEFAULT '',
            loras TEXT DEFAULT '[]',
            seed INTEGER,
            width INTEGER,
            height INTEGER,
            frames INTEGER,
            fps INTEGER DEFAULT 24,
            status TEXT DEFAULT 'running',
            error TEXT,
            duration_seconds REAL,
            created_at TEXT NOT NULL,
            finished_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_video_records_job ON video_records(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_video_records_created ON video_records(created_at)")


def _migration_004_prompt_set_composition(conn: sqlite3.Connection) -> None:
    """迁移 4：提示词集保存可重算的预设组合元数据。"""
    columns = _table_columns(conn, "prompt_sets")
    if "composition_json" not in columns:
        conn.execute("ALTER TABLE prompt_sets ADD COLUMN composition_json TEXT DEFAULT '{}'")


def _migration_005_preset_asset_workshop(conn: sqlite3.Connection) -> None:
    """迁移 5：预设缩略图源图、候选、正式版本和批量任务明细。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preset_asset_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preset_asset_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            preset_type TEXT NOT NULL,
            preset_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            source_kind TEXT NOT NULL,
            managed_path TEXT NOT NULL,
            mime_type TEXT NOT NULL DEFAULT '',
            width INTEGER NOT NULL DEFAULT 0,
            height INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_preset_asset_sources_lookup "
        "ON preset_asset_sources(preset_type, preset_id, active, revision)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preset_asset_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT,
            preset_type TEXT NOT NULL,
            preset_id TEXT NOT NULL,
            source_revision_id INTEGER,
            generation_mode TEXT NOT NULL,
            status TEXT NOT NULL,
            original_path TEXT,
            preview_path TEXT,
            thumbnail_path TEXT,
            params_json TEXT NOT NULL DEFAULT '{}',
            prompt_positive TEXT NOT NULL DEFAULT '',
            prompt_negative TEXT NOT NULL DEFAULT '',
            template_version TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            loras_json TEXT NOT NULL DEFAULT '[]',
            seed INTEGER,
            generation_width INTEGER NOT NULL DEFAULT 0,
            generation_height INTEGER NOT NULL DEFAULT 0,
            output_width INTEGER NOT NULL DEFAULT 0,
            output_height INTEGER NOT NULL DEFAULT 0,
            crop_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_preset_asset_candidates_lookup "
        "ON preset_asset_candidates(preset_type, preset_id, status, id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_preset_asset_candidates_job "
        "ON preset_asset_candidates(job_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preset_asset_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            preset_type TEXT NOT NULL,
            preset_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            candidate_id INTEGER,
            public_path TEXT NOT NULL,
            dist_path TEXT NOT NULL,
            mime_type TEXT NOT NULL DEFAULT '',
            width INTEGER NOT NULL DEFAULT 0,
            height INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(preset_type, preset_id, version)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_preset_asset_versions_lookup "
        "ON preset_asset_versions(preset_type, preset_id, active, version)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preset_asset_job_items (
            job_id TEXT NOT NULL,
            item_index INTEGER NOT NULL,
            preset_type TEXT NOT NULL,
            preset_id TEXT NOT NULL,
            candidate_id INTEGER,
            status TEXT NOT NULL,
            params_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(job_id, item_index)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_preset_asset_job_items_status "
        "ON preset_asset_job_items(job_id, status)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preset_asset_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event TEXT NOT NULL,
            preset_type TEXT NOT NULL DEFAULT '',
            preset_id TEXT NOT NULL DEFAULT '',
            candidate_id INTEGER,
            job_id TEXT,
            detail_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_preset_asset_audit_lookup "
        "ON preset_asset_audit(preset_type, preset_id, id)"
    )


def _migration_006_prompt_document(conn: sqlite3.Connection) -> None:
    """迁移 6：结构化提示词快照和本地角色外观预设。"""
    if "prompt_document_json" not in _table_columns(conn, "prompt_sets"):
        conn.execute(
            "ALTER TABLE prompt_sets ADD COLUMN prompt_document_json TEXT DEFAULT '{}'"
        )
    if "prompt_document_json" not in _table_columns(conn, "draw_records"):
        conn.execute(
            "ALTER TABLE draw_records ADD COLUMN prompt_document_json TEXT DEFAULT '{}'"
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS character_appearance_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            preset_id TEXT NOT NULL,
            name TEXT NOT NULL,
            work TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '自由备注',
            appearance_tags TEXT NOT NULL DEFAULT '[]',
            clothing_tags TEXT NOT NULL DEFAULT '[]',
    expression_tags TEXT NOT NULL DEFAULT '[]',
    outfit_id TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'user',
            version INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(preset_id, version)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_character_appearance_presets_lookup "
        "ON character_appearance_presets(preset_id, version)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_character_appearance_presets_filter "
        "ON character_appearance_presets(category, source, enabled)"
    )
    _seed_builtin_appearance_presets(conn)


def _seed_builtin_appearance_presets(conn: sqlite3.Connection) -> None:
    """写入不指向具体作品角色的通用外观模板。"""
    builtins = (
        (
            "builtin_soft_anime_girl",
            "柔和动漫少女",
            "",
            "脸部",
            ["soft youthful face", "delicate features"],
            ["simple pastel outfit"],
            ["gentle smile"],
        ),
        (
            "builtin_elegant_adult_woman",
            "优雅成熟女性",
            "",
            "体型",
            ["elegant adult woman", "slender mature figure"],
            ["tailored dress"],
            ["calm confident expression"],
        ),
        (
            "builtin_youthful_boy",
            "清爽少年",
            "",
            "脸部",
            ["youthful boyish face", "clear eyes"],
            ["casual shirt"],
            ["bright neutral expression"],
        ),
        (
            "builtin_masculine_man",
            "沉稳成年男性",
            "",
            "体型",
            ["masculine adult man", "broad shoulders"],
            ["dark fitted jacket"],
            ["steady expression"],
        ),
        (
            "builtin_androgynous",
            "中性气质",
            "",
            "脸部",
            ["androgynous beauty", "balanced facial features"],
            ["minimal monochrome outfit"],
            ["ambiguous calm expression"],
        ),
        (
            "builtin_fantasy_humanoid",
            "幻想系人形",
            "",
            "身体特征与配饰",
            ["fantasy humanoid features", "subtle nonhuman traits"],
            ["layered fantasy clothing"],
            ["mysterious expression"],
        ),
    )
    now = now_iso()
    for preset_id, name, work, category, appearance, clothing, expression in builtins:
        conn.execute(
            """
            INSERT OR IGNORE INTO character_appearance_presets (
                preset_id, name, work, category, appearance_tags, clothing_tags,
                expression_tags, note, source, version, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'builtin', 1, 1, ?, ?)
            """,
            (
                preset_id,
                name,
                work,
                category,
                json.dumps(appearance, ensure_ascii=False),
                json.dumps(clothing, ensure_ascii=False),
                json.dumps(expression, ensure_ascii=False),
                "本地通用模板，不包含具体作品角色设定。",
                now,
                now,
            ),
        )


def _migration_007_builtin_character_presets(conn: sqlite3.Connection) -> None:
    """迁移 7：写入作品角色的身份与固有外貌预设。"""
    _seed_builtin_character_presets(conn)


def _migration_008_character_preset_expansion(conn: sqlite3.Connection) -> None:
    """迁移 8：补充鸣潮、绝区零与崩坏3角色预设。"""
    _seed_builtin_character_presets(conn)


def _migration_009_girls_frontline_2_character_expansion(conn: sqlite3.Connection) -> None:
    """迁移 9：录入《少女前线2》角色并修正月下誓约显示名。"""
    _seed_builtin_character_presets(conn)
    conn.execute(
        """
        UPDATE character_appearance_presets
        SET name = ?, updated_at = ?
        WHERE preset_id = ?
        """,
        (
            "月下誓约-予爱以心",
            now_iso(),
            "builtin_character_honkai_impact_3rd_big_luna",
        ),
    )


def _migration_010_character_preset_expansion(conn: sqlite3.Connection) -> None:
    """迁移 10：补充用户确认的 51 名作品角色与默认服装。"""
    _seed_builtin_character_presets(conn)


def _migration_011_preset_asset_queue_recovery(conn: sqlite3.Connection) -> None:
    """迁移 11：预设任务提交幂等、恢复元数据与重试状态。"""
    item_columns = _table_columns(conn, "preset_asset_job_items")
    if "attempt_count" not in item_columns:
        conn.execute(
            "ALTER TABLE preset_asset_job_items "
            "ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
        )
    if "next_retry_at" not in item_columns:
        conn.execute(
            "ALTER TABLE preset_asset_job_items ADD COLUMN next_retry_at TEXT"
        )
    if "retry_backoff_seconds" not in item_columns:
        conn.execute(
            "ALTER TABLE preset_asset_job_items "
            "ADD COLUMN retry_backoff_seconds INTEGER NOT NULL DEFAULT 0"
        )
    if "last_error_code" not in item_columns:
        conn.execute(
            "ALTER TABLE preset_asset_job_items ADD COLUMN last_error_code TEXT"
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preset_asset_job_requests (
            job_id TEXT PRIMARY KEY,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_preset_asset_job_requests_created "
        "ON preset_asset_job_requests(created_at)"
    )


def _migration_012_preset_asset_write_leases(conn: sqlite3.Connection) -> None:
    """迁移 12：为正式素材采纳与回滚提供跨进程唯一写入租约。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS preset_asset_write_leases (
            preset_type TEXT NOT NULL,
            preset_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            candidate_id INTEGER,
            target_version_id INTEGER,
            expected_revision INTEGER NOT NULL,
            owner_token TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            expires_at REAL NOT NULL,
            PRIMARY KEY (preset_type, preset_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_preset_asset_write_leases_expiry "
        "ON preset_asset_write_leases(expires_at)"
    )


def _migration_013_task_resources_and_activity(conn: sqlite3.Connection) -> None:
    """迁移 13：通用任务资源租约与活动审计事件。"""
    columns = _table_columns(conn, "background_jobs")
    if "resources_json" not in columns:
        conn.execute(
            "ALTER TABLE background_jobs ADD COLUMN resources_json TEXT NOT NULL DEFAULT '[]'"
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_resource_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_key TEXT NOT NULL,
            job_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            mode TEXT NOT NULL,
            owner_token TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            expires_at REAL NOT NULL,
            released_at TEXT,
            release_reason TEXT
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_task_resource_claims_active_job "
        "ON task_resource_claims(job_id, resource_key) WHERE released_at IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_resource_claims_active_resource "
        "ON task_resource_claims(resource_key, expires_at) WHERE released_at IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_resource_claims_expiry "
        "ON task_resource_claims(expires_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_events (
            event_id TEXT PRIMARY KEY,
            occurred_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            module TEXT NOT NULL DEFAULT '',
            actor_type TEXT NOT NULL DEFAULT 'system',
            job_id TEXT,
            kind TEXT,
            severity TEXT NOT NULL DEFAULT 'info',
            summary TEXT NOT NULL DEFAULT '',
            correlation_id TEXT,
            payload TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_events_occurred "
        "ON activity_events(occurred_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_events_job "
        "ON activity_events(job_id, occurred_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_events_type "
        "ON activity_events(event_type, occurred_at DESC)"
    )


def _seed_builtin_character_presets(conn: sqlite3.Connection) -> None:
    """默认服装独立维护在服装预设目录中。"""
    if "outfit_id" not in _table_columns(conn, "character_appearance_presets"):
        conn.execute(
            "ALTER TABLE character_appearance_presets "
            "ADD COLUMN outfit_id TEXT NOT NULL DEFAULT ''"
        )
    now = now_iso()
    for item in character_presets.BUILTIN_CHARACTER_PRESETS:
        conn.execute(
            """
            INSERT OR IGNORE INTO character_appearance_presets (
                preset_id, name, work, category, appearance_tags, clothing_tags,
                expression_tags, outfit_id, note, source, version, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, '角色', ?, '[]', '[]', ?, ?, 'builtin', 1, 1, ?, ?)
            """,
            (
                item["preset_id"],
                item["name"],
                item["work"],
                json.dumps(item["appearance_tags"], ensure_ascii=False),
                item["outfit_id"],
                "作品角色身份与固有外貌；默认服装见角色服装预设。",
                now,
                now,
            ),
        )


def _migration_014_character_prompt_batches(conn: sqlite3.Connection) -> None:
    """Seed batches 01-02 and version-upgrade revised built-in presets."""
    _seed_builtin_character_presets(conn)
    now = now_iso()
    for preset_id in character_prompt_presets.REVISED_PRESET_IDS:
        item = character_prompt_presets.CHARACTER_PROMPT_PRESETS_BY_ID[preset_id]
        current = conn.execute(
            """
            SELECT version, name, work, appearance_tags
            FROM character_appearance_presets
            WHERE preset_id = ?
            ORDER BY version DESC LIMIT 1
            """,
            (preset_id,),
        ).fetchone()
        if not current:
            continue
        appearance_tags = json.dumps(item["appearance_tags"], ensure_ascii=False)
        if (
            current["name"] == item["name"]
            and current["work"] == item["work"]
            and current["appearance_tags"] == appearance_tags
        ):
            continue
        conn.execute(
            """
            INSERT INTO character_appearance_presets (
                preset_id, name, work, category, appearance_tags, clothing_tags,
                expression_tags, outfit_id, note, source, version, enabled,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, '[]', '[]', ?, ?, 'builtin', ?, 1, ?, ?)
            """,
            (
                preset_id,
                item["name"],
                item["work"],
                item["category"],
                appearance_tags,
                item["outfit_id"],
                "Character prompt batch 01-02 confirmed revision; default outfit is stored separately.",
                int(current["version"]) + 1,
                now,
                now,
            ),
        )


def _migration_015_character_prompt_batch_03(conn: sqlite3.Connection) -> None:
    """Seed the confirmed Azur Lane character prompt batch 03."""
    _seed_builtin_character_presets(conn)


def _migration_016_character_prompt_batch_04(conn: sqlite3.Connection) -> None:
    """Seed the confirmed Azur Lane character prompt batch 04."""
    _seed_builtin_character_presets(conn)

def _migration_017_character_prompt_batch_05(conn: sqlite3.Connection) -> None:
    """Seed the confirmed Azur Lane character prompt batch 05."""
    _seed_builtin_character_presets(conn)


def _migration_018_character_prompt_batch_06(conn: sqlite3.Connection) -> None:
    """Seed the confirmed Azur Lane character prompt batch 06."""
    _seed_builtin_character_presets(conn)


def _migration_019_character_prompt_batch_07(conn: sqlite3.Connection) -> None:
    """Seed the confirmed Azur Lane and Arknights character prompt batch 07."""
    _seed_builtin_character_presets(conn)


def _migration_020_character_prompt_batch_08(conn: sqlite3.Connection) -> None:
    """Seed the confirmed Arknights and Wuthering Waves character prompt batch 08."""
    _seed_builtin_character_presets(conn)


def _migration_021_character_prompt_batch_09(conn: sqlite3.Connection) -> None:
    """Seed the confirmed Wuthering Waves character prompt batch 09."""
    _seed_builtin_character_presets(conn)


def _migration_022_inpaint(conn: sqlite3.Connection) -> None:
    """Add local-inpaint lineage fields and batch job mode."""
    draw_columns = _table_columns(conn, "draw_records")
    additions = {
        "edit_mode": "TEXT DEFAULT 'generate'",
        "source_record_id": "INTEGER",
        "source_image_path": "TEXT",
        "mask_image_path": "TEXT",
        "masked_prompt": "TEXT",
        "inpaint_denoise": "REAL",
        "edit_params_json": "TEXT DEFAULT '{}'",
    }
    for name, definition in additions.items():
        if name not in draw_columns:
            conn.execute(f"ALTER TABLE draw_records ADD COLUMN {name} {definition}")

    batch_columns = _table_columns(conn, "batch_jobs")
    if "mode" not in batch_columns:
        conn.execute("ALTER TABLE batch_jobs ADD COLUMN mode TEXT DEFAULT 'generate'")


def _migration_023_fgo_character_presets(conn: sqlite3.Connection) -> None:
    """Seed the confirmed FGO character appearances and breakthrough forms."""
    _seed_builtin_character_presets(conn)


def _migration_024_lady_avalon_first_ascension(conn: sqlite3.Connection) -> None:
    """Replace Lady Avalon's final-ascension preset with the confirmed A1 form."""
    conn.execute(
        """
        DELETE FROM character_appearance_presets
        WHERE preset_id = 'builtin_character_fgo_2800300_pretender_a4'
          AND source = 'builtin'
        """
    )
    _seed_builtin_character_presets(conn)


def _migration_025_lady_avalon_second_ascension(conn: sqlite3.Connection) -> None:
    """Add Lady Avalon's second-ascension preset alongside A1."""
    _seed_builtin_character_presets(conn)


def _migration_026_kiyohime_third_ascension(conn: sqlite3.Connection) -> None:
    """Add third-ascension forms for Kiyohime Lancer and Berserker."""
    _seed_builtin_character_presets(conn)


def _migration_027_genshin_character_presets(conn: sqlite3.Connection) -> None:
    """Seed the confirmed Genshin character presets and default outfits."""
    _seed_builtin_character_presets(conn)


def _migration_028_columbina_hair_color(conn: sqlite3.Connection) -> None:
    """Correct Columbina's hair tags to match the official default illustration."""
    preset_id = "builtin_character_genshin_columbina"
    item = character_presets.CHARACTER_PRESETS_BY_ID[preset_id]
    current = conn.execute(
        """
        SELECT version, appearance_tags
        FROM character_appearance_presets
        WHERE preset_id = ?
        ORDER BY version DESC LIMIT 1
        """,
        (preset_id,),
    ).fetchone()
    appearance_tags = json.dumps(item["appearance_tags"], ensure_ascii=False)
    if not current:
        _seed_builtin_character_presets(conn)
        return
    if current["appearance_tags"] == appearance_tags:
        return
    now = now_iso()
    conn.execute(
        """
        INSERT INTO character_appearance_presets (
            preset_id, name, work, category, appearance_tags, clothing_tags,
            expression_tags, note, source, version, enabled, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, '[]', '[]', ?, 'builtin', ?, 1, ?, ?)
        """,
        (
            preset_id,
            item["name"],
            item["work"],
            item["category"],
            appearance_tags,
            "Hair color corrected against the current official default illustration.",
            int(current["version"]) + 1,
            now,
            now,
        ),
    )


def _migration_029_character_outfit_links(conn: sqlite3.Connection) -> None:
    """Separate character identity from default outfits and persist the link."""
    if "outfit_id" not in _table_columns(conn, "character_appearance_presets"):
        conn.execute(
            "ALTER TABLE character_appearance_presets "
            "ADD COLUMN outfit_id TEXT NOT NULL DEFAULT ''"
        )
    _seed_builtin_character_presets(conn)
    now = now_iso()
    for item in character_presets.BUILTIN_CHARACTER_PRESETS:
        appearance_tags = json.dumps(item["appearance_tags"], ensure_ascii=False)
        current = conn.execute(
            """
            SELECT version, appearance_tags, clothing_tags, outfit_id
            FROM character_appearance_presets
            WHERE preset_id = ? AND source = 'builtin'
            ORDER BY version DESC LIMIT 1
            """,
            (item["preset_id"],),
        ).fetchone()
        if (
            current
            and current["appearance_tags"] == appearance_tags
            and current["clothing_tags"] == "[]"
            and current["outfit_id"] == item["outfit_id"]
        ):
            continue
        next_version = int(current["version"]) + 1 if current else 1
        conn.execute(
            """
            INSERT INTO character_appearance_presets (
                preset_id, name, work, category, appearance_tags, clothing_tags,
                expression_tags, outfit_id, note, source, version, enabled,
                created_at, updated_at
            ) VALUES (?, ?, ?, '角色', ?, '[]', '[]', ?, ?, 'builtin', ?, 1, ?, ?)
            """,
            (
                item["preset_id"],
                item["name"],
                item["work"],
                appearance_tags,
                item["outfit_id"],
                "角色身份与默认服装已拆分；默认服装由独立 outfit_id 关联。",
                next_version,
                now,
                now,
            ),
        )


def _migration_030_builtin_character_outfit_resync(conn: sqlite3.Connection) -> None:
    """Apply the separation rules to every built-in character catalog entry."""
    _migration_029_character_outfit_links(conn)


def _migration_031_character_visual_corrections(conn: sqlite3.Connection) -> None:
    """Correct Kiyohime horns/eye colors and Virtuosa's eye description."""
    _migration_029_character_outfit_links(conn)


_MIGRATIONS = (
    _migration_001_compat,
    _migration_002_background_jobs,
    _migration_003_video,
    _migration_004_prompt_set_composition,
    _migration_005_preset_asset_workshop,
    _migration_006_prompt_document,
    _migration_007_builtin_character_presets,
    _migration_008_character_preset_expansion,
    _migration_009_girls_frontline_2_character_expansion,
    _migration_010_character_preset_expansion,
    _migration_011_preset_asset_queue_recovery,
    _migration_012_preset_asset_write_leases,
    _migration_013_task_resources_and_activity,
    _migration_014_character_prompt_batches,
    _migration_015_character_prompt_batch_03,
    _migration_016_character_prompt_batch_04,
    _migration_017_character_prompt_batch_05,
    _migration_018_character_prompt_batch_06,
    _migration_019_character_prompt_batch_07,
    _migration_020_character_prompt_batch_08,
    _migration_021_character_prompt_batch_09,
    _migration_022_inpaint,
    _migration_023_fgo_character_presets,
    _migration_024_lady_avalon_first_ascension,
    _migration_025_lady_avalon_second_ascension,
    _migration_026_kiyohime_third_ascension,
    _migration_027_genshin_character_presets,
    _migration_028_columbina_hair_color,
    _migration_029_character_outfit_links,
    _migration_030_builtin_character_outfit_resync,
    _migration_031_character_visual_corrections,
)


def run_migrations() -> None:
    """把 user_version 升到 SCHEMA_VERSION，逐版本执行迁移。"""
    with get_connection() as conn:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        while version < SCHEMA_VERSION:
            _MIGRATIONS[version](conn)
            version += 1
            conn.execute(f"PRAGMA user_version = {version}")


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(_SCHEMA)
    run_migrations()


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


def list_agent_sessions(limit: int = 100) -> list[dict]:
    """招聘 Agent 会话列表：最近消息时间、最后提问、消息数。"""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                t.session_id,
                MAX(t.created_at) AS last_at,
                COUNT(*) AS message_count,
                (
                    SELECT content FROM agent_chat_records t2
                    WHERE t2.session_id = t.session_id AND t2.sender = 'user'
                    ORDER BY t2.id DESC LIMIT 1
                ) AS last_message
            FROM agent_chat_records t
            GROUP BY t.session_id
            ORDER BY last_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_agent_messages(session_id: str, limit: int = 100) -> list[dict]:
    """按时间正序返回招聘 Agent 会话消息。"""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, sender, content, source, retrieval_score, created_at
            FROM agent_chat_records
            WHERE session_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def delete_agent_session(session_id: str) -> None:
    """删除招聘 Agent 会话全部消息。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM agent_chat_records WHERE session_id = ?", (session_id,))


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
    loras: list[str] | None = None,
    batch_id: str | None = None,
    group_index: int | None = None,
    prompt_document_json: str = "{}",
    edit_mode: str = "generate",
    source_record_id: int | None = None,
    source_image_path: str | None = None,
    mask_image_path: str | None = None,
    masked_prompt: str | None = None,
    inpaint_denoise: float | None = None,
    edit_params_json: str = "{}",
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO draw_records (
                started_at, batch_id, group_index, prompt, prompt_translation, negative_prompt, negative_translation,
                prompt_document_json, width, height, steps, cfg, loras_json, model,
                lora_anima_turbo, lora_high_contrast, status,
                edit_mode, source_record_id, source_image_path, mask_image_path,
                masked_prompt, inpaint_denoise, edit_params_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                batch_id,
                group_index,
                prompt,
                prompt_translation,
                negative_prompt,
                negative_translation,
                prompt_document_json or "{}",
                width,
                height,
                steps,
                cfg,
                json.dumps([name if name.endswith(".safetensors") else name + ".safetensors" for name in (loras or [])], ensure_ascii=False),
                model,
                1 if lora_anima_turbo else 0,
                1 if lora_high_contrast else 0,
                "running",
                edit_mode,
                source_record_id,
                source_image_path,
                mask_image_path,
                masked_prompt,
                inpaint_denoise,
                edit_params_json or "{}",
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
    page_size: int = config.QUERY_RECORDS_PAGE_SIZE_DEFAULT,
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
    limit: int = config.QUERY_RECORD_EXPORT_LIMIT_DEFAULT,
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


def query_prompt_sets(
    keyword: str | None = None,
    prompt_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = config.QUERY_PROMPT_SET_PAGE_SIZE_DEFAULT,
) -> dict:
    """按关键词/类型/时间范围分页查询提示词集。"""
    clauses = []
    params: list[str] = []
    if keyword:
        like = f"%{keyword}%"
        clauses.append("(name LIKE ? OR content LIKE ? OR tags LIKE ?)")
        params += [like, like, like]
    if prompt_type:
        clauses.append("type = ?")
        params.append(prompt_type)
    if date_from:
        clauses.append("substr(created_at, 1, 10) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("substr(created_at, 1, 10) <= ?")
        params.append(date_to)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM prompt_sets {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM prompt_sets {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [dict(row) for row in rows],
    }


def get_prompt_set(prompt_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM prompt_sets WHERE id = ?", (prompt_id,)).fetchone()
    return dict(row) if row else None


def prompt_set_name_exists(name: str, exclude_id: int | None = None) -> bool:
    with get_connection() as conn:
        if exclude_id is None:
            row = conn.execute("SELECT 1 FROM prompt_sets WHERE name = ? LIMIT 1", (name,)).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM prompt_sets WHERE name = ? AND id != ? LIMIT 1",
                (name, exclude_id),
            ).fetchone()
    return row is not None


def insert_prompt_set(
    name: str,
    prompt_type: str,
    content: str,
    translation: str = "",
    description: str = "",
    tags: str = "",
    composition_json: str = "{}",
    prompt_document_json: str = "{}",
) -> int:
    timestamp = now_iso()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO prompt_sets (
                name, type, content, translation, description, tags,
                composition_json, prompt_document_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                prompt_type,
                content,
                translation,
                description,
                tags,
                composition_json or "{}",
                prompt_document_json or "{}",
                timestamp,
                timestamp,
            ),
        )
        return int(cursor.lastrowid)


def update_prompt_set(
    prompt_id: int,
    name: str,
    prompt_type: str,
    content: str,
    translation: str = "",
    description: str = "",
    tags: str = "",
    composition_json: str = "{}",
    prompt_document_json: str = "{}",
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE prompt_sets
            SET name = ?, type = ?, content = ?, translation = ?, description = ?, tags = ?,
                composition_json = ?, prompt_document_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                name,
                prompt_type,
                content,
                translation,
                description,
                tags,
                composition_json or "{}",
                prompt_document_json or "{}",
                now_iso(),
                prompt_id,
            ),
        )


def delete_prompt_set(prompt_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM prompt_sets WHERE id = ?", (prompt_id,))


def touch_prompt_set(prompt_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE prompt_sets SET use_count = use_count + 1, last_used_at = ? WHERE id = ?",
            (now_iso(), prompt_id),
        )


def update_prompt_sets_type(prompt_ids: list[int], prompt_type: str) -> int:
    """批量更新提示词集类型，返回更新条数。"""
    if not prompt_ids:
        return 0
    placeholders = ", ".join("?" for _ in prompt_ids)
    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE prompt_sets SET type = ?, updated_at = ? WHERE id IN ({placeholders})",
            [prompt_type, now_iso(), *prompt_ids],
        )
        return int(cursor.rowcount)


def query_draw_images(
    date_from: str | None = None,
    date_to: str | None = None,
    model: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    batch_id: str | None = None,
    page: int = 1,
    page_size: int = config.QUERY_IMAGE_LIBRARY_PAGE_SIZE_DEFAULT,
) -> dict:
    """分页查询有图片的绘画记录。"""
    clauses = ["image_url IS NOT NULL"]
    params: list[str] = []
    if date_from:
        clauses.append("substr(started_at, 1, 10) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("substr(started_at, 1, 10) <= ?")
        params.append(date_to)
    if model:
        clauses.append("model = ?")
        params.append(model)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if keyword:
        clauses.append("(prompt LIKE ? OR image_url LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if batch_id:
        clauses.append("batch_id = ?")
        params.append(batch_id)
    where = f"WHERE {' AND '.join(clauses)}"
    with get_connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM draw_records {where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM draw_records {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [page_size, (page - 1) * page_size],
        ).fetchall()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [dict(row) for row in rows],
    }


def list_draw_batches(
    date_from: str | None = None,
    date_to: str | None = None,
    model: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
) -> list[dict]:
    """图片库按批次分组统计。"""
    clauses = ["image_url IS NOT NULL"]
    params: list[str] = []
    if date_from:
        clauses.append("substr(started_at, 1, 10) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("substr(started_at, 1, 10) <= ?")
        params.append(date_to)
    if model:
        clauses.append("model = ?")
        params.append(model)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if keyword:
        clauses.append("(prompt LIKE ? OR image_url LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    where = f"WHERE {' AND '.join(clauses)}"
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                batch_id,
                COUNT(*) AS count,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_count,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_count,
                MAX(started_at) AS last_at,
                MAX(CASE WHEN image_url IS NOT NULL THEN image_url END) AS image_url
            FROM draw_records
            {where}
            GROUP BY batch_id
            ORDER BY last_at DESC
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def get_draw_image(record_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM draw_records WHERE id = ?", (record_id,)).fetchone()
    return dict(row) if row else None


def delete_draw_image(record_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM draw_records WHERE id = ?", (record_id,))


def cleanup_records_before(days: int) -> dict[str, int]:
    """清理指定天数之前的历史记录，仅删除数据库行，不删除图片文件。"""
    cutoff = (datetime.now().astimezone() - timedelta(days=days)).isoformat(timespec="seconds")
    counts: dict[str, int] = {}
    with get_connection() as conn:
        for key, table, column in (
            ("agent", "agent_chat_records", "created_at"),
            ("draw", "draw_records", "started_at"),
            ("prompt", "prompt_agent_records", "started_at"),
        ):
            cursor = conn.execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))
            counts[key] = cursor.rowcount or 0
    return counts


def _draw_lora_names(row: sqlite3.Row) -> list[str]:
    names: list[str] = []
    try:
        raw = json.loads(row["loras_json"] or "[]")
    except (json.JSONDecodeError, TypeError):
        raw = []
    if isinstance(raw, list):
        for item in raw:
            name = str(item or "").strip()
            if not name:
                continue
            if name.endswith(".safetensors"):
                name = name[: -len(".safetensors")]
            if name not in names:
                names.append(name)
    if row["lora_anima_turbo"] and "anima-turbo-lora-v0.2" not in names:
        names.append("anima-turbo-lora-v0.2")
    if row["lora_high_contrast"] and "high-contrast aesthetic" not in names:
        names.append("high-contrast aesthetic")
    return names


def draw_stats(
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """聚合绘画记录：状态/模型/尺寸/LoRA 分布与每日趋势。"""
    clauses: list[str] = []
    params: list[str] = []
    if date_from:
        clauses.append("substr(started_at, 1, 10) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("substr(started_at, 1, 10) <= ?")
        params.append(date_to)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT started_at, duration_seconds, model, width, height, status,
                   loras_json, lora_anima_turbo, lora_high_contrast
            FROM draw_records
            {where}
            """,
            params,
        ).fetchall()
    status_counts: dict[str, int] = {}
    model_counts: dict[str, int] = {}
    size_counts: dict[str, int] = {}
    lora_counts: dict[str, int] = {}
    combo_counts: dict[str, int] = {}
    daily: dict[str, dict] = {}
    duration_total = 0.0
    duration_count = 0
    for row in rows:
        status = row["status"] or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        model = row["model"] or "unknown"
        model_counts[model] = model_counts.get(model, 0) + 1
        size = f"{row['width'] or 0}x{row['height'] or 0}"
        size_counts[size] = size_counts.get(size, 0) + 1
        loras = _draw_lora_names(row)
        for name in loras:
            lora_counts[name] = lora_counts.get(name, 0) + 1
        if loras:
            combo = " + ".join(loras)
            combo_counts[combo] = combo_counts.get(combo, 0) + 1
        day = str(row["started_at"] or "")[:10]
        if day:
            entry = daily.setdefault(day, {"count": 0, "duration_total": 0.0, "duration_count": 0})
            entry["count"] += 1
            if row["duration_seconds"]:
                entry["duration_total"] += float(row["duration_seconds"])
                entry["duration_count"] += 1
                duration_total += float(row["duration_seconds"])
                duration_count += 1
    daily_list = [
        {
            "date": day,
            "count": value["count"],
            "avg_duration": round(value["duration_total"] / value["duration_count"], 2) if value["duration_count"] else 0,
        }
        for day, value in sorted(daily.items())
    ]
    return {
        "total": len(rows),
        "success_count": sum(1 for row in rows if str(row["status"] or "") == "success"),
        "error_count": sum(1 for row in rows if str(row["status"] or "") in {"error", "failed"}),
        "avg_duration": round(duration_total / duration_count, 1) if duration_count else 0,
        "status_counts": status_counts,
        "model_counts": model_counts,
        "size_counts": size_counts,
        "lora_counts": lora_counts,
        "combo_counts": combo_counts,
        "daily": daily_list[-30:],
    }


def save_batch_job(job: dict) -> None:
    """写入或更新批量绘画任务。"""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO batch_jobs (batch_id, status, total, done, current_group, results, error, created_at, finished_at, stop_requested, mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(batch_id) DO UPDATE SET
                status = excluded.status,
                total = excluded.total,
                done = excluded.done,
                current_group = excluded.current_group,
                results = excluded.results,
                error = excluded.error,
                finished_at = excluded.finished_at,
                stop_requested = excluded.stop_requested,
                mode = excluded.mode
            """,
            (
                job.get("batch_id"),
                job.get("status"),
                int(job.get("total") or 0),
                int(job.get("done") or 0),
                int(job.get("current_group") or 0),
                json.dumps(job.get("results") or [], ensure_ascii=False),
                job.get("error"),
                job.get("created_at"),
                job.get("finished_at"),
                1 if job.get("stop_requested") else 0,
                job.get("mode") or "generate",
            ),
        )


def get_batch_job(batch_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM batch_jobs WHERE batch_id = ?", (batch_id,)).fetchone()
    if not row:
        return None
    job = dict(row)
    job["results"] = json.loads(job["results"] or "[]")
    job["stop_requested"] = bool(job["stop_requested"])
    return job


def list_batch_jobs() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM batch_jobs ORDER BY created_at DESC").fetchall()
    jobs = []
    for row in rows:
        job = dict(row)
        job["results"] = json.loads(job["results"] or "[]")
        job["stop_requested"] = bool(job["stop_requested"])
        jobs.append(job)
    return jobs


def save_background_job(job: dict) -> None:
    """写入统一任务注册表（background_jobs）。"""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO background_jobs (
                job_id, kind, status, total, done, current, error, stop_requested,
                payload, resources_json, created_at, updated_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                kind = excluded.kind,
                status = excluded.status,
                total = excluded.total,
                done = excluded.done,
                current = excluded.current,
                error = excluded.error,
                stop_requested = excluded.stop_requested,
                payload = excluded.payload,
                resources_json = excluded.resources_json,
                updated_at = excluded.updated_at,
                finished_at = excluded.finished_at
            """,
            (
                job.get("job_id"),
                job.get("kind"),
                job.get("status"),
                int(job.get("total") or 0),
                int(job.get("done") or 0),
                job.get("current") or "",
                job.get("error"),
                1 if job.get("stop_requested") else 0,
                json.dumps(job.get("payload") or {}, ensure_ascii=False),
                json.dumps(job.get("resources") or [], ensure_ascii=False),
                job.get("created_at"),
                job.get("updated_at"),
                job.get("finished_at"),
            ),
        )


def get_background_job(job_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM background_jobs WHERE job_id = ?", (job_id,)).fetchone()
    if not row:
        return None
    job = dict(row)
    try:
        job["payload"] = json.loads(job["payload"] or "{}")
    except json.JSONDecodeError:
        job["payload"] = {}
    try:
        job["resources"] = json.loads(job.get("resources_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        job["resources"] = []
    job["stop_requested"] = bool(job["stop_requested"])
    return job


def list_background_jobs(
    kind: str | None = None,
    status: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    query = "SELECT * FROM background_jobs"
    clauses: list[str] = []
    args: list = []
    if kind:
        clauses.append("kind = ?")
        args.append(kind)
    if status:
        clauses.append("status = ?")
        args.append(status)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC"
    if limit:
        query += " LIMIT ?"
        args.append(limit)
    with get_connection() as conn:
        rows = conn.execute(query, args).fetchall()
    jobs = []
    for row in rows:
        job = dict(row)
        try:
            job["payload"] = json.loads(job["payload"] or "{}")
        except json.JSONDecodeError:
            job["payload"] = {}
        try:
            job["resources"] = json.loads(job.get("resources_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            job["resources"] = []
        job["stop_requested"] = bool(job["stop_requested"])
        jobs.append(job)
    return jobs


def _expire_task_resource_claims(conn: sqlite3.Connection, now_epoch: float) -> int:
    """Release leases whose heartbeat has expired."""
    cursor = conn.execute(
        """
        UPDATE task_resource_claims
        SET released_at = ?, release_reason = 'expired'
        WHERE released_at IS NULL AND expires_at <= ?
        """,
        (now_iso(), now_epoch),
    )
    return int(cursor.rowcount or 0)


def acquire_task_resource_claims(
    job_id: str,
    kind: str,
    resources: list[dict],
    *,
    owner_token: str,
    ttl_seconds: float,
) -> list[dict]:
    """Atomically acquire all requested task resources or raise a conflict."""
    normalized = [
        {"key": str(item.get("key") or ""), "mode": str(item.get("mode") or "")}
        for item in resources
    ]
    if not normalized:
        return []
    now_epoch = time.time()
    expires_at = now_epoch + max(float(ttl_seconds), 1.0)
    timestamp = now_iso()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _expire_task_resource_claims(conn, now_epoch)
        existing_rows = conn.execute(
            """
            SELECT * FROM task_resource_claims
            WHERE job_id = ? AND released_at IS NULL AND expires_at > ?
            """,
            (job_id, now_epoch),
        ).fetchall()
        existing = {str(row["resource_key"]): dict(row) for row in existing_rows}
        conflicts: list[dict] = []
        for requested in normalized:
            key = requested["key"]
            mode = requested["mode"]
            if key in existing:
                continue
            active_rows = conn.execute(
                """
                SELECT * FROM task_resource_claims
                WHERE resource_key = ? AND released_at IS NULL AND expires_at > ?
                ORDER BY acquired_at, id
                """,
                (key, now_epoch),
            ).fetchall()
            conflict = False
            if mode == "exclusive":
                conflict = bool(active_rows)
            elif mode == "shared":
                conflict = any(str(row["mode"]) == "exclusive" for row in active_rows)
            else:
                raise ValueError(f"invalid resource mode: {mode}")
            if conflict:
                conflicts.append(
                    {
                        "resource_key": key,
                        "requested_mode": mode,
                        "claims": [dict(row) for row in active_rows],
                    }
                )
        if conflicts:
            conn.rollback()
            raise ResourceConflictError(conflicts)

        claims: list[dict] = []
        for requested in normalized:
            key = requested["key"]
            mode = requested["mode"]
            if key in existing:
                conn.execute(
                    """
                    UPDATE task_resource_claims
                    SET heartbeat_at = ?, expires_at = ?
                    WHERE id = ?
                    """,
                    (timestamp, expires_at, existing[key]["id"]),
                )
                row = conn.execute(
                    "SELECT * FROM task_resource_claims WHERE id = ?",
                    (existing[key]["id"],),
                ).fetchone()
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO task_resource_claims (
                        resource_key, job_id, kind, mode, owner_token,
                        acquired_at, heartbeat_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (key, job_id, kind, mode, owner_token, timestamp, timestamp, expires_at),
                )
                row = conn.execute(
                    "SELECT * FROM task_resource_claims WHERE id = ?",
                    (cursor.lastrowid,),
                ).fetchone()
            if row is not None:
                claims.append(dict(row))
        conn.commit()
        return claims


def renew_task_resource_claims(
    job_id: str,
    *,
    owner_token: str,
    ttl_seconds: float,
) -> int:
    """Renew all active claims owned by this process for a job."""
    now_epoch = time.time()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE task_resource_claims
            SET heartbeat_at = ?, expires_at = ?
            WHERE job_id = ? AND owner_token = ?
              AND released_at IS NULL AND expires_at > ?
            """,
            (now_iso(), now_epoch + max(float(ttl_seconds), 1.0), job_id, owner_token, now_epoch),
        )
        return int(cursor.rowcount or 0)


def release_task_resource_claims(
    job_id: str,
    *,
    owner_token: str | None = None,
    reason: str = "released",
) -> int:
    """Release active claims for a job, optionally restricted to one owner."""
    clauses = ["job_id = ?", "released_at IS NULL"]
    args: list = [job_id]
    if owner_token is not None:
        clauses.append("owner_token = ?")
        args.append(owner_token)
    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE task_resource_claims SET released_at = ?, release_reason = ? WHERE {' AND '.join(clauses)}",
            (now_iso(), reason, *args),
        )
        return int(cursor.rowcount or 0)


def list_task_resource_claims(
    *,
    job_id: str | None = None,
    resource_key: str | None = None,
    active_only: bool = True,
) -> list[dict]:
    query = "SELECT * FROM task_resource_claims"
    clauses: list[str] = []
    args: list = []
    if job_id:
        clauses.append("job_id = ?")
        args.append(job_id)
    if resource_key:
        clauses.append("resource_key = ?")
        args.append(resource_key)
    if active_only:
        clauses.append("released_at IS NULL AND expires_at > ?")
        args.append(time.time())
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY acquired_at DESC, id DESC"
    with get_connection() as conn:
        rows = conn.execute(query, args).fetchall()
    return [dict(row) for row in rows]


def list_active_task_resource_claims() -> list[dict]:
    with get_connection() as conn:
        _expire_task_resource_claims(conn, time.time())
        rows = conn.execute(
            """
            SELECT * FROM task_resource_claims
            WHERE released_at IS NULL AND expires_at > ?
            ORDER BY resource_key, acquired_at, id
            """,
            (time.time(),),
        ).fetchall()
    return [dict(row) for row in rows]


def insert_activity_event(
    event_type: str,
    *,
    module: str = "",
    actor_type: str = "system",
    job_id: str | None = None,
    kind: str | None = None,
    severity: str = "info",
    summary: str = "",
    correlation_id: str | None = None,
    payload: dict | None = None,
) -> dict:
    """Append one generic activity/audit event."""
    event = {
        "event_id": uuid.uuid4().hex,
        "occurred_at": now_iso(),
        "event_type": event_type,
        "module": module,
        "actor_type": actor_type,
        "job_id": job_id,
        "kind": kind,
        "severity": severity,
        "summary": summary,
        "correlation_id": correlation_id,
        "payload": payload or {},
    }
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO activity_events (
                event_id, occurred_at, event_type, module, actor_type, job_id,
                kind, severity, summary, correlation_id, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["event_id"],
                event["occurred_at"],
                event["event_type"],
                event["module"],
                event["actor_type"],
                event["job_id"],
                event["kind"],
                event["severity"],
                event["summary"],
                event["correlation_id"],
                json.dumps(event["payload"], ensure_ascii=False),
            ),
        )
    return event


def list_activity_events(
    *,
    event_type: str | None = None,
    module: str | None = None,
    job_id: str | None = None,
    kind: str | None = None,
    limit: int = 100,
) -> list[dict]:
    query = "SELECT * FROM activity_events"
    clauses: list[str] = []
    args: list = []
    for column, value in (
        ("event_type", event_type),
        ("module", module),
        ("job_id", job_id),
        ("kind", kind),
    ):
        if value:
            clauses.append(f"{column} = ?")
            args.append(value)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY occurred_at DESC, rowid DESC LIMIT ?"
    args.append(max(1, min(int(limit), 500)))
    with get_connection() as conn:
        rows = conn.execute(query, args).fetchall()
    events = []
    for row in rows:
        event = dict(row)
        try:
            event["payload"] = json.loads(event.get("payload") or "{}")
        except json.JSONDecodeError:
            event["payload"] = {}
        events.append(event)
    return events


# ---- AI video module ----


def insert_video_script(
    source_input: str,
    script: dict,
    model: str,
    content_limited: bool,
) -> int:
    """保存 AI 视频单镜头剧本；script 以 JSON 落库。"""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO video_scripts (source_input, script_json, model, content_limited, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                source_input,
                json.dumps(script, ensure_ascii=False),
                model,
                1 if content_limited else 0,
                now_iso(),
            ),
        )
        return int(cursor.lastrowid)


def get_video_script(script_id: int) -> dict | None:
    """按 id 读取剧本并解析 script_json。"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM video_scripts WHERE id = ?", (script_id,)
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["script"] = json.loads(item.pop("script_json") or "{}")
    except json.JSONDecodeError:
        item["script"] = {}
    item["content_limited"] = bool(item["content_limited"])
    return item


def list_video_scripts(limit: int = 50) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM video_scripts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    items: list[dict] = []
    for row in rows:
        item = dict(row)
        try:
            item["script"] = json.loads(item.pop("script_json") or "{}")
        except json.JSONDecodeError:
            item["script"] = {}
        item["content_limited"] = bool(item["content_limited"])
        items.append(item)
    return items


def insert_video_record(
    job_id: str,
    script_id: int | None,
    keyframe_name: str,
    prompt: str,
    negative_prompt: str,
    model: str,
    loras: list[str],
    seed: int,
    width: int,
    height: int,
    frames: int,
    fps: int,
    status: str = "running",
) -> int:
    """创建成片记录；视频完成前 video_name 为空。"""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO video_records (
                job_id, script_id, keyframe_name, video_name, prompt, negative_prompt,
                model, loras, seed, width, height, frames, fps, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                script_id,
                keyframe_name,
                None,
                prompt,
                negative_prompt,
                model,
                json.dumps(loras, ensure_ascii=False),
                seed,
                width,
                height,
                frames,
                fps,
                status,
                now_iso(),
            ),
        )
        return int(cursor.lastrowid)


def _video_record_row(row: sqlite3.Row) -> dict:
    item = dict(row)
    try:
        item["loras"] = json.loads(item.get("loras") or "[]")
    except json.JSONDecodeError:
        item["loras"] = []
    return item


def get_video_record_by_job(job_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM video_records WHERE job_id = ?", (job_id,)
        ).fetchone()
    return _video_record_row(row) if row else None


def get_video_record(record_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM video_records WHERE id = ?", (record_id,)
        ).fetchone()
    return _video_record_row(row) if row else None


def update_video_record_result(
    job_id: str,
    status: str,
    error: str | None = None,
    video_name: str | None = None,
    duration_seconds: float | None = None,
) -> dict | None:
    """更新成片记录终态；由任务 job_id 定位。"""
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE video_records
            SET status = ?, error = ?, video_name = ?, duration_seconds = ?, finished_at = ?
            WHERE job_id = ?
            """,
            (status, error, video_name, duration_seconds, now_iso(), job_id),
        )
    return get_video_record_by_job(job_id)


def list_video_records(limit: int = 100) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM video_records ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_video_record_row(row) for row in rows]


def list_video_records_raw() -> list[dict]:
    """数据看板原始统计用，不解析 loras。"""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM video_records").fetchall()
    return [dict(row) for row in rows]


def delete_video_record(record_id: int) -> dict | None:
    """删除成片记录并返回删除前的元数据，供文件清理使用。"""
    record = get_video_record(record_id)
    if not record:
        return None
    with get_connection() as conn:
        conn.execute("DELETE FROM video_records WHERE id = ?", (record_id,))
    return record


def mark_interrupted_video_records() -> int:
    """后端重启后，把仍在 running 的成片记录标记为 interrupted。"""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE video_records
            SET status = 'interrupted', error = '后端重启中断，任务无法继续', finished_at = ?
            WHERE status = 'running'
            """,
            (now_iso(),),
        )
        return int(cursor.rowcount)


# ---- companion module ----


def list_companion_personas() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM companion_personas ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def get_companion_persona(persona_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM companion_personas WHERE id = ?", (persona_id,)).fetchone()
    return dict(row) if row else None


def insert_companion_persona(data: dict) -> int:
    timestamp = now_iso()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO companion_personas (name, source, relationship, gender, personality, tone, appearance, catchphrases, avatar, config_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.get("name", ""),
                data.get("source", ""),
                data.get("relationship", "恋人"),
                data.get("gender", ""),
                data.get("personality", ""),
                data.get("tone", ""),
                data.get("appearance", ""),
                data.get("catchphrases", ""),
                data.get("avatar", ""),
                json.dumps(data.get("config_json") or {}, ensure_ascii=False),
                timestamp,
                timestamp,
            ),
        )
        return int(cursor.lastrowid)


def update_companion_persona(persona_id: int, data: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE companion_personas
            SET name = ?, source = ?, relationship = ?, gender = ?, personality = ?, tone = ?, appearance = ?, catchphrases = ?, avatar = ?, config_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                data.get("name", ""),
                data.get("source", ""),
                data.get("relationship", "恋人"),
                data.get("gender", ""),
                data.get("personality", ""),
                data.get("tone", ""),
                data.get("appearance", ""),
                data.get("catchphrases", ""),
                data.get("avatar", ""),
                json.dumps(data.get("config_json") or {}, ensure_ascii=False),
                now_iso(),
                persona_id,
            ),
        )


def update_companion_persona_appearance(persona_id: int, appearance: str) -> None:
    """仅回填外观特征，不覆盖用户其他字段。"""
    with get_connection() as conn:
        conn.execute(
            "UPDATE companion_personas SET appearance = ?, updated_at = ? WHERE id = ?",
            (appearance, now_iso(), persona_id),
        )


def delete_companion_persona(persona_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM companion_personas WHERE id = ?", (persona_id,))
        conn.execute("DELETE FROM companion_sessions WHERE persona_id = ?", (persona_id,))
        conn.execute("DELETE FROM companion_messages WHERE persona_id = ?", (persona_id,))
        conn.execute("DELETE FROM companion_memories WHERE persona_id = ?", (persona_id,))


def list_companion_sessions(persona_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM companion_sessions WHERE persona_id = ? ORDER BY updated_at DESC",
            (persona_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_companion_session(session_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM companion_sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def create_companion_session(persona_id: int, title: str = "新会话") -> int:
    timestamp = now_iso()
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO companion_sessions (persona_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (persona_id, title, timestamp, timestamp),
        )
        return int(cursor.lastrowid)


def delete_companion_session(session_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM companion_messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM companion_sessions WHERE id = ?", (session_id,))


def list_companion_messages(session_id: int, limit: int = 50) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM companion_messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def insert_companion_message(
    session_id: int,
    persona_id: int,
    role: str,
    content: str,
    emotion: str = "",
    image_path: str = "",
    image_description: str = "",
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO companion_messages (session_id, persona_id, role, content, emotion, image_path, image_description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, persona_id, role, content, emotion, image_path, image_description, now_iso()),
        )
        return int(cursor.lastrowid)


def list_companion_memories(persona_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM companion_memories WHERE persona_id = ? ORDER BY id DESC",
            (persona_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def insert_companion_memory(persona_id: int, content: str, embedding: str = "", importance: int = 1) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO companion_memories (persona_id, content, embedding, importance, created_at) VALUES (?, ?, ?, ?, ?)",
            (persona_id, content, embedding, importance, now_iso()),
        )
        return int(cursor.lastrowid)


def delete_companion_memory(memory_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM companion_memories WHERE id = ?", (memory_id,))


def get_companion_setting(key: str, default: str = "") -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM companion_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_companion_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO companion_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# ---- lora protection / usage ----


def lora_usage_counts() -> dict[str, int]:
    """统计每个 LoRA 文件在绘画记录中的使用次数（含旧版标志位）。"""
    counts: dict[str, int] = {}
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT loras_json, lora_anima_turbo, lora_high_contrast FROM draw_records"
        ).fetchall()
    for row in rows:
        try:
            names = json.loads(row["loras_json"] or "[]")
        except json.JSONDecodeError:
            names = []
        for name in names:
            if isinstance(name, str) and name:
                key = name if name.endswith(".safetensors") else name + ".safetensors"
                counts[key] = counts.get(key, 0) + 1
        if row["lora_anima_turbo"]:
            counts["anima-turbo-lora-v0.2.safetensors"] = counts.get("anima-turbo-lora-v0.2.safetensors", 0) + 1
        if row["lora_high_contrast"]:
            counts["high-contrast aesthetic.safetensors"] = counts.get("high-contrast aesthetic.safetensors", 0) + 1
    return counts


def get_lora_protection(name: str) -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM lora_protections WHERE name = ?", (name,)).fetchone()
    return row is not None


def set_lora_protection(name: str, protected: bool) -> None:
    with get_connection() as conn:
        if protected:
            conn.execute(
                "INSERT INTO lora_protections (name, source, created_at) VALUES (?, 'loras', ?) ON CONFLICT(name) DO NOTHING",
                (name, now_iso()),
            )
        else:
            conn.execute("DELETE FROM lora_protections WHERE name = ?", (name,))


# ---- train job persistence ----


def save_train_job(job: dict) -> None:
    """持久化训练任务元数据（参数、状态、时间、Loss 摘要）。"""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO train_jobs (
                job_id, output_name, status, dit, resolution, repeats, batch_size,
                network_dim, network_alpha, learning_rate, epochs, save_every, max_steps,
                auto_convert, error, steps_done, steps_total, latest_loss, min_loss, best_step,
                created_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                output_name = excluded.output_name,
                status = excluded.status,
                dit = excluded.dit,
                resolution = excluded.resolution,
                repeats = excluded.repeats,
                batch_size = excluded.batch_size,
                network_dim = excluded.network_dim,
                network_alpha = excluded.network_alpha,
                learning_rate = excluded.learning_rate,
                epochs = excluded.epochs,
                save_every = excluded.save_every,
                max_steps = excluded.max_steps,
                auto_convert = excluded.auto_convert,
                error = excluded.error,
                steps_done = excluded.steps_done,
                steps_total = excluded.steps_total,
                latest_loss = excluded.latest_loss,
                min_loss = excluded.min_loss,
                best_step = excluded.best_step,
                created_at = excluded.created_at,
                finished_at = excluded.finished_at
            """,
            (
                job.get("job_id"),
                job.get("output_name"),
                job.get("status"),
                job.get("dit"),
                job.get("resolution"),
                job.get("repeats"),
                job.get("batch_size"),
                job.get("network_dim"),
                job.get("network_alpha"),
                job.get("learning_rate"),
                job.get("epochs"),
                job.get("save_every"),
                job.get("max_steps"),
                1 if job.get("auto_convert") else 0,
                job.get("error"),
                job.get("steps_done"),
                job.get("steps_total"),
                job.get("latest_loss"),
                job.get("min_loss"),
                job.get("best_step"),
                job.get("created_at"),
                job.get("finished_at"),
            ),
        )


def get_train_job(job_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM train_jobs WHERE job_id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def list_train_jobs(limit: int = 50) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM train_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def list_train_jobs_raw() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM train_jobs").fetchall()
    return [dict(row) for row in rows]


def list_batch_jobs_raw() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM batch_jobs").fetchall()
    return [dict(row) for row in rows]


def list_prompt_sets_raw() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT name, type, use_count FROM prompt_sets").fetchall()
    return [dict(row) for row in rows]


def list_all_prompt_sets() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM prompt_sets ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def _tag_values(value) -> list[str]:
    if isinstance(value, list):
        parts = [str(item) for item in value]
    else:
        parts = str(value or "").split(",")
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        cleaned = str(part).strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def get_character_appearance(character_name: str, work: str = "") -> dict | None:
    """查询角色外观缓存；名称与作品忽略大小写。"""
    name = str(character_name or "").strip()
    source_work = str(work or "").strip()
    if not name:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM character_appearance
            WHERE lower(character_name) = lower(?) AND lower(COALESCE(work, '')) = lower(?)
            """,
            (name, source_work),
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    return {
        "id": data["id"],
        "character_name": data["character_name"],
        "work": data["work"] or "",
        "appearance": _tag_values(data["appearance_tags"]),
        "clothing": _tag_values(data["clothing_tags"]),
        "full_prompt": data["full_prompt"] or "",
        "confidence": float(data["confidence"] or 0),
        "source": data["source"] or "llm",
        "note": data["note"] or "",
        "corrected": bool(data["corrected"]),
        "updated_at": data["updated_at"],
    }


def save_character_appearance(
    character_name: str,
    work: str,
    appearance_tags,
    clothing_tags,
    note: str = "",
    confidence: float = 0,
    source: str = "manual",
    corrected: bool = True,
) -> dict:
    """保存角色外观（生成草稿或人工修正），名称+作品重复时覆盖。"""
    name = str(character_name or "").strip()
    source_work = str(work or "").strip()
    if not name:
        raise ValueError("角色名不能为空")
    appearance = _tag_values(appearance_tags)
    clothing = _tag_values(clothing_tags)
    appearance_text = ", ".join(appearance)
    clothing_text = ", ".join(clothing)
    full_prompt = ", ".join([*appearance, *clothing])
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO character_appearance (
                character_name, work, appearance_tags, clothing_tags, full_prompt,
                confidence, source, note, corrected, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(character_name, work) DO UPDATE SET
                appearance_tags = excluded.appearance_tags,
                clothing_tags = excluded.clothing_tags,
                full_prompt = excluded.full_prompt,
                confidence = excluded.confidence,
                source = excluded.source,
                note = excluded.note,
                corrected = excluded.corrected,
                updated_at = excluded.updated_at
            """,
            (
                name,
                source_work,
                appearance_text,
                clothing_text,
                full_prompt,
                max(0.0, min(1.0, float(confidence or 0))),
                source,
                str(note or "").strip(),
                1 if corrected else 0,
                now,
                now,
            ),
        )
    return get_character_appearance(name, source_work)


def _decode_json_tags(value) -> list[str]:
    if isinstance(value, list):
        return _tag_values(value)
    try:
        decoded = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        decoded = str(value or "").split(",")
    return _tag_values(decoded)


def _appearance_preset_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    return {
        "id": int(data["id"]),
        "preset_id": str(data["preset_id"]),
        "name": str(data["name"]),
        "work": str(data["work"] or ""),
        "category": str(data["category"] or "自由备注"),
        "appearance_tags": _decode_json_tags(data["appearance_tags"]),
        "clothing_tags": _decode_json_tags(data["clothing_tags"]),
        "expression_tags": _decode_json_tags(data["expression_tags"]),
        "outfit_id": str(data.get("outfit_id") or ""),
        "note": str(data["note"] or ""),
        "source": str(data["source"] or "user"),
        "version": int(data["version"] or 1),
        "enabled": bool(data["enabled"]),
        "created_at": str(data["created_at"]),
        "updated_at": str(data["updated_at"]),
    }


def list_character_appearance_presets(
    keyword: str = "",
    category: str = "",
    source: str = "",
    work: str = "",
    enabled: bool | None = None,
) -> list[dict]:
    """返回每个稳定 preset_id 的最新版本。"""
    clauses = [
        """
        p.version = (
            SELECT MAX(p2.version)
            FROM character_appearance_presets p2
            WHERE p2.preset_id = p.preset_id
        )
        """
    ]
    params: list[object] = []
    if keyword.strip():
        like = f"%{keyword.strip()}%"
        clauses.append(
            "(p.name LIKE ? OR p.work LIKE ? OR p.outfit_id LIKE ? OR p.note LIKE ? "
            "OR p.appearance_tags LIKE ? OR p.clothing_tags LIKE ? OR p.expression_tags LIKE ?)"
        )
        params.extend([like, like, like, like, like, like, like])
    if category.strip():
        clauses.append("p.category = ?")
        params.append(category.strip())
    if source.strip():
        clauses.append("p.source = ?")
        params.append(source.strip())
    if work.strip():
        clauses.append("p.work = ?")
        params.append(work.strip())
    if enabled is not None:
        clauses.append("p.enabled = ?")
        params.append(1 if enabled else 0)
    where = " AND ".join(clauses)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT p.* FROM character_appearance_presets p
            WHERE {where}
            ORDER BY CASE p.source WHEN 'builtin' THEN 0 ELSE 1 END,
                     p.updated_at DESC, p.id DESC
            """,
            params,
        ).fetchall()
    return [_appearance_preset_row(row) for row in rows]


def list_character_appearance_works() -> list[str]:
    """返回最新版本中全部非空作品名，供筛选器使用。"""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT p.work
            FROM character_appearance_presets p
            WHERE p.version = (
                SELECT MAX(p2.version)
                FROM character_appearance_presets p2
                WHERE p2.preset_id = p.preset_id
            )
              AND TRIM(COALESCE(p.work, '')) <> ''
            GROUP BY p.work
            ORDER BY p.work COLLATE NOCASE
            """
        ).fetchall()
    return [str(row["work"]) for row in rows]


def get_character_appearance_preset(
    preset_id: str,
    version: int | None = None,
) -> dict | None:
    with get_connection() as conn:
        if version is None:
            row = conn.execute(
                """
                SELECT * FROM character_appearance_presets
                WHERE preset_id = ?
                ORDER BY version DESC LIMIT 1
                """,
                (preset_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM character_appearance_presets
                WHERE preset_id = ? AND version = ?
                """,
                (preset_id, version),
            ).fetchone()
    return _appearance_preset_row(row) if row else None


def create_character_appearance_preset(
    preset_id: str,
    name: str,
    work: str,
    category: str,
    appearance_tags,
    clothing_tags,
    expression_tags,
    outfit_id: str = "",
    note: str = "",
    source: str = "user",
    enabled: bool = True,
) -> dict:
    now = now_iso()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO character_appearance_presets (
                preset_id, name, work, category, appearance_tags, clothing_tags,
                expression_tags, outfit_id, note, source, version, enabled,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                preset_id,
                name,
                work,
                category,
                json.dumps(_tag_values(appearance_tags), ensure_ascii=False),
                json.dumps(_tag_values(clothing_tags), ensure_ascii=False),
                json.dumps(_tag_values(expression_tags), ensure_ascii=False),
                str(outfit_id or "").strip(),
                note,
                source,
                1 if enabled else 0,
                now,
                now,
            ),
        )
        row_id = int(cursor.lastrowid)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM character_appearance_presets WHERE id = ?",
            (row_id,),
        ).fetchone()
    return _appearance_preset_row(row)


def update_character_appearance_preset(
    preset_id: str,
    name: str,
    work: str,
    category: str,
    appearance_tags,
    clothing_tags,
    expression_tags,
    outfit_id: str = "",
    note: str = "",
    source: str = "user",
    enabled: bool = True,
) -> dict:
    """写入新版本，历史版本保留。"""
    current = get_character_appearance_preset(preset_id)
    if not current:
        raise KeyError(preset_id)
    now = now_iso()
    next_version = int(current["version"]) + 1
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO character_appearance_presets (
                preset_id, name, work, category, appearance_tags, clothing_tags,
                expression_tags, outfit_id, note, source, version, enabled,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                preset_id,
                name,
                work,
                category,
                json.dumps(_tag_values(appearance_tags), ensure_ascii=False),
                json.dumps(_tag_values(clothing_tags), ensure_ascii=False),
                json.dumps(_tag_values(expression_tags), ensure_ascii=False),
                str(outfit_id or "").strip(),
                note,
                source,
                next_version,
                1 if enabled else 0,
                now,
                now,
            ),
        )
        row_id = int(cursor.lastrowid)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM character_appearance_presets WHERE id = ?",
            (row_id,),
        ).fetchone()
    return _appearance_preset_row(row)


def delete_character_appearance_preset(preset_id: str) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM character_appearance_presets WHERE preset_id = ?",
            (preset_id,),
        )
        return int(cursor.rowcount)


def count_character_appearance_preset_references(preset_id: str) -> dict:
    query = """
        SELECT COUNT(*) FROM {table}
        WHERE EXISTS (
            SELECT 1
            FROM json_tree({table}.prompt_document_json) AS node
            WHERE node.key = 'preset_id' AND node.value = ?
        )
    """
    with get_connection() as conn:
        try:
            prompt_refs = int(
                conn.execute(query.format(table="prompt_sets"), (preset_id,)).fetchone()[0]
            )
            draw_refs = int(
                conn.execute(query.format(table="draw_records"), (preset_id,)).fetchone()[0]
            )
        except sqlite3.OperationalError:
            prompt_refs = _count_json_preset_references(
                conn, "prompt_sets", preset_id
            )
            draw_refs = _count_json_preset_references(
                conn, "draw_records", preset_id
            )
    return {
        "preset_id": preset_id,
        "prompt_sets": prompt_refs,
        "draw_records": draw_refs,
        "total": prompt_refs + draw_refs,
    }


def _count_json_preset_references(
    conn: sqlite3.Connection,
    table: str,
    preset_id: str,
) -> int:
    count = 0
    rows = conn.execute(f"SELECT prompt_document_json FROM {table}").fetchall()
    for row in rows:
        try:
            document = json.loads(row["prompt_document_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if _json_contains_preset_id(document, preset_id):
            count += 1
    return count


def _json_contains_preset_id(value: object, preset_id: str) -> bool:
    if isinstance(value, dict):
        if value.get("preset_id") == preset_id:
            return True
        return any(
            _json_contains_preset_id(item, preset_id) for item in value.values()
        )
    if isinstance(value, list):
        return any(_json_contains_preset_id(item, preset_id) for item in value)
    return False


def companion_summary() -> dict:
    """情感陪伴汇总：会话数、活跃会话、消息数、记忆数、按人设消息数与最近情绪。"""
    with get_connection() as conn:
        sessions = conn.execute("SELECT COUNT(*) FROM companion_sessions").fetchone()[0]
        active_cutoff = (datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)).isoformat(
            timespec="seconds"
        )
        active_sessions = conn.execute(
            "SELECT COUNT(*) FROM companion_sessions WHERE updated_at >= ?",
            (active_cutoff,),
        ).fetchone()[0]
        messages = conn.execute("SELECT COUNT(*) FROM companion_messages").fetchone()[0]
        memories = conn.execute("SELECT COUNT(*) FROM companion_memories").fetchone()[0]
        rows = conn.execute(
            "SELECT persona_id, COUNT(*) AS count FROM companion_messages GROUP BY persona_id"
        ).fetchall()
        personas = conn.execute("SELECT id, name FROM companion_personas").fetchall()
        emotion_rows = conn.execute(
            "SELECT emotion FROM companion_messages WHERE emotion != '' ORDER BY id DESC LIMIT 100"
        ).fetchall()
    names = {row["id"]: row["name"] for row in personas}
    by_persona = {names.get(row["persona_id"], f"人设 {row['persona_id']}"): row["count"] for row in rows}
    recent_emotions: dict[str, int] = {}
    for row in emotion_rows:
        emotion = str(row["emotion"] or "平静")
        recent_emotions[emotion] = recent_emotions.get(emotion, 0) + 1
    return {
        "sessions": sessions,
        "active_sessions": active_sessions,
        "messages": messages,
        "memories": memories,
        "by_persona": by_persona,
        "recent_emotions": recent_emotions,
    }


def get_preset_asset_setting(key: str) -> dict | None:
    """读取预设素材工坊 JSON 设置。"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value_json FROM preset_asset_settings WHERE key = ?", (key,)
        ).fetchone()
    if not row:
        return None
    try:
        value = json.loads(row["value_json"] or "{}")
    except json.JSONDecodeError:
        value = {}
    return value if isinstance(value, dict) else {}


def set_preset_asset_setting(key: str, value: dict) -> None:
    """保存预设素材工坊 JSON 设置。"""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO preset_asset_settings (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            (key, json.dumps(value or {}, ensure_ascii=False), now_iso()),
        )


def get_preset_asset_settings() -> dict:
    """读取全部预设素材工坊设置。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT key, value_json, updated_at FROM preset_asset_settings"
        ).fetchall()
    result: dict[str, dict] = {}
    for row in rows:
        try:
            value = json.loads(row["value_json"] or "{}")
        except json.JSONDecodeError:
            value = {}
        result[str(row["key"])] = {
            "value": value if isinstance(value, dict) else {},
            "updated_at": row["updated_at"],
        }
    return result


def insert_preset_asset_source(
    preset_type: str,
    preset_id: str,
    revision: int,
    source_kind: str,
    managed_path: str,
    mime_type: str,
    width: int,
    height: int,
    sha256: str,
    active: bool = True,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO preset_asset_sources (
                preset_type, preset_id, revision, source_kind, managed_path,
                mime_type, width, height, sha256, active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                preset_type,
                preset_id,
                int(revision),
                source_kind,
                managed_path,
                mime_type,
                int(width),
                int(height),
                sha256,
                1 if active else 0,
                now_iso(),
            ),
        )
        return int(cursor.lastrowid)


def _preset_asset_source_row(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["active"] = bool(item.get("active"))
    return item


def get_preset_asset_source(source_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM preset_asset_sources WHERE id = ?", (source_id,)
        ).fetchone()
    return _preset_asset_source_row(row) if row else None


def list_preset_asset_sources(
    preset_type: str,
    preset_id: str,
    active_only: bool = False,
    limit: int = 100,
) -> list[dict]:
    query = (
        "SELECT * FROM preset_asset_sources "
        "WHERE preset_type = ? AND preset_id = ?"
    )
    args: list = [preset_type, preset_id]
    if active_only:
        query += " AND active = 1"
    query += " ORDER BY revision DESC, id DESC LIMIT ?"
    args.append(int(limit))
    with get_connection() as conn:
        rows = conn.execute(query, args).fetchall()
    return [_preset_asset_source_row(row) for row in rows]


def get_active_preset_asset_source(
    preset_type: str, preset_id: str
) -> dict | None:
    rows = list_preset_asset_sources(
        preset_type, preset_id, active_only=True, limit=1
    )
    return rows[0] if rows else None


def deactivate_preset_asset_sources(preset_type: str, preset_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE preset_asset_sources SET active = 0
            WHERE preset_type = ? AND preset_id = ?
            """,
            (preset_type, preset_id),
        )


def insert_preset_asset_candidate(
    preset_type: str,
    preset_id: str,
    generation_mode: str,
    status: str,
    params: dict,
    *,
    job_id: str | None = None,
    source_revision_id: int | None = None,
    original_path: str | None = None,
    preview_path: str | None = None,
    thumbnail_path: str | None = None,
    prompt_positive: str = "",
    prompt_negative: str = "",
    template_version: str = "",
    model: str = "",
    loras: list[str] | None = None,
    seed: int | None = None,
    generation_width: int = 0,
    generation_height: int = 0,
    output_width: int = 0,
    output_height: int = 0,
    crop: dict | None = None,
    error: str | None = None,
) -> int:
    timestamp = now_iso()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO preset_asset_candidates (
                job_id, preset_type, preset_id, source_revision_id,
                generation_mode, status, original_path, preview_path,
                thumbnail_path, params_json, prompt_positive, prompt_negative,
                template_version, model, loras_json, seed, generation_width,
                generation_height, output_width, output_height, crop_json,
                error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                preset_type,
                preset_id,
                source_revision_id,
                generation_mode,
                status,
                original_path,
                preview_path,
                thumbnail_path,
                json.dumps(params or {}, ensure_ascii=False),
                prompt_positive,
                prompt_negative,
                template_version,
                model,
                json.dumps(loras or [], ensure_ascii=False),
                seed,
                int(generation_width),
                int(generation_height),
                int(output_width),
                int(output_height),
                json.dumps(crop or {}, ensure_ascii=False),
                error,
                timestamp,
                timestamp,
            ),
        )
        return int(cursor.lastrowid)


def _preset_asset_candidate_row(row: sqlite3.Row) -> dict:
    item = dict(row)
    for source, target, fallback in (
        ("params_json", "params", {}),
        ("loras_json", "loras", []),
        ("crop_json", "crop", {}),
    ):
        try:
            item[target] = json.loads(item.get(source) or json.dumps(fallback))
        except json.JSONDecodeError:
            item[target] = fallback
        item.pop(source, None)
    return item


def get_preset_asset_candidate(candidate_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM preset_asset_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
    return _preset_asset_candidate_row(row) if row else None


def list_preset_asset_candidates_by_ids(candidate_ids: list[int]) -> list[dict]:
    """Batch-load candidates without issuing one query per preset."""
    ids = sorted(
        {
            int(candidate_id)
            for candidate_id in candidate_ids
            if int(candidate_id) > 0
        }
    )
    if not ids:
        return []
    placeholders = ", ".join("?" for _ in ids)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM preset_asset_candidates
            WHERE id IN ({placeholders})
            ORDER BY id
            """,
            ids,
        ).fetchall()
    return [_preset_asset_candidate_row(row) for row in rows]


_PRESET_ASSET_CANDIDATE_FIELDS = {
    "job_id",
    "source_revision_id",
    "generation_mode",
    "status",
    "original_path",
    "preview_path",
    "thumbnail_path",
    "params_json",
    "prompt_positive",
    "prompt_negative",
    "template_version",
    "model",
    "loras_json",
    "seed",
    "generation_width",
    "generation_height",
    "output_width",
    "output_height",
    "crop_json",
    "error",
}


def update_preset_asset_candidate(candidate_id: int, **changes) -> dict | None:
    safe = {key: value for key, value in changes.items() if key in _PRESET_ASSET_CANDIDATE_FIELDS}
    if safe:
        assignments = ", ".join(f"{key} = ?" for key in safe)
        values = list(safe.values()) + [now_iso(), candidate_id]
        with get_connection() as conn:
            conn.execute(
                f"UPDATE preset_asset_candidates SET {assignments}, updated_at = ? WHERE id = ?",
                values,
            )
    return get_preset_asset_candidate(candidate_id)


def list_preset_asset_candidates(
    preset_type: str,
    preset_id: str,
    statuses: list[str] | None = None,
    limit: int = 100,
) -> list[dict]:
    query = (
        "SELECT * FROM preset_asset_candidates "
        "WHERE preset_type = ? AND preset_id = ?"
    )
    args: list = [preset_type, preset_id]
    if statuses:
        placeholders = ", ".join("?" for _ in statuses)
        query += f" AND status IN ({placeholders})"
        args.extend(statuses)
    query += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    with get_connection() as conn:
        rows = conn.execute(query, args).fetchall()
    return [_preset_asset_candidate_row(row) for row in rows]


def discard_preset_asset_candidates(
    preset_type: str,
    preset_id: str,
) -> tuple[int, int, bool]:
    """Discard every non-adopted candidate unless generation is still active."""
    timestamp = now_iso()
    now_epoch = time.time()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            lease = conn.execute(
                """
                SELECT owner_token FROM preset_asset_write_leases
                WHERE preset_type = ? AND preset_id = ? AND expires_at > ?
                """,
                (preset_type, preset_id, now_epoch),
            ).fetchone()
            if lease:
                conn.rollback()
                return 0, 0, True
            active_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM preset_asset_candidates
                    WHERE preset_type = ? AND preset_id = ?
                      AND status IN ('queued', 'preparing', 'running', 'cancel_requested')
                    """,
                    (preset_type, preset_id),
                ).fetchone()[0]
            )
            if active_count:
                conn.rollback()
                return 0, active_count, False
            cursor = conn.execute(
                """
                UPDATE preset_asset_candidates
                SET status = 'discarded', updated_at = ?
                WHERE preset_type = ? AND preset_id = ?
                  AND status NOT IN ('adopted', 'discarded')
                """,
                (timestamp, preset_type, preset_id),
            )
            conn.commit()
            return max(0, int(cursor.rowcount)), 0, False
        except Exception:
            conn.rollback()
            raise


def list_preset_asset_candidates_by_job(job_id: str) -> list[dict]:
    """Return every candidate produced by one preset asset job."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM preset_asset_candidates
            WHERE job_id = ?
            ORDER BY id
            """,
            (job_id,),
        ).fetchall()
    return [_preset_asset_candidate_row(row) for row in rows]


def list_preset_asset_candidate_version_rows() -> list[dict]:
    """Return lightweight candidate version fields for read-only dashboards."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, preset_type, preset_id, status, params_json,
                   template_version, created_at, updated_at
            FROM preset_asset_candidates
            """
        ).fetchall()
    return [dict(row) for row in rows]


def insert_preset_asset_version(
    preset_type: str,
    preset_id: str,
    version: int,
    candidate_id: int | None,
    public_path: str,
    dist_path: str,
    mime_type: str,
    width: int,
    height: int,
    sha256: str,
    active: bool,
) -> int:
    with get_connection() as conn:
        if active:
            conn.execute(
                """
                UPDATE preset_asset_versions SET active = 0
                WHERE preset_type = ? AND preset_id = ?
                """,
                (preset_type, preset_id),
            )
        cursor = conn.execute(
            """
            INSERT INTO preset_asset_versions (
                preset_type, preset_id, version, candidate_id, public_path,
                dist_path, mime_type, width, height, sha256, active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                preset_type,
                preset_id,
                int(version),
                candidate_id,
                public_path,
                dist_path,
                mime_type,
                int(width),
                int(height),
                sha256,
                1 if active else 0,
                now_iso(),
            ),
        )
        return int(cursor.lastrowid)


def _preset_asset_version_row(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["active"] = bool(item.get("active"))
    return item


def get_preset_asset_version(version_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM preset_asset_versions WHERE id = ?", (version_id,)
        ).fetchone()
    return _preset_asset_version_row(row) if row else None


def get_active_preset_asset_version(
    preset_type: str, preset_id: str
) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM preset_asset_versions
            WHERE preset_type = ? AND preset_id = ? AND active = 1
            ORDER BY version DESC LIMIT 1
            """,
            (preset_type, preset_id),
        ).fetchone()
    return _preset_asset_version_row(row) if row else None


def get_preset_asset_version_by_number(
    preset_type: str,
    preset_id: str,
    version: int,
) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM preset_asset_versions
            WHERE preset_type = ? AND preset_id = ? AND version = ?
            """,
            (preset_type, preset_id, int(version)),
        ).fetchone()
    return _preset_asset_version_row(row) if row else None


def list_preset_asset_versions(
    preset_type: str, preset_id: str, limit: int = 100
) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM preset_asset_versions
            WHERE preset_type = ? AND preset_id = ?
            ORDER BY version DESC LIMIT ?
            """,
            (preset_type, preset_id, int(limit)),
        ).fetchall()
    return [_preset_asset_version_row(row) for row in rows]


def list_active_preset_asset_versions(preset_types: list[str]) -> list[dict]:
    """Batch-load active versions for catalog assembly."""
    kinds = [str(item) for item in preset_types if item]
    if not kinds:
        return []
    placeholders = ", ".join("?" for _ in kinds)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM preset_asset_versions
            WHERE active = 1 AND preset_type IN ({placeholders})
            ORDER BY preset_type, preset_id, version DESC, id DESC
            """,
            kinds,
        ).fetchall()
    return [_preset_asset_version_row(row) for row in rows]


def list_active_preset_asset_sources(preset_types: list[str]) -> list[dict]:
    """Batch-load active sources for catalog assembly."""
    kinds = [str(item) for item in preset_types if item]
    if not kinds:
        return []
    placeholders = ", ".join("?" for _ in kinds)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM preset_asset_sources
            WHERE active = 1 AND preset_type IN ({placeholders})
            ORDER BY preset_type, preset_id, revision DESC, id DESC
            """,
            kinds,
        ).fetchall()
    return [_preset_asset_source_row(row) for row in rows]


def summarize_preset_asset_candidates(
    preset_types: list[str],
    statuses: list[str] | None = None,
) -> list[dict]:
    """Aggregate active candidate counts for catalog queries."""
    kinds = [str(item) for item in preset_types if item]
    if not kinds:
        return []
    kind_placeholders = ", ".join("?" for _ in kinds)
    query = f"""
        SELECT
            preset_type,
            preset_id,
            status,
            COUNT(*) AS status_count,
            MAX(updated_at) AS updated_at
        FROM preset_asset_candidates
        WHERE preset_type IN ({kind_placeholders})
    """
    args: list = [*kinds]
    cleaned_statuses = [str(item) for item in statuses or [] if item]
    if cleaned_statuses:
        status_placeholders = ", ".join("?" for _ in cleaned_statuses)
        query += f" AND status IN ({status_placeholders})"
        args.extend(cleaned_statuses)
    query += """
        GROUP BY preset_type, preset_id, status
        ORDER BY preset_type, preset_id, status
    """
    with get_connection() as conn:
        rows = conn.execute(query, args).fetchall()
    aggregates: dict[tuple[str, str], dict] = {}
    running_statuses = {"queued", "preparing", "running", "cancel_requested"}
    for row in rows:
        key = (str(row["preset_type"]), str(row["preset_id"]))
        aggregate = aggregates.setdefault(
            key,
            {
                "preset_type": key[0],
                "preset_id": key[1],
                "candidate_count": 0,
                "ready_count": 0,
                "running_count": 0,
                "failed_count": 0,
                "candidate_status_counts": {},
                "updated_at": "",
            },
        )
        status = str(row["status"])
        count = int(row["status_count"] or 0)
        aggregate["candidate_status_counts"][status] = (
            int(aggregate["candidate_status_counts"].get(status) or 0) + count
        )
        aggregate["candidate_count"] += count
        if status == "ready":
            aggregate["ready_count"] += count
        if status in running_statuses:
            aggregate["running_count"] += count
        if status in {"failed", "interrupted"}:
            aggregate["failed_count"] += count
        updated_at = str(row["updated_at"] or "")
        if updated_at > str(aggregate["updated_at"] or ""):
            aggregate["updated_at"] = updated_at
    return list(aggregates.values())


def summarize_preset_asset_job_item_statuses(
    preset_types: list[str],
    statuses: list[str] | None = None,
) -> list[dict]:
    """Aggregate job-item counts by preset for catalog filtering."""
    kinds = [str(item) for item in preset_types if item]
    if not kinds:
        return []
    kind_placeholders = ", ".join("?" for _ in kinds)
    query = f"""
        SELECT
            preset_type,
            preset_id,
            status,
            COUNT(*) AS status_count,
            MAX(updated_at) AS updated_at
        FROM preset_asset_job_items
        WHERE preset_type IN ({kind_placeholders})
    """
    args: list = [*kinds]
    cleaned_statuses = [str(item) for item in statuses or [] if item]
    if cleaned_statuses:
        status_placeholders = ", ".join("?" for _ in cleaned_statuses)
        query += f" AND status IN ({status_placeholders})"
        args.extend(cleaned_statuses)
    query += """
        GROUP BY preset_type, preset_id, status
        ORDER BY preset_type, preset_id, status
    """
    with get_connection() as conn:
        rows = conn.execute(query, args).fetchall()
    aggregates: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (str(row["preset_type"]), str(row["preset_id"]))
        aggregate = aggregates.setdefault(
            key,
            {
                "preset_type": key[0],
                "preset_id": key[1],
                "task_status_counts": {},
                "task_status_updated_at": "",
            },
        )
        status = str(row["status"])
        count = int(row["status_count"] or 0)
        aggregate["task_status_counts"][status] = (
            int(aggregate["task_status_counts"].get(status) or 0) + count
        )
        updated_at = str(row["updated_at"] or "")
        if updated_at > str(aggregate["task_status_updated_at"] or ""):
            aggregate["task_status_updated_at"] = updated_at
    return list(aggregates.values())


def set_active_preset_asset_version(
    preset_type: str, preset_id: str, version_id: int
) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id FROM preset_asset_versions
            WHERE id = ? AND preset_type = ? AND preset_id = ?
            """,
            (version_id, preset_type, preset_id),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            """
            UPDATE preset_asset_versions SET active = 0
            WHERE preset_type = ? AND preset_id = ?
            """,
            (preset_type, preset_id),
        )
        conn.execute(
            "UPDATE preset_asset_versions SET active = 1 WHERE id = ?",
            (version_id,),
        )
    return get_active_preset_asset_version(preset_type, preset_id)


def get_preset_asset_write_lease(
    preset_type: str, preset_id: str
) -> dict | None:
    """Return the current formal-asset write lease, including expired rows."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM preset_asset_write_leases
            WHERE preset_type = ? AND preset_id = ?
            """,
            (preset_type, preset_id),
        ).fetchone()
    return dict(row) if row else None


def acquire_preset_asset_write_lease(
    preset_type: str,
    preset_id: str,
    operation: str,
    expected_revision: int,
    owner_token: str,
    *,
    candidate_id: int | None = None,
    target_version_id: int | None = None,
    ttl_seconds: int = 900,
) -> str:
    """Claim one formal-asset write slot with a database-backed lease.

    The lease is acquired before any public/dist file is touched. A different
    process can only take over after the lease expires, and the final commit is
    still guarded by the owner token and the expected active revision.
    """
    if operation not in {"adopt", "rollback"}:
        raise ValueError("unknown preset asset write operation")
    if not owner_token:
        raise ValueError("owner_token is required")
    now_epoch = time.time()
    expires_at = now_epoch + max(1, int(ttl_seconds))
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                DELETE FROM preset_asset_write_leases
                WHERE preset_type = ? AND preset_id = ? AND expires_at <= ?
                """,
                (preset_type, preset_id, now_epoch),
            )
            existing = conn.execute(
                """
                SELECT owner_token FROM preset_asset_write_leases
                WHERE preset_type = ? AND preset_id = ?
                """,
                (preset_type, preset_id),
            ).fetchone()
            if existing:
                conn.rollback()
                return "busy"

            active = conn.execute(
                """
                SELECT id FROM preset_asset_versions
                WHERE preset_type = ? AND preset_id = ? AND active = 1
                ORDER BY version DESC, id DESC LIMIT 1
                """,
                (preset_type, preset_id),
            ).fetchone()
            current_revision = int(active["id"]) if active else 0
            if current_revision != int(expected_revision):
                conn.rollback()
                return "revision_conflict"

            if operation == "adopt":
                candidate = conn.execute(
                    """
                    SELECT status FROM preset_asset_candidates
                    WHERE id = ? AND preset_type = ? AND preset_id = ?
                    """,
                    (candidate_id, preset_type, preset_id),
                ).fetchone()
                if not candidate or str(candidate["status"]) != "ready":
                    conn.rollback()
                    return "candidate_unavailable"
            else:
                target = conn.execute(
                    """
                    SELECT id FROM preset_asset_versions
                    WHERE id = ? AND preset_type = ? AND preset_id = ?
                    """,
                    (target_version_id, preset_type, preset_id),
                ).fetchone()
                if not target:
                    conn.rollback()
                    return "target_unavailable"

            conn.execute(
                """
                INSERT INTO preset_asset_write_leases (
                    preset_type, preset_id, operation, candidate_id,
                    target_version_id, expected_revision, owner_token,
                    acquired_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    preset_type,
                    preset_id,
                    operation,
                    candidate_id,
                    target_version_id,
                    int(expected_revision),
                    owner_token,
                    now_iso(),
                    expires_at,
                ),
            )
            conn.commit()
            return "acquired"
        except Exception:
            conn.rollback()
            raise


def release_preset_asset_write_lease(
    preset_type: str,
    preset_id: str,
    owner_token: str,
) -> bool:
    """Release a lease only when the caller still owns it."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            DELETE FROM preset_asset_write_leases
            WHERE preset_type = ? AND preset_id = ? AND owner_token = ?
            """,
            (preset_type, preset_id, owner_token),
        )
        return int(cursor.rowcount) > 0


def renew_preset_asset_write_lease(
    preset_type: str,
    preset_id: str,
    owner_token: str,
    *,
    ttl_seconds: int = 900,
) -> bool:
    """Renew an unexpired lease without reviving an expired ownership claim."""
    now_epoch = time.time()
    expires_at = now_epoch + max(1, int(ttl_seconds))
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE preset_asset_write_leases
            SET expires_at = ?
            WHERE preset_type = ? AND preset_id = ? AND owner_token = ?
              AND expires_at > ?
            """,
            (
                expires_at,
                preset_type,
                preset_id,
                owner_token,
                now_epoch,
            ),
        )
        conn.commit()
        return int(cursor.rowcount) == 1


def commit_preset_asset_adoption(
    preset_type: str,
    preset_id: str,
    candidate_id: int,
    owner_token: str,
    public_path: str,
    dist_path: str,
    mime_type: str,
    width: int,
    height: int,
    sha256: str,
    expected_version_number: int | None = None,
) -> dict | None:
    """Atomically activate a version, mark its candidate adopted, and audit it."""
    timestamp = now_iso()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            lease = conn.execute(
                """
                SELECT operation, candidate_id, expected_revision
                FROM preset_asset_write_leases
                WHERE preset_type = ? AND preset_id = ? AND owner_token = ?
                """,
                (preset_type, preset_id, owner_token),
            ).fetchone()
            if (
                not lease
                or str(lease["operation"]) != "adopt"
                or int(lease["candidate_id"] or 0) != int(candidate_id)
            ):
                conn.rollback()
                return None

            active = conn.execute(
                """
                SELECT id FROM preset_asset_versions
                WHERE preset_type = ? AND preset_id = ? AND active = 1
                ORDER BY version DESC, id DESC LIMIT 1
                """,
                (preset_type, preset_id),
            ).fetchone()
            current_revision = int(active["id"]) if active else 0
            if current_revision != int(lease["expected_revision"]):
                conn.rollback()
                return None

            candidate = conn.execute(
                """
                SELECT status FROM preset_asset_candidates
                WHERE id = ? AND preset_type = ? AND preset_id = ?
                """,
                (candidate_id, preset_type, preset_id),
            ).fetchone()
            if not candidate or str(candidate["status"]) != "ready":
                conn.rollback()
                return None

            version_number = int(
                conn.execute(
                    """
                    SELECT COALESCE(MAX(version), 0) + 1
                    FROM preset_asset_versions
                    WHERE preset_type = ? AND preset_id = ?
                    """,
                    (preset_type, preset_id),
                ).fetchone()[0]
            )
            if (
                expected_version_number is not None
                and version_number != int(expected_version_number)
            ):
                conn.rollback()
                return None
            conn.execute(
                """
                UPDATE preset_asset_versions SET active = 0
                WHERE preset_type = ? AND preset_id = ?
                """,
                (preset_type, preset_id),
            )
            cursor = conn.execute(
                """
                INSERT INTO preset_asset_versions (
                    preset_type, preset_id, version, candidate_id, public_path,
                    dist_path, mime_type, width, height, sha256, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    preset_type,
                    preset_id,
                    version_number,
                    candidate_id,
                    public_path,
                    dist_path,
                    mime_type,
                    int(width),
                    int(height),
                    sha256,
                    timestamp,
                ),
            )
            version_id = int(cursor.lastrowid)
            updated = conn.execute(
                """
                UPDATE preset_asset_candidates
                SET status = 'adopted', error = NULL, updated_at = ?
                WHERE id = ? AND status = 'ready'
                """,
                (timestamp, candidate_id),
            )
            if int(updated.rowcount) != 1:
                conn.rollback()
                return None
            conn.execute(
                """
                INSERT INTO preset_asset_audit (
                    event, preset_type, preset_id, candidate_id, job_id,
                    detail_json, created_at
                ) VALUES ('candidate_adopted', ?, ?, ?, NULL, ?, ?)
                """,
                (
                    preset_type,
                    preset_id,
                    candidate_id,
                    json.dumps(
                        {"version_id": version_id, "version": version_number},
                        ensure_ascii=False,
                    ),
                    timestamp,
                ),
            )
            conn.execute(
                """
                DELETE FROM preset_asset_write_leases
                WHERE preset_type = ? AND preset_id = ? AND owner_token = ?
                """,
                (preset_type, preset_id, owner_token),
            )
            conn.commit()
            return {"version_id": version_id, "version": version_number}
        except Exception:
            conn.rollback()
            raise


def commit_preset_asset_rollback(
    preset_type: str,
    preset_id: str,
    target_version_id: int,
    owner_token: str,
) -> bool:
    """Atomically activate an archived version and write its audit record."""
    timestamp = now_iso()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            lease = conn.execute(
                """
                SELECT operation, target_version_id, expected_revision
                FROM preset_asset_write_leases
                WHERE preset_type = ? AND preset_id = ? AND owner_token = ?
                """,
                (preset_type, preset_id, owner_token),
            ).fetchone()
            if (
                not lease
                or str(lease["operation"]) != "rollback"
                or int(lease["target_version_id"] or 0) != int(target_version_id)
            ):
                conn.rollback()
                return False
            active = conn.execute(
                """
                SELECT id FROM preset_asset_versions
                WHERE preset_type = ? AND preset_id = ? AND active = 1
                ORDER BY version DESC, id DESC LIMIT 1
                """,
                (preset_type, preset_id),
            ).fetchone()
            current_revision = int(active["id"]) if active else 0
            if current_revision != int(lease["expected_revision"]):
                conn.rollback()
                return False
            target = conn.execute(
                """
                SELECT id, version, candidate_id
                FROM preset_asset_versions
                WHERE id = ? AND preset_type = ? AND preset_id = ?
                """,
                (target_version_id, preset_type, preset_id),
            ).fetchone()
            if not target:
                conn.rollback()
                return False
            conn.execute(
                """
                UPDATE preset_asset_versions SET active = 0
                WHERE preset_type = ? AND preset_id = ?
                """,
                (preset_type, preset_id),
            )
            conn.execute(
                "UPDATE preset_asset_versions SET active = 1 WHERE id = ?",
                (target_version_id,),
            )
            conn.execute(
                """
                INSERT INTO preset_asset_audit (
                    event, preset_type, preset_id, candidate_id, job_id,
                    detail_json, created_at
                ) VALUES ('version_rolled_back', ?, ?, ?, NULL, ?, ?)
                """,
                (
                    preset_type,
                    preset_id,
                    target["candidate_id"],
                    json.dumps(
                        {
                            "version_id": int(target["id"]),
                            "version": int(target["version"]),
                        },
                        ensure_ascii=False,
                    ),
                    timestamp,
                ),
            )
            conn.execute(
                """
                DELETE FROM preset_asset_write_leases
                WHERE preset_type = ? AND preset_id = ? AND owner_token = ?
                """,
                (preset_type, preset_id, owner_token),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise


def discard_preset_asset_candidate(candidate_id: int) -> bool:
    """Discard a candidate without overwriting a concurrent adoption."""
    now_epoch = time.time()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            """
            UPDATE preset_asset_candidates
            SET status = 'discarded', updated_at = ?
            WHERE id = ? AND status != 'adopted'
              AND NOT EXISTS (
                  SELECT 1 FROM preset_asset_write_leases AS lease
                  WHERE lease.preset_type = preset_asset_candidates.preset_type
                    AND lease.preset_id = preset_asset_candidates.preset_id
                    AND lease.expires_at > ?
              )
            """,
            (now_iso(), int(candidate_id), now_epoch),
        )
        conn.commit()
        return int(cursor.rowcount) == 1


def create_preset_asset_job(
    job_id: str,
    total: int,
    items: list[dict],
    *,
    idempotency_key: str | None,
    request_hash: str,
    payload: dict | None = None,
) -> dict:
    """Atomically create one workshop job and its idempotency record."""
    timestamp = now_iso()
    payload_json = json.dumps(payload or {}, ensure_ascii=False)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if idempotency_key:
            existing = conn.execute(
                """
                SELECT job_id, request_hash
                FROM preset_asset_job_requests
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing:
                conn.rollback()
                return {
                    "job_id": str(existing["job_id"]),
                    "created": False,
                    "conflict": existing["request_hash"] != request_hash,
                }
        conn.execute(
            """
            INSERT INTO background_jobs (
                job_id, kind, status, total, done, current, error, stop_requested,
                payload, created_at, updated_at, finished_at
            ) VALUES (?, 'preset_asset', 'queued', ?, 0, '等待队列', NULL, 0, ?, ?, ?, NULL)
            """,
            (job_id, int(total), payload_json, timestamp, timestamp),
        )
        for item_index, item in enumerate(items):
            conn.execute(
                """
                INSERT INTO preset_asset_job_items (
                    job_id, item_index, preset_type, preset_id, candidate_id,
                    status, params_json, error, attempt_count, next_retry_at,
                    retry_backoff_seconds, last_error_code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, 'queued', ?, NULL, 0, NULL, 0, NULL, ?, ?)
                """,
                (
                    job_id,
                    item_index,
                    str(item["preset_type"]),
                    str(item["preset_id"]),
                    json.dumps(item.get("params") or {}, ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
        if idempotency_key:
            conn.execute(
                """
                INSERT INTO preset_asset_job_requests (
                    job_id, idempotency_key, request_hash, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (job_id, idempotency_key, request_hash, timestamp),
            )
        conn.execute(
            """
            INSERT INTO preset_asset_audit (
                event, preset_type, preset_id, candidate_id, job_id,
                detail_json, created_at
            ) VALUES ('job_created', '', '', NULL, ?, ?, ?)
            """,
            (
                job_id,
                json.dumps(
                    {
                        "items": len(items),
                        "total": int(total),
                        "request_hash": request_hash,
                    },
                    ensure_ascii=False,
                ),
                timestamp,
            ),
        )
        conn.commit()
    return {"job_id": job_id, "created": True, "conflict": False}


def insert_preset_asset_job_item(
    job_id: str,
    item_index: int,
    preset_type: str,
    preset_id: str,
    status: str,
    params: dict,
    candidate_id: int | None = None,
    error: str | None = None,
) -> None:
    timestamp = now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO preset_asset_job_items (
                job_id, item_index, preset_type, preset_id, candidate_id,
                status, params_json, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                int(item_index),
                preset_type,
                preset_id,
                candidate_id,
                status,
                json.dumps(params or {}, ensure_ascii=False),
                error,
                timestamp,
                timestamp,
            ),
        )


def update_preset_asset_job_item(
    job_id: str,
    item_index: int,
    **changes,
) -> dict | None:
    safe_fields = {
        "candidate_id",
        "status",
        "params_json",
        "error",
        "attempt_count",
        "next_retry_at",
        "retry_backoff_seconds",
        "last_error_code",
    }
    safe = {key: value for key, value in changes.items() if key in safe_fields}
    if safe:
        assignments = ", ".join(f"{key} = ?" for key in safe)
        values = list(safe.values()) + [now_iso(), job_id, int(item_index)]
        with get_connection() as conn:
            conn.execute(
                f"UPDATE preset_asset_job_items SET {assignments}, updated_at = ? "
                "WHERE job_id = ? AND item_index = ?",
                values,
            )
    return get_preset_asset_job_item(job_id, item_index)


def start_preset_asset_job_item_attempt(
    job_id: str,
    item_index: int,
) -> dict | None:
    """Mark one queued item as running and increment its attempt counter."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE preset_asset_job_items
            SET status = 'running', error = NULL, next_retry_at = NULL,
                retry_backoff_seconds = 0, last_error_code = NULL,
                attempt_count = attempt_count + 1, updated_at = ?
            WHERE job_id = ? AND item_index = ?
              AND status IN ('queued', 'preparing')
            """,
            (now_iso(), job_id, int(item_index)),
        )
        if cursor.rowcount != 1:
            return None
    return get_preset_asset_job_item(job_id, item_index)


def mark_preset_asset_job_items_interrupted(
    job_id: str,
    item_indexes: set[int],
    reason: str,
) -> int:
    """Mark selected active workshop items as interrupted after restart."""
    indexes = sorted({int(index) for index in item_indexes})
    if not indexes:
        return 0
    placeholders = ", ".join("?" for _ in indexes)
    with get_connection() as conn:
        cursor = conn.execute(
            f"""
            UPDATE preset_asset_job_items
            SET status = 'interrupted', error = ?, updated_at = ?
            WHERE job_id = ? AND item_index IN ({placeholders})
              AND status IN ('queued', 'preparing', 'running', 'cancel_requested')
            """,
            (reason, now_iso(), job_id, *indexes),
        )
        return int(cursor.rowcount)


def mark_preset_asset_job_active_candidates_interrupted(
    job_id: str,
    reason: str,
) -> int:
    """Mark active candidates belonging to one interrupted workshop job."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE preset_asset_candidates
            SET status = 'interrupted', error = ?, updated_at = ?
            WHERE job_id = ?
              AND status IN ('queued', 'preparing', 'running', 'cancel_requested')
            """,
            (reason, now_iso(), job_id),
        )
        return int(cursor.rowcount)


def mark_preset_asset_job_interrupted(job_id: str, reason: str) -> int:
    """Mark one active workshop job and all of its active work as interrupted."""
    timestamp = now_iso()
    with get_connection() as conn:
        jobs = conn.execute(
            """
            UPDATE background_jobs
            SET status = 'interrupted', error = ?, updated_at = ?, finished_at = ?
            WHERE job_id = ? AND kind = 'preset_asset'
              AND status IN ('queued', 'preparing', 'running', 'cancel_requested')
            """,
            (reason, timestamp, timestamp, job_id),
        )
        candidates = conn.execute(
            """
            UPDATE preset_asset_candidates
            SET status = 'interrupted', error = ?, updated_at = ?
            WHERE job_id = ?
              AND status IN ('queued', 'preparing', 'running', 'cancel_requested')
            """,
            (reason, timestamp, job_id),
        )
        items = conn.execute(
            """
            UPDATE preset_asset_job_items
            SET status = 'interrupted', error = ?, updated_at = ?
            WHERE job_id = ?
              AND status IN ('queued', 'preparing', 'running', 'cancel_requested')
            """,
            (reason, timestamp, job_id),
        )
    return max(int(jobs.rowcount), int(candidates.rowcount), int(items.rowcount))


def _preset_asset_job_item_row(row: sqlite3.Row) -> dict:
    item = dict(row)
    try:
        item["params"] = json.loads(item.get("params_json") or "{}")
    except json.JSONDecodeError:
        item["params"] = {}
    return item


def get_preset_asset_job_item(job_id: str, item_index: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM preset_asset_job_items
            WHERE job_id = ? AND item_index = ?
            """,
            (job_id, int(item_index)),
        ).fetchone()
    return _preset_asset_job_item_row(row) if row else None


def list_preset_asset_job_items(job_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM preset_asset_job_items
            WHERE job_id = ? ORDER BY item_index
            """,
            (job_id,),
        ).fetchall()
    return [_preset_asset_job_item_row(row) for row in rows]


def mark_interrupted_preset_asset_jobs() -> int:
    """后端重启后把工坊运行中记录标记为中断，不自动恢复 GPU。"""
    timestamp = now_iso()
    with get_connection() as conn:
        jobs = conn.execute(
            """
            UPDATE background_jobs
            SET status = 'interrupted', error = '后端重启中断，任务无法继续',
                updated_at = ?, finished_at = ?
            WHERE kind = 'preset_asset'
              AND status IN ('queued', 'preparing', 'running', 'cancel_requested')
            """,
            (timestamp, timestamp),
        )
        candidates = conn.execute(
            """
            UPDATE preset_asset_candidates
            SET status = 'interrupted', error = '后端重启中断，任务无法继续',
                updated_at = ?
            WHERE status IN ('queued', 'preparing', 'running', 'cancel_requested')
            """,
            (timestamp,),
        )
        items = conn.execute(
            """
            UPDATE preset_asset_job_items
            SET status = 'interrupted', error = '后端重启中断，任务无法继续',
                updated_at = ?
            WHERE status IN ('queued', 'preparing', 'running', 'cancel_requested')
            """,
            (timestamp,),
        )
    return max(int(jobs.rowcount), int(candidates.rowcount), int(items.rowcount))


def add_preset_asset_audit(
    event: str,
    preset_type: str = "",
    preset_id: str = "",
    candidate_id: int | None = None,
    job_id: str | None = None,
    detail: dict | None = None,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO preset_asset_audit (
                event, preset_type, preset_id, candidate_id, job_id,
                detail_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event,
                preset_type,
                preset_id,
                candidate_id,
                job_id,
                json.dumps(detail or {}, ensure_ascii=False),
                now_iso(),
            ),
        )
        return int(cursor.lastrowid)


def list_preset_asset_audit(
    preset_type: str,
    preset_id: str,
    limit: int = 100,
) -> list[dict]:
    """Return recent workshop audit events for one preset."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM preset_asset_audit
            WHERE preset_type = ? AND preset_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (preset_type, preset_id, int(limit)),
        ).fetchall()
    items: list[dict] = []
    for row in rows:
        item = dict(row)
        try:
            item["detail"] = json.loads(item.get("detail_json") or "{}")
        except json.JSONDecodeError:
            item["detail"] = {}
        item.pop("detail_json", None)
        items.append(item)
    return items


def summarize_preset_asset_audit_events() -> dict[str, int]:
    """Count workshop audit event types without loading their details."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT event, COUNT(*) AS event_count
            FROM preset_asset_audit
            GROUP BY event
            ORDER BY event
            """
        ).fetchall()
    return {str(row["event"]): int(row["event_count"] or 0) for row in rows}


def backup_database(dest_dir) -> dict:
    """用 SQLite 在线备份机制复制当前数据库，返回备份信息。"""
    from pathlib import Path

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    backup_path = dest / f"rider_studio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    source = sqlite3.connect(str(DB_PATH))
    target = sqlite3.connect(str(backup_path))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return {
        "path": str(backup_path),
        "size_mb": round(backup_path.stat().st_size / (1024 * 1024), 2),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
