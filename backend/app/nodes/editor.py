"""Node 13 - Editor.

Applies any pending edit to the project and finalises it. The edit helpers here
are the same functions the API's PATCH/regenerate endpoints call, so editing
during generation and editing afterwards behave identically.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..logging_config import get_logger
from ..schemas import PanelUpdateRequest
from ..state import PipelineState
from .base import NodeError, emit, pipeline_node, project_from, project_update

log = get_logger("nodes.editor")


def find_panel(project, panel_id: str):
    for panel in project.panels:
        if panel.panel_id == panel_id:
            return panel
    raise KeyError(f"panel '{panel_id}' does not exist in project {project.project_id}")


def apply_panel_update(project, panel_id: str, update: PanelUpdateRequest):
    """Merge an edit into a panel. Only the fields actually sent are changed."""
    panel = find_panel(project, panel_id)
    changed: list[str] = []
    panel.visual_prompt_overridden = False

    if update.dialogue is not None:
        panel.dialogue = update.dialogue
        changed.append("dialogue")
    if update.narration is not None:
        panel.narration = update.narration or None
        changed.append("narration")
    if update.sfx is not None:
        panel.sfx = update.sfx or None
        changed.append("sfx")
    if update.action is not None:
        panel.action = update.action
        changed.append("action")
    if update.scene_summary is not None:
        panel.scene_summary = update.scene_summary
        changed.append("scene_summary")
    if update.emotion is not None:
        panel.emotion = update.emotion
        panel.emotion_overridden = True
        changed.append("emotion")
    if update.expression is not None:
        panel.expression = update.expression
        panel.expression_overridden = True
        changed.append("expression")
    if update.characters is not None:
        panel.characters = update.characters
        changed.append("characters")

    panel.is_edited = True
    project.updated_at = datetime.now(timezone.utc)
    return panel, changed


@pipeline_node("editor", "Editor")
def run(state: PipelineState) -> dict[str, Any]:
    project = project_from(state)
    edit_request = state.get("edit_request")

    if edit_request:
        panel_id = edit_request.get("panel_id")
        if not panel_id:
            raise NodeError("editor", "edit_request is missing panel_id")
        update = PanelUpdateRequest.model_validate(
            {k: v for k, v in edit_request.items() if k != "panel_id"}
        )
        try:
            panel, changed = apply_panel_update(project, panel_id, update)
        except KeyError as exc:
            raise NodeError("editor", str(exc)) from exc
        emit(f"Applied edit to {panel_id}: {', '.join(changed) or 'no fields changed'}")
    else:
        emit("No pending edits to apply")

    edited = [p.panel_id for p in project.panels if p.is_edited]
    if edited:
        emit(f"{len(edited)} panel(s) carry manual edits: {', '.join(edited)}")

    project.status = "ready"
    project.error = None
    emit(
        f"Comic finalised: {len(project.panels)} panel(s) across {len(project.pages)} page(s), "
        f"{len(project.characters)} character(s)",
        level="success",
    )

    return {"edit_request": None, **project_update(project)}
