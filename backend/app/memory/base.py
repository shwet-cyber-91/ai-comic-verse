"""Character memory store interface.

One record per character: its embedding, its character-sheet metadata, and a
short text document ("Maya: tall and lean, short black hair, ..."). Implemented
by ChromaDB when available and by a JSON store otherwise, so character memory
works with or without the extra dependency.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass
class MemoryRecord:
    character_id: str
    embedding: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    document: str = ""


class CharacterMemory(ABC):
    backend: str = "base"

    @abstractmethod
    def upsert(
        self,
        character_id: str,
        embedding: Sequence[float],
        metadata: dict[str, Any] | None = None,
        document: str = "",
    ) -> None: ...

    @abstractmethod
    def get(self, character_id: str) -> MemoryRecord | None: ...

    @abstractmethod
    def all(self) -> list[MemoryRecord]: ...

    @abstractmethod
    def query(self, embedding: Sequence[float], k: int = 3) -> list[tuple[MemoryRecord, float]]:
        """Return the ``k`` nearest records with a similarity score in [0, 1]."""

    @abstractmethod
    def clear(self) -> None: ...

    def count(self) -> int:
        return len(self.all())


def similarity_from_distance(distance: float, space: str = "cosine") -> float:
    """Map a vector-store distance onto a 0..1 similarity."""
    if space == "cosine":
        return max(0.0, min(1.0, 1.0 - float(distance)))
    if space == "l2":
        return 1.0 / (1.0 + float(distance))
    if space == "ip":
        return max(0.0, min(1.0, float(distance)))
    return max(0.0, min(1.0, 1.0 - float(distance)))
