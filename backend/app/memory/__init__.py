"""Character memory factory."""

from __future__ import annotations

from ..config import get_settings
from ..logging_config import get_logger
from .base import CharacterMemory, MemoryRecord, similarity_from_distance  # noqa: F401
from .json_store import JsonCharacterMemory

log = get_logger("memory")

_backend_name: str | None = None


def _resolve_backend() -> str:
    global _backend_name
    if _backend_name is not None:
        return _backend_name

    requested = (get_settings().vector_store or "auto").lower()
    if requested == "json":
        _backend_name = "json"
    elif requested == "chroma":
        from .chroma_store import chroma_available

        if chroma_available():
            _backend_name = "chroma"
        else:
            log.warning("VECTOR_STORE=chroma but chromadb is not installed; using the JSON store")
            _backend_name = "json"
    else:  # auto
        from .chroma_store import chroma_available

        _backend_name = "chroma" if chroma_available() else "json"
    return _backend_name


def get_memory(project_id: str) -> CharacterMemory:
    if _resolve_backend() == "chroma":
        from .chroma_store import build_chroma_memory

        return build_chroma_memory(project_id)
    return JsonCharacterMemory(project_id)


def memory_backend_name() -> str:
    return _resolve_backend()


def reset_memory_backend() -> None:
    global _backend_name
    _backend_name = None
