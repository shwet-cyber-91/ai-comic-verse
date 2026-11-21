"""Node 6 - Dialogue Generation.

Speech, thought, shout and whisper bubbles, plus narration and sound effects.
Every line is a typed ``DialogueLine`` so the editor and the exporters can render
it as the right bubble shape without re-parsing anything.
"""

from __future__ import annotations

from typing import Any

from ..providers.registry import get_llm
from ..schemas import DialoguePlan
from ..state import PipelineState
from .base import emit, pipeline_node, project_from, project_update, request_from


@pipeline_node("dialogue_generation", "Dialogue Generation")
def run(state: PipelineState) -> dict[str, Any]:
    request = request_from(state)
    project = project_from(state)
    llm = get_llm()

    scene_lookup = {scene.scene_id: scene for scene in project.scenes}
    first_of_scene: dict[str, str] = {}
    for panel in project.panels:
        first_of_scene.setdefault(panel.scene_id, panel.panel_id)

    payload_panels: list[dict[str, Any]] = []
    for panel in project.panels:
        scene = scene_lookup.get(panel.scene_id)
        payload_panels.append(
            {
                "panel_id": panel.panel_id,
                "action": panel.action,
                "characters": panel.characters,
                "emotion": panel.emotion,
                "expression": panel.expression,
                "scene_setting": panel.scene_setting,
                "scene_summary": panel.scene_summary,
                "scene_mood": scene.mood if scene else "neutral",
                "is_first_of_scene": first_of_scene.get(panel.scene_id) == panel.panel_id,
                "is_last_of_scene": panel.index
                == max(
                    (p.index for p in project.panels if p.scene_id == panel.scene_id),
                    default=panel.index,
                ),
                "silent": panel.index == 1 and not panel.characters,
            }
        )

    emit(f"Writing dialogue for {len(payload_panels)} panel(s) in {request.language}")
    plan = llm.complete_json(
        "dialogue_generation",
        {
            "panels": payload_panels,
            "style": request.style,
            "language": request.language,
            "genre": project.story_analysis.genre if project.story_analysis else "drama",
        },
        DialoguePlan,
    )

    by_id = {item.panel_id: item for item in plan.panels}
    total_lines = 0
    for panel in project.panels:
        item = by_id.get(panel.panel_id)
        if item is None:
            continue
        if item.lines:
            panel.dialogue = item.lines
            total_lines += len(item.lines)
        if item.narration:
            panel.narration = item.narration
        if item.sfx:
            panel.sfx = item.sfx

    narrated = sum(1 for p in project.panels if p.narration)
    emit(
        f"{total_lines} line(s) of dialogue and {narrated} narration caption(s) written",
        data={"lines": total_lines, "narration": narrated},
    )

    # a panel with neither words nor a caption reads as a blank page, so caption it
    # from its own action rather than ship an empty one
    captioned = 0
    for panel in project.panels:
        if panel.dialogue or panel.narration:
            continue
        caption = (panel.action or panel.scene_summary or "").strip()
        panel.narration = caption[:160] if caption else f"Panel {panel.index}."
        captioned += 1
    if captioned:
        emit(
            f"{captioned} panel(s) came back wordless; captioned them from the action",
            level="warning",
        )

    for panel in project.panels[:3]:
        if panel.dialogue:
            line = panel.dialogue[0]
            emit(f"  {panel.panel_id} {line.speaker} ({line.kind}): \"{line.text}\"")

    return {"panels": [p.model_dump(mode="json") for p in project.panels], **project_update(project)}
