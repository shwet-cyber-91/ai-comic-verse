"""Pipeline nodes, in execution order.

``NODE_REGISTRY`` is the single place the node order lives for the graph, the API
and the progress UI. Adding a node means writing the module and adding one line
here - nothing else needs to know.
"""

from __future__ import annotations

from . import (
    camera_director,
    character_memory,
    continuity_check,
    dialogue_generation,
    editor,
    emotion_detection,
    export,
    image_generation,
    layout_generator,
    scene_planning,
    story_input,
    story_understanding,
    style_selection,
    visual_prompt,
)
from .base import NodeError, NodeSpec, emit, pipeline_node

_MODULES = [
    story_input,
    story_understanding,
    scene_planning,
    character_memory,
    emotion_detection,
    dialogue_generation,
    camera_director,
    visual_prompt,
    style_selection,
    image_generation,
    continuity_check,
    layout_generator,
    editor,
    export,
]

_DESCRIPTIONS = {
    "story_input": "Normalise the request and set up the project.",
    "story_understanding": "Genre, tone, cast, logline and narrative arc.",
    "scene_planning": "Break the story into scenes and one beat per panel.",
    "character_memory": "Build character sheets, embed references, store in the vector memory.",
    "emotion_detection": "Per-panel emotion, intensity and facial expression.",
    "dialogue_generation": "Speech, thought, narration and sound effects.",
    "camera_director": "Shot, lens, composition and movement for every panel.",
    "visual_prompt_generation": "Final image prompts with the character design restated.",
    "style_selection": "Lock the art style and its palette across all panels.",
    "image_generation": "Render each panel with reference-image conditioning.",
    "continuity_check": "Score each panel against the character references.",
    "layout_generator": "Paginate panels into grids and page templates.",
    "editor": "Apply pending edits and finalise the comic.",
    "export": "Write PDF, PNG zip, web comic and EPUB.",
}

NODE_REGISTRY: list[NodeSpec] = []
for _module in _MODULES:
    _name = _module.run.__node_name__  # type: ignore[attr-defined]
    NODE_REGISTRY.append(
        NodeSpec(
            name=_name,
            label=_name.replace("_", " ").title(),
            description=_DESCRIPTIONS[_name],
            run=_module.run,
        )
    )

NODE_BY_NAME: dict[str, NodeSpec] = {spec.name: spec for spec in NODE_REGISTRY}
NODE_ORDER: list[str] = [spec.name for spec in NODE_REGISTRY]

__all__ = [
    "NODE_BY_NAME",
    "NODE_ORDER",
    "NODE_REGISTRY",
    "NodeError",
    "NodeSpec",
    "emit",
    "pipeline_node",
]
