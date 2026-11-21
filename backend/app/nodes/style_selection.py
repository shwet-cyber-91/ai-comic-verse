"""Node 9 - Style Selection.

Deliberately deterministic: the style is a user choice, not something to leave to
a model. This node locks the preset across every panel, appends the preset's
prompt and negative fragments so the style survives even if an upstream prompt
omitted it, and publishes the palette and per-character colours that the mock
renderer and the exporters both use.
"""

from __future__ import annotations

from typing import Any

from ..state import PipelineState
from ..styles.presets import get_style_preset
from .base import emit, pipeline_node, project_from, project_update, request_from


@pipeline_node("style_selection", "Style Selection")
def run(state: PipelineState) -> dict[str, Any]:
    request = request_from(state)
    project = project_from(state)
    preset = get_style_preset(request.style)

    emit(f"Locking style: {preset.name} - {preset.description}")

    # deterministic per-character accent colour, used by the mock renderer for
    # characters that have no reference image
    palette = preset.palette or ["#6b7fa8"]
    character_colours = {
        character.name: palette[index % len(palette)]
        for index, character in enumerate(project.characters)
    }

    for panel in project.panels:
        panel.style = preset.id
        prompt = panel.visual_prompt or ""
        if preset.prompt_fragment not in prompt:
            panel.visual_prompt = f"{prompt}, {preset.prompt_fragment}".strip(", ").strip()
        negative = panel.negative_prompt or ""
        if preset.negative_fragment not in negative:
            panel.negative_prompt = f"{negative}, {preset.negative_fragment}".strip(", ").strip()

    if not project.characters:
        character_colours["protagonist"] = palette[0]

    emit(
        f"{preset.name} applied to {len(project.panels)} panel(s); palette {', '.join(palette[:5])}",
        data={"palette": palette, "bubble_style": preset.bubble_style},
    )

    return {
        "panels": [p.model_dump(mode="json") for p in project.panels],
        "style": {
            "id": preset.id,
            "name": preset.name,
            "prompt_fragment": preset.prompt_fragment,
            "negative_fragment": preset.negative_fragment,
            "palette": palette,
            "bubble_style": preset.bubble_style,
            "font_family": preset.font_family,
            "line_weight": preset.line_weight,
            "character_colours": character_colours,
        },
        **project_update(project),
    }
