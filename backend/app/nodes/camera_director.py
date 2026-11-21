"""Node 7 - Camera Director.

Shot, lens, composition and movement per panel, with the scene position flags
the director needs to open on an establishing shot and close on a reaction.
"""

from __future__ import annotations

from typing import Any

from ..providers.registry import get_llm
from ..schemas import CameraPlan
from ..state import PipelineState
from .base import emit, pipeline_node, project_from, project_update, request_from


@pipeline_node("camera_director", "Camera Director")
def run(state: PipelineState) -> dict[str, Any]:
    request = request_from(state)
    project = project_from(state)
    llm = get_llm()

    scene_first: dict[str, str] = {}
    scene_last: dict[str, str] = {}
    for panel in project.panels:
        scene_first.setdefault(panel.scene_id, panel.panel_id)
        scene_last[panel.scene_id] = panel.panel_id

    payload_panels: list[dict[str, Any]] = []
    for panel in project.panels:
        siblings = [p.index for p in project.panels if p.scene_id == panel.scene_id]
        payload_panels.append(
            {
                "panel_id": panel.panel_id,
                "action": panel.action,
                "characters": panel.characters,
                "emotion": panel.emotion,
                "expression": panel.expression,
                "scene_setting": panel.scene_setting,
                "index_in_scene": siblings.index(panel.index) if panel.index in siblings else 0,
                "is_first_of_scene": scene_first.get(panel.scene_id) == panel.panel_id,
                "is_last_of_scene": scene_last.get(panel.scene_id) == panel.panel_id,
            }
        )

    emit(f"Choosing camera work for {len(payload_panels)} panel(s)")
    plan = llm.complete_json(
        "camera_director",
        {
            "panels": payload_panels,
            "style": request.style,
            "genre": project.story_analysis.genre if project.story_analysis else "drama",
        },
        CameraPlan,
    )

    by_id = {item.panel_id: item for item in plan.panels}
    shots: dict[str, int] = {}
    for panel in project.panels:
        item = by_id.get(panel.panel_id)
        if item is None:
            continue
        panel.camera = item.camera
        shots[item.camera.shot] = shots.get(item.camera.shot, 0) + 1

    if len(shots) == 1 and len(project.panels) > 2:
        emit(
            f"every panel uses the same shot ({next(iter(shots))}); the sequence will read flat",
            level="warning",
        )
    emit("Shot list: " + ", ".join(f"{k} x{v}" for k, v in sorted(shots.items())), data={"shots": shots})

    return {"panels": [p.model_dump(mode="json") for p in project.panels], **project_update(project)}
