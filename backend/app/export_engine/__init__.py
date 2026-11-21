"""Export engine.

``export_project`` writes the requested formats and returns a mapping of format
name to *storage-relative* path. The API layer turns those into ``/static`` URLs.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_settings
from ..logging_config import get_logger
from ..schemas import ComicProject, ExportResult
from ..storage import rel_path, safe_slug
from .epub import export_epub
from .pdf import export_pdf
from .png_zip import export_png_zip
from .render import compose_page, cell_rect  # noqa: F401  (re-exported for the API)
from .web import export_web

log = get_logger("export")

EXPORTERS = {
    "pdf": (export_pdf, ".pdf"),
    "png_zip": (export_png_zip, ".zip"),
    "web": (export_web, ".html"),
    "epub": (export_epub, ".epub"),
}

ALL_FORMATS = list(EXPORTERS.keys())


def export_project(project: ComicProject, formats: list[str] | None = None) -> dict[str, str]:
    """Write the requested formats. Failures in one format do not block the others."""
    settings = get_settings()
    requested = [f for f in (formats or ALL_FORMATS) if f in EXPORTERS]
    unknown = [f for f in (formats or []) if f not in EXPORTERS]
    if unknown:
        log.warning("ignoring unknown export format(s): %s", ", ".join(unknown))
    if not requested:
        raise ValueError(f"no valid export formats requested (valid: {', '.join(ALL_FORMATS)})")
    if not project.pages:
        raise ValueError("nothing to export: the project has no pages")

    export_dir = settings.project_subdirs(project.project_id)["exports"]
    base = safe_slug(project.title) or "comic"
    results: dict[str, str] = {}

    for fmt in requested:
        exporter, suffix = EXPORTERS[fmt]
        output = export_dir / f"{base}-{fmt}{suffix}"
        started = time.perf_counter()
        try:
            exporter(project, output)
            results[fmt] = rel_path(output)
            log.info("%s export finished in %.2fs", fmt, time.perf_counter() - started)
        except Exception as exc:
            log.exception("%s export failed", fmt)
            log.warning("format %s could not be produced: %s", fmt, exc)

    if not results:
        raise RuntimeError("every requested export format failed")

    project.exports = ExportResult(generated_at=datetime.now(timezone.utc), **results)
    return results
