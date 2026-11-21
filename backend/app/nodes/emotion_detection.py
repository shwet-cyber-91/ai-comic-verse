"""Node 5 - Emotion Detection.

One strict-JSON task over the panel beats: dominant emotion, intensity and the
visible facial expression that the image prompt will carry.
"""

from __future__ import annotations

from typing import Any

from ..providers.registry import get_llm
from ..schemas import EmotionPlan
from ..state import PipelineState
from .base import emit, pipeline_node, project_from, project_update, request_from


@pipeline_node("emotion_detection", "Emotion Detection")
def run(state: PipelineState) -> dict[str, Any]:
    request = request_from(state)
    project = project_from(state)
    llm = get_llm()

    if not project.panels:
        raise ValueError("no panels to analyse - scene_planning produced none")

    scene_lookup = {scene.scene_id: scene for scene in project.scenes}
    beats: list[dict[str, Any]] = []
    for panel in project.panels:
        scene = scene_lookup.get(panel.scene_id)
        beats.append(
            {
                "panel_id": panel.panel_id,
                "scene_id": panel.scene_id,
                "action": panel.action,
                "characters": panel.characters,
                "scene_mood": scene.mood if scene else "neutral",
                "scene_setting": panel.scene_setting,
            }
        )

    emit(f"Reading emotion across {len(beats)} panel(s)")
    plan = llm.complete_json(
        "emotion_detection",
        {"beats": beats, "genre": project.story_analysis.genre if project.story_analysis else "drama"},
        EmotionPlan,
    )

    by_id = {item.panel_id: item for item in plan.beats}
    applied = 0
    for panel in project.panels:
        item = by_id.get(panel.panel_id)
        if item is None:
            continue

        if panel.emotion_overridden:
            emit(f"Keeping manual emotion override on {panel.panel_id}: {panel.emotion}")
            continue

        panel.emotion = item.emotion
        panel.intensity = item.intensity
        if not panel.expression_overridden:
            panel.expression = item.expression
        applied += 1

    if applied < len(project.panels):
        emit(
            f"emotion was returned for {applied}/{len(project.panels)} panels; "
            f"the remainder keep a neutral expression",
            level="warning",
        )

    distribution: dict[str, int] = {}
    for panel in project.panels:
        distribution[panel.emotion] = distribution.get(panel.emotion, 0) + 1
    emit(
        "Emotional range: " + ", ".join(f"{k} x{v}" for k, v in sorted(distribution.items())),
        data={"distribution": distribution},
    )

    return {"panels": [p.model_dump(mode="json") for p in project.panels], **project_update(project)}
