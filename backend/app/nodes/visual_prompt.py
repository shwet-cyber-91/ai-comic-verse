"""Node 8 - Visual Prompt Generation.

The final prompt for each panel. The character's fixed design details are
restated in every prompt, which is what keeps a reference-conditioned model from
drifting even when the reference image is the only identity signal.
"""

from __future__ import annotations

from typing import Any

from ..providers.registry import get_llm
from ..schemas import PromptPlan
from ..state import PipelineState
from .base import emit, pipeline_node, project_from, project_update, request_from


@pipeline_node("visual_prompt_generation", "Visual Prompt Generation")
def run(state: PipelineState) -> dict[str, Any]:
    request = request_from(state)
    project = project_from(state)
    llm = get_llm()

    if not project.characters:
        emit("no character sheets available; prompts will rely on the written description", level="warning")

    sheets = [c.model_dump(mode="json") for c in project.characters]
    payload_panels: list[dict[str, Any]] = []
    for panel in project.panels:
        payload_panels.append(
            {
                "panel_id": panel.panel_id,
                "action": panel.action,
                "characters": panel.characters,
                "emotion": panel.emotion,
                "expression": panel.expression,
                "setting": panel.scene_setting,
                "time_of_day": panel.scene_setting,
                "camera": panel.camera.model_dump(mode="json") if panel.camera else {},
                "dialogue_hint": " ".join(line.text for line in panel.dialogue)[:180],
            }
        )

    emit(f"Composing {len(payload_panels)} image prompt(s) with {llm.name}")
    plan = llm.complete_json(
        "visual_prompt_generation",
        {
            "panels": payload_panels,
            "character_sheets": sheets,
            "style": request.style,
            "character_reference_counts": {c.name: len(c.reference_images) for c in project.characters},
        },
        PromptPlan,
    )

    by_id = {item.panel_id: item for item in plan.panels}
    missing = 0
    for panel in project.panels:
        if panel.visual_prompt_overridden and panel.visual_prompt:
            emit(f"Keeping manual prompt override for {panel.panel_id}")
            continue

        item = by_id.get(panel.panel_id)
        if item is None:
            missing += 1
            continue
        panel.visual_prompt = item.positive
        panel.negative_prompt = item.negative

    if missing:
        emit(f"{missing} panel(s) came back without a prompt", level="warning")

    sample = project.panels[0].visual_prompt if project.panels else ""
    emit(
        f"{len(project.panels) - missing} prompt(s) ready (avg {sum(len(p.visual_prompt) for p in project.panels) // max(1, len(project.panels))} chars)",
        data={"sample_prompt": sample[:400]},
    )

    return {"panels": [p.model_dump(mode="json") for p in project.panels], **project_update(project)}
