from __future__ import annotations

import json
import sqlite3
from pathlib import Path


db = Path(r"D:\workSpace\code\ai-workbench\AIproduct\rider_studio.db")
conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    """
    SELECT id, original_path, preview_path, thumbnail_path, params_json
    FROM preset_asset_candidates
    WHERE id IN (1502, 1503)
    ORDER BY id
    """
).fetchall()
print(
    json.dumps(
        [
            {
                "id": row["id"],
                "original_path": row["original_path"],
                "preview_path": row["preview_path"],
                "thumbnail_path": row["thumbnail_path"],
                "params": json.loads(row["params_json"] or "{}"),
            }
            for row in rows
        ],
        ensure_ascii=False,
        indent=2,
    )
)
conn.close()
