"""JSON-backed character memory.

Zero dependencies beyond numpy. Records live in
``storage/memory/<project_id>/characters.json``; queries are brute-force cosine
over the embeddings, which is more than fast enough for a handful of characters
per comic.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Sequence

from ..config import get_settings
from ..embeddings import cosine_similarity
from ..logging_config import get_logger
from .base import CharacterMemory, MemoryRecord

log = get_logger("memory.json")


class JsonCharacterMemory(CharacterMemory):
    backend = "json"

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._lock = threading.RLock()
        self.path = get_settings().memory_dir / project_id / "characters.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, MemoryRecord] = {}
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("could not read character memory %s: %s", self.path, exc)
            return
        for character_id, payload in (raw.get("characters") or {}).items():
            self._records[character_id] = MemoryRecord(
                character_id=character_id,
                embedding=list(payload.get("embedding") or []),
                metadata=dict(payload.get("metadata") or {}),
                document=payload.get("document", ""),
            )
        log.debug("loaded %d character records for project %s", len(self._records), self.project_id)

    def _save(self) -> None:
        payload = {
            "project_id": self.project_id,
            "backend": self.backend,
            "characters": {
                cid: {
                    "embedding": record.embedding,
                    "metadata": record.metadata,
                    "document": record.document,
                }
                for cid, record in self._records.items()
            },
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self.path)

    # -- interface ---------------------------------------------------------
    def upsert(
        self,
        character_id: str,
        embedding: Sequence[float],
        metadata: dict[str, Any] | None = None,
        document: str = "",
    ) -> None:
        with self._lock:
            self._records[character_id] = MemoryRecord(
                character_id=character_id,
                embedding=[float(v) for v in embedding],
                metadata=dict(metadata or {}),
                document=document,
            )
            self._save()

    def get(self, character_id: str) -> MemoryRecord | None:
        with self._lock:
            return self._records.get(character_id)

    def all(self) -> list[MemoryRecord]:
        with self._lock:
            return list(self._records.values())

    def query(self, embedding: Sequence[float], k: int = 3) -> list[tuple[MemoryRecord, float]]:
        with self._lock:
            records = list(self._records.values())
        scored = [
            (record, cosine_similarity(embedding, record.embedding))
            for record in records
            if record.embedding
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:k]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            if self.path.exists():
                self.path.unlink()


def build_json_memory(project_id: str) -> JsonCharacterMemory:
    return JsonCharacterMemory(project_id)
