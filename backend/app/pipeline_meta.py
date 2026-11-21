"""Pipeline metadata - the node order, shown in the UI and used for progress.

Its own module so both ``nodes`` and ``story_input`` can read it without an
import cycle.
"""

from __future__ import annotations

from .schemas import NodeInfo

NODE_META: list[tuple[str, str, str]] = [
    ("story_input", "Story Input", "Normalise the request and set up the project."),
    ("story_understanding", "Story Understanding", "Genre, tone, cast, logline and narrative arc."),
    ("scene_planning", "Scene Planning", "Break the story into scenes and one beat per panel."),
    ("character_memory", "Character Memory", "Build character sheets, embed references, store in the vector memory."),
    ("emotion_detection", "Emotion Detection", "Per-panel emotion, intensity and facial expression."),
    ("dialogue_generation", "Dialogue Generation", "Speech, thought, narration and sound effects."),
    ("camera_director", "Camera Director", "Shot, lens, composition and movement for every panel."),
    ("visual_prompt_generation", "Visual Prompt Generation", "Final image prompts with the character design restated."),
    ("style_selection", "Style Selection", "Lock the art style and its palette across all panels."),
    ("image_generation", "Image Generation", "Render each panel with reference-image conditioning."),
    ("continuity_check", "Continuity Check", "Score each panel against the character references."),
    ("layout_generator", "Layout Generator", "Paginate panels into grids and page templates."),
    ("editor", "Editor", "Apply pending edits and finalise the comic."),
    ("export", "Export", "Write PDF, PNG zip, web comic and EPUB."),
]

NODE_NAMES: list[str] = [name for name, _, _ in NODE_META]
NODE_LABELS: dict[str, str] = {name: label for name, label, _ in NODE_META}
TOTAL_NODES: int = len(NODE_META)


def node_infos() -> list[NodeInfo]:
    return [
        NodeInfo(name=name, label=label, description=description, index=index)
        for index, (name, label, description) in enumerate(NODE_META)
    ]
