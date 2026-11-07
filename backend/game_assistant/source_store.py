"""File-backed source snapshots for the public Game Assistant knowledge base."""
from __future__ import annotations

import json
from pathlib import Path

import config

from .source_domain import SourceRecord


class SourceStore:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or config.GAME_ASSISTANT_SOURCE_DIR)

    def _path(self, source_id: str) -> Path:
        safe = "".join(ch for ch in source_id if ch.isalnum() or ch in "-_")
        if not safe or safe != source_id:
            raise ValueError("invalid source id")
        return self.root / f"{safe}.json"

    def save(self, record: SourceRecord) -> SourceRecord:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(record.source_id)
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)
        return record

    def get(self, source_id: str) -> SourceRecord | None:
        path = self._path(source_id)
        if not path.exists():
            return None
        return SourceRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def list(self, *, limit: int = 50) -> list[SourceRecord]:
        if not self.root.exists():
            return []
        records: list[SourceRecord] = []
        for path in sorted(self.root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
            try:
                records.append(SourceRecord.model_validate(json.loads(path.read_text(encoding="utf-8"))))
            except Exception:
                continue
        return records
