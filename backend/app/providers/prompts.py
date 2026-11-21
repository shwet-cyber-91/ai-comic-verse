"""Task prompts for LLM-backed nodes.

The JSON schema is injected into every prompt automatically, so a new node only
needs to register a task description here - none of the provider backends need
to change.
"""

from __future__ import annotations

import json
from typing import Any, Type

from pydantic import BaseModel

BASE_SYSTEM = (
    "You are a senior comic writer and storyboard artist working on an original "
    "comic. You always reply with a single valid JSON value and nothing else. "
    "Never write markdown fences, comments or explanatory prose. "
    "All characters are original - never reference or describe existing "
    "copyrighted characters, brands or real public figures."
)

TASK_INSTRUCTIONS: dict[str, str] = {
    "story_understanding": (
        "Analyse the story. Identify genre, tone, setting, time period, themes, a "
        "one-sentence logline, and every recurring character with a role and a short "
        "appearance note. Decide how many distinct scenes the story needs "
        "(scene_count, 1-8). narrative_arc is an ordered list of 3-5 short beats."
    ),
    "character_sheet": (
        "Produce a production character sheet for each character: physical "
        "appearance (age, build, hair, eyes, skin, notable marks), outfit, "
        "personality, 3-6 distinguishing features that must stay identical in every "
        "panel, a 3-5 colour palette as hex strings, and signature props. "
        "Be specific and visual - these strings drive image generation and "
        "must keep the character consistent across panels."
    ),
    "scene_planning": (
        "Break the story into sequential scenes. For each scene give an id "
        "(s1, s2, ...), a title, a one-sentence summary, the setting, time of day, "
        "which characters appear, the action, the mood, and a list of 'beats'. "
        "Every beat is ONE comic panel. The total number of beats across all scenes "
        "must equal exactly the requested panel_count."
    ),
    "emotion_detection": (
        "For each panel beat, decide the dominant emotion, its intensity (0-1) and "
        "the visible facial expression. The expression MUST be described with specific "
        "visual details: exact eye shape (wide, narrowed, squinting, teary), "
        "eyebrow position (raised, furrowed, arched), mouth shape (smiling, frowning, "
        "open, pursed, gritted teeth), and any other facial cues (flushed cheeks, "
        "twitching lip, sweat drop). Do NOT use vague terms like 'emotional' or "
        "'expressive' — describe exactly what the viewer sees. Emotion must serve "
        "the story beat and should evolve rather than repeat."
    ),
    "dialogue_generation": (
        "Write the dialogue for each panel: 0-2 short lines (max 18 words each) "
        "with a speaker, plus optional narration (first panel of a scene only) and "
        "optional sfx. kind is one of speech, thought, shout, whisper. "
        "Keep speech natural and in character. Do not describe the art."
    ),
    "camera_director": (
        "Choose the camera for each panel: shot (establishing_wide, wide, medium, "
        "medium_close, close_up, extreme_close_up, over_the_shoulder, low_angle, "
        "high_angle, bird_eye, dutch_angle), lens, composition, movement and a "
        "one-line rationale. Vary the shots - do not use the same shot repeatedly, "
        "and use establishing_wide to open a scene and close_up for emotional peaks."
    ),
    "visual_prompt_generation": (
        "Write the final image-generation prompt for each panel. The prompt MUST be "
        "a single comma-separated description that is highly detailed and explicit. "
        "CRITICAL: The facial expression must be vividly described using specific "
        "visual cues (e.g., 'eyes wide with fear', 'jaw clenched in anger', "
        "'tears streaming down cheeks', 'mouth curved in a sly smile'). Do NOT use "
        "vague words like 'emotional' or 'expressive' — describe exactly what the "
        "face looks like. Include: subject, detailed facial expression with muscle "
        "movements, action, clothing, setting, lighting, camera shot and art style. "
        "Restate the character's fixed appearance details for consistency. "
        "Also write a negative prompt that excludes: blurry, low quality, bad anatomy, "
        "mutated hands, extra fingers, deformed face, blank expression, emotionless."
    ),
}


def build_prompt(task: str, payload: dict[str, Any], schema: Type[BaseModel]) -> tuple[str, str]:
    """Return (system, user) for a task, with the schema spelled out."""
    instruction = TASK_INSTRUCTIONS.get(task, f"Complete the '{task}' task.")
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    system = f"{BASE_SYSTEM}\n\nTASK: {instruction}"

    user_parts = [
        "INPUT DATA:",
        json.dumps(payload, indent=2, default=str),
        "",
        "Reply with a single JSON value matching exactly this JSON Schema:",
        schema_json,
    ]
    return system, "\n".join(user_parts)
