"""Node 10 - Image Generation.

Renders every panel, or - inside the continuity retry loop - just the panels the
checker rejected. Character sheets are included in each panel's prompt;
reference-capable providers additionally receive uploaded reference images.

Retries vary the seed so a re-render is actually different, and re-ask for the
same prompt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import get_settings
from ..logging_config import get_logger
from ..providers.base import ImageRequest
from ..providers.registry import get_image_provider
from ..state import PipelineState
from ..storage import rel_path, static_url
from .base import emit, pipeline_node, project_from, project_update, request_from
from .refs import panel_reference_paths

log = get_logger("nodes.image_generation")


@pipeline_node("image_generation", "Image Generation")
def run(state: PipelineState) -> dict[str, Any]:
    request = request_from(state)
    project = project_from(state)
    settings = get_settings()
    provider = get_image_provider()

    targets = state.get("regenerate_panel_ids") or []
    is_retry = bool(targets)
    if is_retry:
        panels = [p for p in project.panels if p.panel_id in set(targets)]
        emit(
            f"Regenerating {len(panels)} panel(s) (round {state.get('retry', 0)}): {', '.join(targets)}",
            level="warning",
        )
    else:
        panels = list(project.panels)
        emit(
            f"Rendering {len(panels)} panel(s) with the '{provider.name}' provider"
            + (" (reference-conditioned)" if provider.supports_reference_images else " (text-only)")
        )

    panel_dir = settings.project_subdirs(project.project_id)["panels"]
    style_config = state.get("style") or {}
    character_colours = dict(style_config.get("character_colours") or {})
    character_lookup = {character.name.casefold(): character for character in project.characters}

    failures: list[str] = []
    for panel in panels:
        references, colours = panel_reference_paths(panel.characters, project.characters)
        character_colours.update(colours)
        character_descriptions = {}
        for name in panel.characters:
            character = character_lookup.get(name.casefold())
            if character is None:
                continue
            details = [
                character.appearance,
                f"outfit: {character.outfit}" if character.outfit else "",
                (
                    "distinctive features: " + ", ".join(character.distinguishing_features)
                    if character.distinguishing_features
                    else ""
                ),
                (
                    "signature props: " + ", ".join(character.signature_props)
                    if character.signature_props
                    else ""
                ),
            ]
            description = "; ".join(detail.strip() for detail in details if detail.strip())
            if description:
                character_descriptions[name] = description

        if not provider.supports_reference_images:
            emit(
                f"  {panel.panel_id}: {provider.name} uses character descriptions, "
                "not uploaded images, for visual consistency",
                level="warning",
            )
        elif not references:
            emit(
                f"  {panel.panel_id}: no reference image for {', '.join(panel.characters) or 'nobody'} - "
                f"relying on the prompt alone",
                level="warning",
            )

        seed = (panel.seed or project.seed) + panel.regenerations * 977
        output_path = panel_dir / f"{panel.panel_id}.png"

        image_request = ImageRequest(
            panel_id=panel.panel_id,
            prompt=panel.visual_prompt,
            negative_prompt=panel.negative_prompt,
            style=panel.style,
            size=settings.image_size,
            seed=seed,
            output_path=str(output_path),
            reference_images=references,
            character_names=panel.characters or ["protagonist"],
            character_descriptions=character_descriptions,
            character_colors=character_colours,
            action=panel.action,
            emotion=panel.emotion,
            shot=panel.camera.shot if panel.camera else "medium",
            setting=panel.scene_setting,
            time_of_day=(panel.scene_setting.split(",")[-1].strip() if panel.scene_setting else "day"),
            dialogue_hint=" ".join(line.text for line in panel.dialogue)[:160],
        )

        try:
            result = provider.generate(image_request)
        except Exception as exc:
            log.exception("panel %s failed to render", panel.panel_id)
            failures.append(panel.panel_id)
            emit(f"  {panel.panel_id} failed: {exc}", level="error")
            continue

        try:
            relative = rel_path(Path(result.path))
        except ValueError:
            relative = f"projects/{project.project_id}/panels/{panel.panel_id}.png"

        panel.image_path = relative
        panel.image_url = static_url(relative)
        panel.seed = result.seed
        panel.image_provider = result.provider
        emit(
            f"  {panel.panel_id} rendered ({panel.camera.shot if panel.camera else 'medium'}, "
            f"{panel.emotion}, seed {result.seed})",
            data={"image_url": panel.image_url, "panel_id": panel.panel_id},
        )

    if failures:
        emit(
            f"{len(failures)} panel(s) failed to render; retrying only those panels",
            level="warning",
            data={"panels": failures},
        )

    return {
        "panels": [p.model_dump(mode="json") for p in project.panels],
        "regenerate_panel_ids": failures,
        **project_update(project),
    }
