"""All API routes.

Contract (the frontend's ``src/api.js`` mirrors this exactly):

    GET    /api/health
    GET    /api/styles
    GET    /api/pipeline/nodes
    GET    /api/seed/demo
    POST   /api/characters/refs            multipart: name, files[]
    POST   /api/transcribe                 multipart: file
    POST   /api/projects
    GET    /api/projects
    GET    /api/projects/{project_id}
    DELETE /api/projects/{project_id}
    POST   /api/projects/{project_id}/generate
    PATCH  /api/projects/{project_id}/panels/{panel_id}
    POST   /api/projects/{project_id}/panels/{panel_id}/regenerate
    PATCH  /api/projects/{project_id}/layout
    POST   /api/projects/{project_id}/export
    GET    /api/projects/{project_id}/download/{fmt}
    GET    /api/jobs/{job_id}
    GET    /api/jobs/{job_id}/events       text/event-stream
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from ..config import get_settings
from ..db import delete_project, list_projects, load_project, save_project
from ..export_engine import ALL_FORMATS, export_project
from ..graph import regenerate_panels, run_pipeline
from ..jobs import registry
from ..logging_config import get_logger
from ..nodes.editor import apply_panel_update, find_panel
from ..nodes.layout_generator import paginate
from ..pipeline_meta import TOTAL_NODES, node_infos
from ..providers.registry import get_stt, is_mock_mode, provider_info
from ..schemas import (
    CharacterRef,
    ComicProject,
    DemoStoryResponse,
    ExportRequest,
    JobSnapshot,
    LayoutRequest,
    PanelUpdateRequest,
    PipelineNodesResponse,
    ProjectListResponse,
    RegeneratePanelRequest,
    StoryRequest,
    StyleListResponse,
    TranscribeResponse,
)
from ..storage import abs_path, image_suffix_from_bytes, save_loose_reference, static_url
from ..styles.presets import list_style_presets

log = get_logger("api")

router = APIRouter(prefix="/api")

APP_VERSION = "0.1.0"

# One generation at a time (the pipeline is CPU/GPU heavy); editors can still
# regenerate a panel while another project renders.
#
# The pool is created lazily and recreated after a shutdown, because the ASGI
# lifespan tears it down on every app shutdown - including the shutdown that
# ends each TestClient block in the test suite, and any run that builds a
# second app object. A module-level executor would be dead after the first one.
_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="comicverse")
        return _pool

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "png_zip": "application/zip",
    "web": "text/html",
    "epub": "application/epub+zip",
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _load(project_id: str) -> ComicProject:
    project = load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project '{project_id}' not found")
    return project


def _request_for(project: ComicProject) -> dict[str, Any]:
    """Rebuild the StoryRequest a stored project was generated from."""
    return StoryRequest(
        title=project.title,
        story_text=project.story_text or ".",
        style=project.style,
        characters=[
            CharacterRef(
                name=character.name,
                description=character.appearance,
                reference_images=list(character.reference_images),
            )
            for character in project.characters
        ],
        panel_count=max(2, len(project.panels) or project.panel_count or 8),
        panels_per_page=project.panels_per_page,
        language=project.language,
        continuity_threshold=project.continuity_threshold,
        seed=project.seed,
    ).model_dump(mode="json")


def _spawn(project_id: str, request: dict[str, Any], label: str):
    """Queue a blocking pipeline run on the worker pool and return its job."""
    job = registry.create(project_id, TOTAL_NODES)
    registry.emit(job.job_id, f"{label} queued", level="info")

    def _work() -> None:
        try:
            run_pipeline(project_id, request, job_id=job.job_id)
        except Exception as exc:  # already recorded on the job by the graph
            log.error("%s failed for %s: %s", label, project_id, exc)

    _get_pool().submit(_work)
    return job


def _spawn_regeneration(
    project_id: str,
    request: dict[str, Any],
    panel_ids: list[str],
    edit_request: dict[str, Any] | None,
):
    job = registry.create(project_id, TOTAL_NODES)
    registry.emit(
        job.job_id,
        f"Regenerating {len(panel_ids)} panel(s): {', '.join(panel_ids)}",
        level="info",
    )

    def _work() -> None:
        try:
            regenerate_panels(
                project_id,
                request,
                panel_ids,
                job_id=job.job_id,
                edit_request=edit_request,
            )
        except Exception as exc:
            log.error("regeneration failed for %s: %s", project_id, exc)

    _get_pool().submit(_work)
    return job


# --------------------------------------------------------------------------- #
# Health / metadata
# --------------------------------------------------------------------------- #


@router.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": APP_VERSION,
        "environment": settings.environment,
        "mock_mode": is_mock_mode(),
        "providers": provider_info().model_dump(mode="json"),
    }


@router.get("/styles", response_model=StyleListResponse)
def styles() -> StyleListResponse:
    return StyleListResponse(styles=list_style_presets())


@router.get("/pipeline/nodes", response_model=PipelineNodesResponse)
def pipeline_nodes() -> PipelineNodesResponse:
    nodes = node_infos()
    return PipelineNodesResponse(nodes=nodes, total=len(nodes))


@router.get("/seed/demo", response_model=DemoStoryResponse)
def seed_demo() -> DemoStoryResponse:
    path = Path(__file__).resolve().parents[2] / "seed" / "demo_story.json"
    if not path.exists():
        raise HTTPException(status_code=500, detail="seed/demo_story.json is missing")
    return DemoStoryResponse.model_validate_json(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Voice + reference uploads
# --------------------------------------------------------------------------- #


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(file: UploadFile = File(...)) -> TranscribeResponse:
    settings = get_settings()
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="the uploaded audio file is empty")

    suffix = Path(file.filename or "").suffix.lower() or ".webm"
    target = settings.tmp_dir / f"upload-{uuid.uuid4().hex[:10]}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    try:
        result = get_stt().transcribe(str(target))
    except Exception as exc:
        log.exception("transcription failed")
        raise HTTPException(status_code=502, detail=f"transcription failed: {exc}") from exc
    finally:
        target.unlink(missing_ok=True)

    return TranscribeResponse(
        text=result.text,
        language=result.language,
        provider=result.provider,
        duration=result.duration,
    )


@router.post("/characters/refs", response_model=CharacterRef)
async def upload_references(
    name: str = Form(...),
    description: str = Form(""),
    files: Optional[list[UploadFile]] = File(default=None),
) -> CharacterRef:
    cleaned = name.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="character name must not be blank")

    stored: list[str] = []
    for upload in files or []:
        data = await upload.read()
        if not data:
            continue
        suffix = Path(upload.filename or "").suffix.lower() or image_suffix_from_bytes(data)
        stored.append(save_loose_reference(cleaned, f"ref{suffix}", data))
        if len(stored) >= 2:
            break

    if not stored:
        raise HTTPException(status_code=400, detail="at least one reference image is required")

    log.info("stored %d reference image(s) for '%s'", len(stored), cleaned)
    return CharacterRef(name=cleaned, description=description, reference_images=stored)


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #


@router.post("/projects", response_model=ComicProject)
def create_project(request: StoryRequest) -> ComicProject:
    project_id = uuid.uuid4().hex[:12]
    settings = get_settings()
    settings.project_subdirs(project_id)  # create the folders up front

    project = ComicProject(
        project_id=project_id,
        title=request.title,
        style=request.style,
        status="draft",
        story_text=request.story_text,
        language=request.language,
        panel_count=request.panel_count,
        panels_per_page=request.panels_per_page,
        seed=request.seed if request.seed is not None else settings.seed,
        continuity_threshold=(
            request.continuity_threshold
            if request.continuity_threshold is not None
            else settings.continuity_threshold
        ),
    )
    save_project(project)
    log.info("project %s created ('%s', %d panels)", project_id, project.title, request.panel_count)
    return project


@router.get("/projects", response_model=ProjectListResponse)
def get_projects(limit: int = 50) -> ProjectListResponse:
    return ProjectListResponse(projects=list_projects(limit=limit))


@router.get("/projects/{project_id}", response_model=ComicProject)
def get_project(project_id: str) -> ComicProject:
    return _load(project_id)


@router.delete("/projects/{project_id}")
def remove_project(project_id: str) -> dict[str, bool]:
    if not delete_project(project_id):
        raise HTTPException(status_code=404, detail=f"project '{project_id}' not found")
    return {"deleted": True}


@router.post("/projects/{project_id}/generate", status_code=202)
def generate(project_id: str, request: StoryRequest | None = None) -> dict[str, Any]:
    project = _load(project_id)
    payload = request.model_dump(mode="json") if request else _request_for(project)

    project.status = "queued"
    project.error = None
    save_project(project)

    job = _spawn(project_id, payload, "generation")
    return {"job_id": job.job_id, "project_id": project_id, "status": "queued", "total_nodes": TOTAL_NODES}


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #


@router.get("/jobs/{job_id}", response_model=JobSnapshot)
def job_status(job_id: str, since: int = 0) -> JobSnapshot:
    snapshot = registry.snapshot(job_id, since_seq=since)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")
    return snapshot


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, since: int = 0):
    if registry.get(job_id) is None:
        raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")

    async def stream():
        cursor = since
        idle = 0
        while True:
            snapshot = registry.snapshot(job_id, since_seq=cursor)
            if snapshot is None:
                yield {"event": "error", "data": json.dumps({"message": "job disappeared"})}
                return

            for event in snapshot.events:
                cursor = max(cursor, event.seq)
                yield {"event": "progress", "data": event.model_dump_json()}
                idle = 0

            yield {
                "event": "state",
                "data": json.dumps(
                    {
                        "status": snapshot.status,
                        "current_node": snapshot.current_node,
                        "completed_nodes": snapshot.completed_nodes,
                        "total_nodes": snapshot.total_nodes,
                        "progress": snapshot.progress,
                        "error": snapshot.error,
                    }
                ),
            }

            if snapshot.status in ("succeeded", "failed"):
                yield {"event": "end", "data": json.dumps({"status": snapshot.status})}
                return

            idle += 1
            if idle > 2400:  # ~10 minutes of silence: give up rather than hang forever
                yield {"event": "end", "data": json.dumps({"status": "timeout"})}
                return
            await asyncio.sleep(0.25)

    return EventSourceResponse(stream(), ping=15)


# --------------------------------------------------------------------------- #
# Editor
# --------------------------------------------------------------------------- #


@router.patch("/projects/{project_id}/panels/{panel_id}")
def update_panel(project_id: str, panel_id: str, update: PanelUpdateRequest) -> dict[str, Any]:
    project = _load(project_id)
    try:
        panel, changed = apply_panel_update(project, panel_id, update)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # a panel change can alter the page composite, so re-paginate cheaply -
    # keeping whatever template the user already chose
    template = project.pages[0].template if project.pages else None
    project.pages = paginate(project.panels, project.panels_per_page, template)
    save_project(project)
    log.info("panel %s of %s edited: %s", panel_id, project_id, ", ".join(changed) or "nothing")

    return {"panel": panel.model_dump(mode="json"), "project": project.model_dump(mode="json"), "changed": changed}


@router.post("/projects/{project_id}/panels/{panel_id}/regenerate", status_code=202)
def regenerate_panel(
    project_id: str, panel_id: str, request: RegeneratePanelRequest | None = None
) -> dict[str, Any]:
    project = _load(project_id)
    try:
        panel = find_panel(project, panel_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    request = request or RegeneratePanelRequest()
    if request.seed is not None:
        panel.seed = request.seed
    if request.prompt_override:
        panel.visual_prompt = request.prompt_override
        panel.visual_prompt_overridden = True
    else:
        panel.visual_prompt_overridden = False
    panel.regenerations += 1
    save_project(project)

    job = _spawn_regeneration(project_id, _request_for(project), [panel_id], None)
    return {
        "job_id": job.job_id,
        "project_id": project_id,
        "panel_id": panel_id,
        "status": "queued",
    }


# --------------------------------------------------------------------------- #
# Layout / export / download
# --------------------------------------------------------------------------- #


@router.patch("/projects/{project_id}/layout")
def update_layout(project_id: str, request: LayoutRequest) -> dict[str, Any]:
    project = _load(project_id)
    if not project.panels:
        raise HTTPException(status_code=400, detail="this project has no panels to lay out yet")

    if request.panels_per_page is not None:
        project.panels_per_page = request.panels_per_page
    project.pages = paginate(project.panels, project.panels_per_page, request.template)
    save_project(project)
    log.info(
        "layout of %s updated: %d page(s) at %d per page",
        project_id,
        len(project.pages),
        project.panels_per_page,
    )
    return {"project": project.model_dump(mode="json")}


@router.post("/projects/{project_id}/export")
def export(project_id: str, request: ExportRequest | None = None) -> dict[str, Any]:
    project = _load(project_id)
    formats = list(request.formats) if request else list(ALL_FORMATS)
    try:
        results = export_project(project, formats)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    project.exports.generated_at = datetime.now(timezone.utc)
    save_project(project)

    urls = {fmt: static_url(path) for fmt, path in results.items()}
    return {
        "exports": urls,
        "paths": results,
        "project": project.model_dump(mode="json"),
    }


@router.get("/projects/{project_id}/download/{fmt}")
def download(project_id: str, fmt: str):
    project = _load(project_id)
    if fmt not in MEDIA_TYPES:
        raise HTTPException(status_code=404, detail=f"unknown format '{fmt}'")

    stored = project.exports.as_dict().get(fmt)
    path = abs_path(stored) if stored else None
    if path is None or not path.exists():
        try:
            results = export_project(project, [fmt])
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"{fmt} export is not available: {exc}") from exc
        save_project(project)
        path = abs_path(results[fmt])

    filename = f"{project.project_id}-{fmt}{path.suffix}"
    return FileResponse(path, media_type=MEDIA_TYPES[fmt], filename=filename)


def shutdown_pool(wait: bool = False) -> None:
    """Stop accepting pipeline work. Called from the app's shutdown hook.

    Drops the reference as well, so a later request rebuilds a live pool instead
    of submitting to a shut-down executor.
    """
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=wait, cancel_futures=not wait)


__all__ = ["router", "shutdown_pool"]
