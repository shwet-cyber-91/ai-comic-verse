"""Node 14 - Export.

Writes the requested formats and records their storage-relative paths on the
project. Individual format failures are logged and skipped rather than failing
the whole run, because a comic with a PDF and no EPUB is still a usable comic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..export_engine import ALL_FORMATS, export_project
from ..schemas import ExportResult
from ..state import PipelineState
from ..storage import static_url
from .base import emit, pipeline_node, project_from, project_update, request_from


@pipeline_node("export", "Export")
def run(state: PipelineState) -> dict[str, Any]:
    request = request_from(state)
    project = project_from(state)

    formats = [f for f in (request.export_formats or ALL_FORMATS) if f in ALL_FORMATS] or ALL_FORMATS
    emit(f"Writing {', '.join(formats)}")

    urls: dict[str, str] = {}
    paths: dict[str, str] = {}
    failures: list[str] = []
    for fmt in formats:
        try:
            results = export_project(project, [fmt])
        except Exception as exc:
            failures.append(f"{fmt} ({exc})")
            emit(f"  {fmt} failed: {exc}", level="error")
            continue
        relative = results.get(fmt)
        if relative:
            paths[fmt] = relative
            urls[fmt] = static_url(relative) or ""
            emit(f"  {fmt} ready", level="success", data={"url": urls[fmt], "format": fmt})

    if not urls:
        raise RuntimeError(f"no export could be produced: {'; '.join(failures)}")
    if failures:
        emit(f"{len(failures)} format(s) unavailable: {'; '.join(failures)}", level="warning")

    # each per-format call above replaces project.exports with just its own format,
    # so record the union - the storage-relative paths, which is what download reads
    project.exports = ExportResult(generated_at=datetime.now(timezone.utc), **paths)

    project.status = "ready"
    emit(
        f"Export complete - {len(urls)} file(s) ready to download",
        level="success",
        data={"exports": urls},
    )

    return {"exports": urls, **project_update(project)}
