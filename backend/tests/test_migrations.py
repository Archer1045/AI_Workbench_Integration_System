"""SQLite 迁移机制测试：幂等执行且版本号递增。"""
from __future__ import annotations

import json

import database


def _fresh_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "migration_test.db")
    with database.get_connection() as conn:
        conn.executescript(database._SCHEMA)


def test_migrations_idempotent(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    database.run_migrations()
    first_version = database.get_connection().execute("PRAGMA user_version").fetchone()[0]
    assert first_version == database.SCHEMA_VERSION
    database.run_migrations()
    second_version = database.get_connection().execute("PRAGMA user_version").fetchone()[0]
    assert second_version == database.SCHEMA_VERSION
    tables = {
        row["name"]
        for row in database.get_connection().execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "background_jobs" in tables
    assert "preset_asset_write_leases" in tables
    lease_columns = {
        row["name"]
        for row in database.get_connection()
        .execute("PRAGMA table_info(preset_asset_write_leases)")
        .fetchall()
    }
    assert {
        "preset_type",
        "preset_id",
        "operation",
        "candidate_id",
        "target_version_id",
        "expected_revision",
        "owner_token",
        "acquired_at",
        "expires_at",
    } <= lease_columns
    prompt_columns = {
        row["name"]
        for row in database.get_connection().execute("PRAGMA table_info(prompt_sets)").fetchall()
    }
    assert "composition_json" in prompt_columns
    draw_columns = {
        row["name"]
        for row in database.get_connection().execute("PRAGMA table_info(draw_records)").fetchall()
    }
    assert {
        "edit_mode",
        "source_record_id",
        "source_image_path",
        "mask_image_path",
        "masked_prompt",
        "inpaint_denoise",
        "edit_params_json",
    } <= draw_columns
    batch_columns = {
        row["name"]
        for row in database.get_connection().execute("PRAGMA table_info(batch_jobs)").fetchall()
    }
    assert "mode" in batch_columns
    aemeath = database.get_character_appearance_preset(
        "builtin_character_wuthering_waves_aemeath"
    )
    assert aemeath is not None
    assert aemeath["appearance_tags"][0] == "aemeath_(wuthering_waves)"
    bronya = database.get_character_appearance_preset("builtin_character_hsr_bronya")
    assert bronya is not None
    assert bronya["appearance_tags"][0] == "bronya_(honkai:_star_rail)"
    ulrich = database.get_character_appearance_preset(
        "builtin_character_azur_lane_ulrich_von_hutten"
    )
    assert ulrich is not None
    assert ulrich["appearance_tags"][0] == "ulrich_von_hutten_(azur_lane)"


    gotz = database.get_character_appearance_preset(
        "builtin_character_azur_lane_gotz_von_berlichingen"
    )
    assert gotz is not None
    assert gotz["appearance_tags"][0] == "gotz_von_berlichingen_(azur_lane)"
    napoli = database.get_character_appearance_preset(
        "builtin_character_azur_lane_napoli"
    )
    assert napoli is not None
    assert napoli["appearance_tags"][0] == "napoli_(azur_lane)"
    alsace = database.get_character_appearance_preset(
        "builtin_character_azur_lane_alsace"
    )
    assert alsace is not None
    assert alsace["appearance_tags"][0] == "alsace_(azur_lane)"
    sirius = database.get_character_appearance_preset(
        "builtin_character_azur_lane_sirius"
    )
    assert sirius is not None
    assert sirius["appearance_tags"][0] == "sirius_(azur_lane)"
    sakawa = database.get_character_appearance_preset(
        "builtin_character_azur_lane_sakawa"
    )
    assert sakawa is not None
    assert sakawa["appearance_tags"][0] == "sakawa_(azur_lane)"
    asama = database.get_character_appearance_preset(
        "builtin_character_azur_lane_asama"
    )
    assert asama is not None
    assert asama["appearance_tags"][0] == "asama_(azur_lane)"
    zhen_hai = database.get_character_appearance_preset(
        "builtin_character_azur_lane_zhen_hai"
    )
    assert zhen_hai is not None
    assert zhen_hai["appearance_tags"][0] == "zhen_hai_(azur_lane)"
    maggiore = database.get_character_appearance_preset(
        "builtin_character_azur_lane_maggiore_baracca"
    )
    assert maggiore is not None
    assert maggiore["appearance_tags"][0] == "maggiore_baracca_(azur_lane)"
    typhon = database.get_character_appearance_preset(
        "builtin_character_arknights_typhon"
    )
    assert typhon is not None
    assert typhon["appearance_tags"][0] == "typhon_(arknights)"
    virtuosa = database.get_character_appearance_preset(
        "builtin_character_arknights_virtuosa"
    )
    assert virtuosa is not None
    assert virtuosa["appearance_tags"][0] == "virtuosa_(arknights)"
    assert "black eyes" in virtuosa["appearance_tags"]
    assert "amber pupils" in virtuosa["appearance_tags"]
    assert "amber eyes" not in virtuosa["appearance_tags"]
    dania = database.get_character_appearance_preset(
        "builtin_character_wuthering_waves_dania"
    )
    assert dania is not None
    assert dania["appearance_tags"][0] == "dania_(wuthering_waves)"
    iuno = database.get_character_appearance_preset(
        "builtin_character_wuthering_waves_iuno"
    )
    assert iuno is not None
    assert iuno["appearance_tags"][0] == "iuno_(wuthering_waves)"
    female_rover = database.get_character_appearance_preset(
        "builtin_character_wuthering_waves_female_rover"
    )
    assert female_rover is not None
    assert female_rover["appearance_tags"][0] == "female_rover_(wuthering_waves)"
    typhon_a1 = database.get_character_appearance_preset(
        "builtin_character_fgo_2801100_pretender_a1"
    )
    assert typhon_a1 is not None
    assert typhon_a1["appearance_tags"][0] == "typhon_ephemeros_(fate)"
    assert typhon_a1["work"] == "Fate/Grand Order"
    lady_avalon_a1 = database.get_character_appearance_preset(
        "builtin_character_fgo_2800300_pretender_a1"
    )
    assert lady_avalon_a1 is not None
    assert "一破（A1）" in lady_avalon_a1["name"]
    lady_avalon_a2 = database.get_character_appearance_preset(
        "builtin_character_fgo_2800300_pretender_a2"
    )
    assert lady_avalon_a2 is not None
    assert "二破（A2）" in lady_avalon_a2["name"]
    kiyohime_expected = {
        "builtin_character_fgo_701300_berserker_a3": ("red eyes", "三破（A3）"),
        "builtin_character_fgo_701300_berserker_a4": ("yellow eyes", "满破（A4）"),
        "builtin_character_fgo_302500_lancer_a3": ("red eyes", "三破（A3）"),
        "builtin_character_fgo_302500_lancer_a4": ("red eyes", "满破（A4）"),
    }
    for preset_id, (eye_color, form_label) in kiyohime_expected.items():
        kiyohime = database.get_character_appearance_preset(preset_id)
        assert kiyohime is not None
        assert form_label in kiyohime["name"]
        assert eye_color in kiyohime["appearance_tags"]
        assert "black dragon horns" in kiyohime["appearance_tags"]
        if preset_id != "builtin_character_fgo_701300_berserker_a4":
            assert "yellow eyes" not in kiyohime["appearance_tags"]
    assert (
        database.get_character_appearance_preset(
            "builtin_character_fgo_2800300_pretender_a4"
        )
        is None
    )
    genshin = database.get_character_appearance_preset(
        "builtin_character_genshin_columbina"
    )
    assert genshin is not None
    assert genshin["name"] == "哥伦比娅"
    assert genshin["work"] == "原神"
    assert "dark purple hair" in genshin["appearance_tags"]
    assert "pink hair" not in genshin["appearance_tags"]
    assert genshin["outfit_id"] == "outfit_genshin_columbina_default"
    assert "black and white dress" not in genshin["appearance_tags"]
    lady_avalon_outfit = database.get_character_appearance_preset(
        "builtin_character_fgo_2800300_pretender_a1"
    )
    assert lady_avalon_outfit is not None
    assert lady_avalon_outfit["outfit_id"] == "outfit_fgo_2800300_pretender_a1_default"
    assert "white formal dress" not in lady_avalon_outfit["appearance_tags"]

def test_background_job_crud(tmp_path, monkeypatch):
    _fresh_db(tmp_path, monkeypatch)
    database.run_migrations()
    job = {
        "job_id": "job-1",
        "kind": "draw",
        "status": "running",
        "total": 2,
        "done": 1,
        "current": "",
        "error": None,
        "stop_requested": False,
        "payload": {"seed": 123},
        "created_at": "2026-09-02 10:00:00",
        "updated_at": "2026-09-02 10:00:00",
        "finished_at": None,
    }
    database.save_background_job(job)
    loaded = database.get_background_job("job-1")
    assert loaded["kind"] == "draw"
    assert loaded["payload"]["seed"] == 123
    rows = database.list_background_jobs(status="running")
    assert len(rows) == 1


def test_inpaint_migration_upgrades_legacy_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "legacy.db")
    with database.get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE draw_records (id INTEGER PRIMARY KEY, status TEXT);
            CREATE TABLE batch_jobs (batch_id TEXT PRIMARY KEY, status TEXT);
            """
        )
        database._migration_022_inpaint(conn)
        draw_columns = {row["name"] for row in conn.execute("PRAGMA table_info(draw_records)")}
        batch_columns = {row["name"] for row in conn.execute("PRAGMA table_info(batch_jobs)")}
    assert {"edit_mode", "source_record_id", "mask_image_path", "edit_params_json"} <= draw_columns
    assert "mode" in batch_columns


def test_character_outfit_migration_upgrades_legacy_table(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "legacy_character_presets.db")
    with database.get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE character_appearance_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                preset_id TEXT NOT NULL,
                name TEXT NOT NULL,
                work TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '自由备注',
                appearance_tags TEXT NOT NULL DEFAULT '[]',
                clothing_tags TEXT NOT NULL DEFAULT '[]',
                expression_tags TEXT NOT NULL DEFAULT '[]',
                note TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'user',
                version INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(preset_id, version)
            );
            """
        )
        database._migration_029_character_outfit_links(conn)
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(character_appearance_presets)"
            ).fetchall()
        }
        columbina = conn.execute(
            """
            SELECT appearance_tags, outfit_id
            FROM character_appearance_presets
            WHERE preset_id = 'builtin_character_genshin_columbina'
            ORDER BY version DESC LIMIT 1
            """
        ).fetchone()
    assert "outfit_id" in columns
    assert columbina is not None
    assert columbina["outfit_id"] == "outfit_genshin_columbina_default"
    assert "black and white dress" not in columbina["appearance_tags"]


def test_character_visual_correction_migration_upgrades_stale_rows(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "visual_corrections.db")
    with database.get_connection() as conn:
        conn.executescript(database._SCHEMA)
        stale = {
            "builtin_character_fgo_302500_lancer_a4": [
                "kiyohime_(lancer)_(fate)",
                "long white hair",
                "yellow eyes",
            ],
            "builtin_character_arknights_virtuosa": [
                "virtuosa_(arknights)",
                "very long black hair",
                "amber eyes",
            ],
        }
        for preset_id, tags in stale.items():
            conn.execute(
                """
                INSERT INTO character_appearance_presets (
                    preset_id, name, work, category, appearance_tags,
                    clothing_tags, expression_tags, outfit_id, note, source,
                    version, enabled, created_at, updated_at
                ) VALUES (?, ?, '', '角色', ?, '[]', '[]', '', 'stale',
                          'builtin', 1, 1, '', '')
                """,
                (preset_id, preset_id, json.dumps(tags)),
            )

        database._migration_031_character_visual_corrections(conn)
        lancer = conn.execute(
            """
            SELECT appearance_tags FROM character_appearance_presets
            WHERE preset_id = 'builtin_character_fgo_302500_lancer_a4'
            ORDER BY version DESC LIMIT 1
            """
        ).fetchone()
        virtuosa = conn.execute(
            """
            SELECT appearance_tags FROM character_appearance_presets
            WHERE preset_id = 'builtin_character_arknights_virtuosa'
            ORDER BY version DESC LIMIT 1
            """
        ).fetchone()

    lancer_tags = json.loads(lancer["appearance_tags"])
    virtuosa_tags = json.loads(virtuosa["appearance_tags"])
    assert "red eyes" in lancer_tags
    assert "yellow eyes" not in lancer_tags
    assert "black dragon horns" in lancer_tags
    assert "black eyes" in virtuosa_tags
    assert "amber pupils" in virtuosa_tags
    assert "amber eyes" not in virtuosa_tags
