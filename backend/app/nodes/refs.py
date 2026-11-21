"""Reference-image lookup shared by image generation and the continuity checker.

Both stages must agree on exactly which images represent a character, otherwise
the checker would score against something the renderer never used.
"""

from __future__ import annotations

from typing import Sequence

from ..schemas import CharacterSheet
from ..storage import abs_path


def normalise(value: str) -> str:
    return " ".join((value or "").lower().split())


def character_lookup(characters: Sequence[CharacterSheet]) -> dict[str, CharacterSheet]:
    return {normalise(c.name): c for c in characters}


def panel_reference_paths(
    panel_characters: Sequence[str],
    characters: Sequence[CharacterSheet],
    limit: int = 2,
) -> tuple[list[str], dict[str, str]]:
    """Absolute paths for the characters in one panel, best conditioning first.

    Raw uploads come before the derived canonical card, because the upload is the
    true identity signal and the card is a re-render of it.
    """
    lookup = character_lookup(characters)
    paths: list[str] = []
    colours: dict[str, str] = {}
    palette_index = 0

    for name in panel_characters:
        sheet = lookup.get(normalise(name))
        if sheet is None:
            continue
        for rel in sheet.reference_images:
            candidate = abs_path(rel)
            if candidate.exists():
                paths.append(str(candidate))
        if sheet.canonical_image:
            candidate = abs_path(sheet.canonical_image)
            if candidate.exists():
                paths.append(str(candidate))
        palette = sheet.palette or []
        if palette:
            colours[name] = palette[palette_index % len(palette)]
            palette_index += 1

    seen: set[str] = set()
    unique = [p for p in paths if not (p in seen or seen.add(p))]
    return unique[:limit], colours
