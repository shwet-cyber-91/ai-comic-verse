"""Filesystem layout for generated artefacts.

Everything the app writes lives under ``STORAGE_DIR`` (default ``backend/storage``)
and is addressed by a *storage-relative* POSIX path such as
``projects/<pid>/panels/p001.png``. Those relative paths are what gets stored in
the database and returned to the frontend, which prefixes them with ``/static``.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from .config import get_settings
from .logging_config import get_logger

log = get_logger("storage")

ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def static_url(rel_path: str | None) -> str | None:
    """Storage-relative path -> URL the frontend can load."""
    if not rel_path:
        return None
    return "/static/" + rel_path.replace("\\", "/").lstrip("/")


def abs_path(rel_path: str) -> Path:
    """Storage-relative path -> absolute path on disk."""
    return get_settings().storage_dir / rel_path


def rel_path(path: Path) -> str:
    """Absolute path -> storage-relative POSIX path."""
    return path.resolve().relative_to(get_settings().storage_dir.resolve()).as_posix()


def safe_slug(value: str) -> str:
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in value.strip().lower()]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "item"


def save_reference_upload(project_id: str, character_name: str, filename: str, data: bytes) -> str:
    """Persist an uploaded reference image; returns the storage-relative path."""
    settings = get_settings()
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        suffix = ".png"
    target_dir = settings.project_subdirs(project_id)["refs"]
    target = target_dir / f"{safe_slug(character_name)}-{uuid.uuid4().hex[:8]}{suffix}"
    target.write_bytes(data)
    log.info("saved reference image %s (%d bytes)", target.name, len(data))
    return rel_path(target)


def save_loose_reference(character_name: str, filename: str, data: bytes) -> str:
    """Reference uploaded before the project exists (Create screen).

    Lands in ``storage/refs`` under a synthetic ``_draft`` project id and is
    referenced directly by the character sheet at generation time.
    """
    settings = get_settings()
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        suffix = ".png"
    target_dir = settings.refs_dir / "_draft"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{safe_slug(character_name)}-{uuid.uuid4().hex[:8]}{suffix}"
    target.write_bytes(data)
    return rel_path(target)


def copy_into_project(project_id: str, rel_or_abs: str, subdir: str = "refs") -> str:
    """Copy a file (loose ref or any storage file) into the project folder."""
    settings = get_settings()
    src = Path(rel_or_abs)
    if not src.is_absolute():
        src = settings.storage_dir / rel_or_abs
    if not src.exists():
        log.warning("copy_into_project: missing source %s", src)
        return rel_or_abs
    target_dir = settings.project_subdirs(project_id)[subdir]
    target = target_dir / src.name
    if src.resolve() != target.resolve():
        shutil.copy2(src, target)
    return rel_path(target)


def write_bytes(project_id: str, subdir: str, filename: str, data: bytes) -> str:
    settings = get_settings()
    target_dir = settings.project_subdirs(project_id)[subdir]
    target = target_dir / filename
    target.write_bytes(data)
    return rel_path(target)


def resolve_maybe_relative(path_str: str | None) -> Path | None:
    """Accept either an absolute path or a storage-relative one."""
    if not path_str:
        return None
    candidate = Path(path_str)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    fallback = get_settings().storage_dir / path_str
    return fallback if fallback.exists() else None


def image_suffix_from_bytes(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".png"
