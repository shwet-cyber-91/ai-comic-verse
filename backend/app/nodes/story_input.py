"""Node 1 - Story Input.

Normalises the request, creates the project record, and copies any uploaded
reference images into the project's own folder so later stages have stable paths.
"""

from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..pipeline_meta import NODE_META, TOTAL_NODES
from ..schemas import ComicProject
from ..state import PipelineState
from ..storage import copy_into_project
from .base import emit, pipeline_node, project_update, request_from


@pipeline_node("story_input", "Story Input")
def run(state: PipelineState) -> dict[str, Any]:
    settings = get_settings()
    request = request_from(state)
    project_id = state["project_id"]

    emit(f"Preparing project '{request.title}' ({request.panel_count} panels, {request.style} style)")

    project = ComicProject(
        project_id=project_id,
        title=request.title,
        style=request.style,
        status="running",
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

    # Move reference images into the project folder and rewrite the request so
    # every downstream stage addresses files inside the project.
    normalized_characters: list[dict[str, Any]] = []
    moved = 0
    for character in request.characters:
        copied: list[str] = []
        for reference in character.reference_images:
            copied.append(copy_into_project(project_id, reference, "refs"))
            moved += 1
        normalized_characters.append(
            {
                "name": character.name,
                "description": character.description,
                "reference_images": copied,
            }
        )
    if normalized_characters:
        emit(
            f"{moved} reference image(s) across {len(normalized_characters)} character(s) stored",
            data={"characters": [c["name"] for c in normalized_characters]},
        )
    else:
        emit("No reference images supplied - characters will be drawn from their written descriptions")

    request_payload = request.model_dump(mode="json")
    request_payload["characters"] = normalized_characters

    plan = {
        "nodes": [name for name, _, _ in NODE_META],
        "total": TOTAL_NODES,
        "panel_count": request.panel_count,
        "panels_per_page": request.panels_per_page,
        "style": request.style,
    }

    return {
        "request": request_payload,
        "plan": plan,
        "retry": 0,
        "regenerate_panel_ids": [],
        **project_update(project),
    }
