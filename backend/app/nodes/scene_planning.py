"""Node 3 - Scene Planning.

Produces the scene list and, crucially, one *beat per panel*: the beat list is
what fixes the panel count. Models drift on this, so the result is reconciled
against the requested panel count before it is trusted.
"""

from __future__ import annotations

from typing import Any

from ..providers.registry import get_llm
from ..schemas import Panel, ScenePlanList
from ..state import PipelineState
from .base import emit, pipeline_node, project_from, project_update, request_from


def reconcile_beats(scenes: list[Any], panel_count: int) -> list[str]:
    """Force the total beat count to equal ``panel_count``. Returns warnings."""
    warnings: list[str] = []
    total = sum(len(scene.beats) for scene in scenes)
    if total == panel_count:
        return warnings

    warnings.append(f"model planned {total} beats for {panel_count} panels; reconciled")

    # trim from the scenes with the most beats
    while sum(len(s.beats) for s in scenes) > panel_count:
        fattest = max(scenes, key=lambda s: len(s.beats))
        if len(fattest.beats) <= 1:
            break
        fattest.beats.pop()

    # pad the last scene, extending its action text
    while sum(len(s.beats) for s in scenes) < panel_count:
        target = scenes[-1]
        target.beats.append(
            f"closing beat: {target.action[:110] or target.summary}" if target.action else "closing beat"
        )
    return warnings


@pipeline_node("scene_planning", "Scene Planning")
def run(state: PipelineState) -> dict[str, Any]:
    request = request_from(state)
    project = project_from(state)
    llm = get_llm()
    analysis = project.story_analysis

    characters = [c.name for c in (analysis.characters if analysis else [])] or ["the narrator"]
    emit(f"Planning scenes across {len(characters)} character(s)")

    payload = {
        "story_text": request.story_text,
        "panel_count": request.panel_count,
        "style": request.style,
        "characters": characters,
        "story_analysis": project.story_analysis.model_dump(mode="json") if analysis else {},
    }
    plan = llm.complete_json("scene_planning", payload, ScenePlanList)

    for warning in reconcile_beats(plan.scenes, request.panel_count):
        emit(warning, level="warning")

    # ensure ids and ordering are sane regardless of what the model returned
    for index, scene in enumerate(plan.scenes, start=1):
        scene.index = index
        scene.scene_id = scene.scene_id or f"s{index}"

    # build one Panel per beat
    panels: list[Panel] = []
    cast = plan.scenes[0].characters or characters
    index = 0
    for scene in plan.scenes:
        scene_cast = scene.characters or cast
        for beat_index, beat in enumerate(scene.beats):
            index += 1
            # rotate the on-panel cast so panels vary, and keep groups small enough to draw
            present = [scene_cast[(beat_index + offset) % len(scene_cast)] for offset in range(min(2, len(scene_cast)))]
            present = list(dict.fromkeys(present))
            panels.append(
                Panel(
                    panel_id=f"p{index:03d}",
                    index=index,
                    scene_id=scene.scene_id,
                    scene_summary=scene.summary,
                    scene_setting=f"{scene.setting}, {scene.time_of_day}",
                    characters=present,
                    action=beat,
                    style=request.style,
                    seed=project.seed + index,
                )
            )

    project.scenes = plan.scenes
    project.panels = panels
    project.panel_count = len(panels)

    emit(
        f"{len(plan.scenes)} scene(s), {len(panels)} panels",
        data={"scenes": [s.title for s in plan.scenes], "panels": len(panels)},
    )
    for scene in plan.scenes:
        emit(f"  {scene.scene_id} '{scene.title}' - {scene.mood} - {len(scene.beats)} panel(s)")

    return {
        "scenes": [s.model_dump(mode="json") for s in plan.scenes],
        "panels": [p.model_dump(mode="json") for p in panels],
        **project_update(project),
    }
