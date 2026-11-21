"""ChromaDB-backed character memory.

Same interface as the JSON store, but with a real persistent vector index, which
is what the proposal specifies. Selected automatically when ``chromadb`` is
importable and ``VECTOR_STORE`` is ``auto`` or ``chroma``.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..config import get_settings
from ..logging_config import get_logger
from .base import CharacterMemory, MemoryRecord, similarity_from_distance

log = get_logger("memory.chroma")


def chroma_available() -> bool:
    try:
        import chromadb  # noqa: F401
    except Exception:
        return False
    return True


class ChromaCharacterMemory(CharacterMemory):
    backend = "chroma"

    def __init__(self, project_id: str) -> None:
        import chromadb

        self.project_id = project_id
        self.client = chromadb.PersistentClient(path=str(get_settings().resolved_chroma_dir))
        self.collection = self.client.get_or_create_collection(
            name=f"characters_{project_id}",
            metadata={"hnsw:space": "cosine"},
        )
        log.info(
            "chroma collection 'characters_%s' ready (%d records)",
            project_id,
            self.collection.count(),
        )

    def upsert(
        self,
        character_id: str,
        embedding: Sequence[float],
        metadata: dict[str, Any] | None = None,
        document: str = "",
    ) -> None:
        clean_metadata = {
            k: (v if isinstance(v, (str, int, float, bool)) else str(v))
            for k, v in (metadata or {}).items()
        }
        self.collection.upsert(
            ids=[character_id],
            embeddings=[[float(v) for v in embedding]],
            metadatas=[clean_metadata] if clean_metadata else None,
            documents=[document] if document else None,
        )

    def get(self, character_id: str) -> MemoryRecord | None:
        result = self.collection.get(ids=[character_id], include=["embeddings", "metadatas", "documents"])
        ids = result.get("ids") or []
        if not ids:
            return None
        embeddings = result.get("embeddings")
        return MemoryRecord(
            character_id=character_id,
            embedding=[float(v) for v in (embeddings[0] if embeddings is not None and len(embeddings) else [])],
            metadata=dict((result.get("metadatas") or [{}])[0] or {}),
            document=((result.get("documents") or [""])[0]) or "",
        )

    def all(self) -> list[MemoryRecord]:
        result = self.collection.get(include=["embeddings", "metadatas", "documents"])
        ids = result.get("ids") or []
        embeddings = result.get("embeddings")
        metadatas = result.get("metadatas") or [{}] * len(ids)
        documents = result.get("documents") or [""] * len(ids)
        records: list[MemoryRecord] = []
        for i, character_id in enumerate(ids):
            embedding = []
            if embeddings is not None and len(embeddings) > i and embeddings[i] is not None:
                embedding = [float(v) for v in embeddings[i]]
            records.append(
                MemoryRecord(
                    character_id=character_id,
                    embedding=embedding,
                    metadata=dict(metadatas[i] or {}),
                    document=documents[i] or "",
                )
            )
        return records

    def query(self, embedding: Sequence[float], k: int = 3) -> list[tuple[MemoryRecord, float]]:
        if self.collection.count() == 0:
            return []
        result = self.collection.query(
            query_embeddings=[[float(v) for v in embedding]],
            n_results=min(k, self.collection.count()),
            include=["metadatas", "documents", "distances", "embeddings"],
        )
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        embeddings = (result.get("embeddings") or [[]])[0]

        out: list[tuple[MemoryRecord, float]] = []
        for i, character_id in enumerate(ids):
            distance = float(distances[i]) if i < len(distances) else 1.0
            vector = embeddings[i] if embeddings is not None and i < len(embeddings) and embeddings[i] is not None else []
            out.append(
                (
                    MemoryRecord(
                        character_id=character_id,
                        embedding=[float(v) for v in vector],
                        metadata=dict(metadatas[i] or {}) if i < len(metadatas) else {},
                        document=documents[i] or "" if i < len(documents) else "",
                    ),
                    similarity_from_distance(distance, "cosine"),
                )
            )
        return out

    def clear(self) -> None:
        self.client.delete_collection(f"characters_{self.project_id}")
        self.collection = self.client.get_or_create_collection(
            name=f"characters_{self.project_id}", metadata={"hnsw:space": "cosine"}
        )


def build_chroma_memory(project_id: str) -> ChromaCharacterMemory:
    return ChromaCharacterMemory(project_id)
