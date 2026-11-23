"""Node 2 - Story Understanding.

One strict-JSON LLM task: genre, tone, setting, themes, logline, cast and arc.
"""

from __future__ import annotations

from typing import Any

from ..providers.registry import get_llm
from ..schemas import StoryAnalysis
from ..state import PipelineState
from .base import emit, pipeline_node, project_from, project_update, request_from


@pipeline_node("story_understanding", "Story Understanding")
def run(state: PipelineState) -> dict[str, Any]:
    request = request_from(state)
    project = project_from(state)
    llm = get_llm()

    emit(f"Asking {llm.name} to analyse the story ({len(request.story_text.split())} words)")

    payload = {
        "story_text": request.story_text,
        "title": request.title,
        "panel_count": request.panel_count,
        "auto_panel_count": request.auto_panel_count,
        "language": request.language,
        "user_characters": [
            {"name": c.name, "description": c.description} for c in request.characters
        ],
    }
    analysis = llm.complete_json("story_understanding", payload, StoryAnalysis)

    # the user's title always wins over the model's suggestion
    if request.title and request.title != "Untitled Comic":
        analysis.title = request.title
    if request.auto_panel_count:
        request.panel_count = analysis.recommended_panel_count
        request.auto_panel_count = False
        emit(f"Story-based panel count selected: {request.panel_count}")
    analysis.scene_count = max(1, min(analysis.scene_count, max(1, request.panel_count)))
    project.panel_count = request.panel_count
    project.title = analysis.title
    project.story_analysis = analysis

    emit(
        f"{analysis.genre} / {analysis.tone} - {len(analysis.characters)} character(s), "
        f"{analysis.scene_count} scene(s)",
        data={
            "genre": analysis.genre,
            "tone": analysis.tone,
            "scene_count": analysis.scene_count,
            "logline": analysis.logline,
        },
    )
    if analysis.characters:
        emit("Cast: " + ", ".join(f"{c.name} ({c.role})" for c in analysis.characters))

    return {
        "request": request.model_dump(mode="json"),
        "story_analysis": analysis.model_dump(mode="json"),
        **project_update(project),
    }
