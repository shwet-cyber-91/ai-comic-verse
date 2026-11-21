"""Node 4 - Character Memory.

For every character: produce a production sheet, build a canonical "character
card" image (the style-filtered reference, or a drawn stand-in when the user
supplied none), embed it, and store the embedding plus the sheet in the character
memory (ChromaDB or the JSON store).

That card is what the continuity checker compares panels against, and what the
image provider conditions on - which is why a 1-2 image reference is enough to
hold a design steady across a whole comic.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from ..config import get_settings
from ..embeddings import get_embedder
from ..logging_config import get_logger
from ..memory import get_memory
from ..providers.registry import get_llm
from ..render_utils import fit_cover, hex_to_rgb, placeholder_portrait, style_filter
from ..schemas import CharacterSheet, CharacterSheetDraft, CharacterSheetPlan
from ..state import PipelineState
from ..storage import abs_path, rel_path, safe_slug, static_url
from ..styles.presets import get_style_preset
from .base import emit, pipeline_node, project_from, project_update, request_from

log = get_logger("nodes.character_memory")

CARD_SIZE = 512


def _card_colour(name: str, style: str, index: int) -> str:
    """Deterministic fallback colour for characters without a reference image."""
    palette = get_style_preset(style).palette or ["#6b7fa8"]
    return palette[index % len(palette)]


def _build_card(
    project_id: str,
    name: str,
    reference_rel_paths: list[str],
    style: str,
    colour: str,
) -> str:
    """Write the canonical character card and return its storage-relative path."""
    settings = get_settings()
    target_dir = settings.project_subdirs(project_id)["refs"]
    target = target_dir / f"{safe_slug(name)}_canonical.png"

    source = None
    for rel in reference_rel_paths:
        candidate = abs_path(rel)
        if candidate.exists():
            source = candidate
            break

    if source is not None:
        try:
            with Image.open(source) as handle:
                card = fit_cover(handle.convert("RGB"), (CARD_SIZE, CARD_SIZE), centering=(0.5, 0.35))
            card = style_filter(card, style)
        except Exception as exc:
            log.warning("could not build card from %s: %s", source, exc)
            source = None

    if source is None:
        card = placeholder_portrait((CARD_SIZE, CARD_SIZE), hex_to_rgb(colour), "neutral", name).convert("RGB")
        card = style_filter(card, style)

    card.save(target, format="PNG", optimize=True)
    return rel_path(target)


def _normalise_name(value: str) -> str:
    return " ".join(value.lower().split())


@pipeline_node("character_memory", "Character Memory")
def run(state: PipelineState) -> dict[str, Any]:
    request = request_from(state)
    project = project_from(state)
    llm = get_llm()
    embedder = get_embedder()
    memory = get_memory(project.project_id)

    analysis = project.story_analysis
    drafts: list[dict[str, Any]] = []
    if analysis and analysis.characters:
        drafts = [c.model_dump(mode="json") for c in analysis.characters]

    # characters the user uploaded but the analysis missed must still be in the cast
    known = {_normalise_name(d.get("name", "")) for d in drafts}
    user_refs: dict[str, dict[str, Any]] = {}
    for character in request.characters:
        user_refs[_normalise_name(character.name)] = character.model_dump(mode="json")
        if _normalise_name(character.name) not in known:
            drafts.append(
                {
                    "name": character.name,
                    "role": "supporting",
                    "appearance": character.description,
                    "personality": "",
                    "importance": 3,
                }
            )
            known.add(_normalise_name(character.name))

    if not drafts:
        drafts = [{"name": "the narrator", "role": "protagonist", "appearance": "", "personality": "", "importance": 3}]

    emit(f"Building {len(drafts)} character sheet(s) with {llm.name}")
    sheet_plan = llm.complete_json(
        "character_sheet",
        {
            "characters": drafts,
            "style": request.style,
            "story_analysis": analysis.model_dump(mode="json") if analysis else {},
        },
        CharacterSheetPlan,
    )

    returned = {_normalise_name(c.name): c for c in sheet_plan.characters}
    sheets: list[CharacterSheet] = []

    for index, draft in enumerate(drafts):
        name = draft["name"]
        key = _normalise_name(name)
        generated: CharacterSheetDraft | None = returned.get(key)

        if generated is None:
            generated = CharacterSheetDraft(
                name=name,
                role=draft.get("role", "supporting"),
                appearance=draft.get("appearance", ""),
                personality=draft.get("personality", ""),
                distinguishing_features=[],
                palette=get_style_preset(request.style).palette[:4],
            )

        character_id = f"c_{safe_slug(name)}"
        references = list(user_refs.get(key, {}).get("reference_images") or [])
        usable = [r for r in references if abs_path(r).exists()]
        if references and not usable:
            emit(f"  reference images for {name} could not be read; using the written description", level="warning")

        colour = _card_colour(name, request.style, index)
        card_rel = _build_card(project.project_id, name, usable, request.style, colour)
        embedding = embedder.embed_image(str(abs_path(card_rel)))
        appearance_count = sum(
            1 for panel in project.panels if key in {_normalise_name(n) for n in panel.characters}
        )

        sheet = CharacterSheet(
            character_id=character_id,
            name=name,
            role=generated.role or draft.get("role", "supporting"),
            appearance=generated.appearance,
            outfit=generated.outfit,
            personality=generated.personality,
            distinguishing_features=generated.distinguishing_features,
            palette=generated.palette or get_style_preset(request.style).palette[:4],
            signature_props=generated.signature_props,
            reference_images=usable,
            reference_urls=[static_url(r) or "" for r in usable],
            canonical_image=card_rel,
            canonical_url=static_url(card_rel),
            embedding_id=character_id,
            embedding_backend=embedder.name,
            appearance_count=appearance_count,
        )
        sheets.append(sheet)

        document = (
            f"{sheet.name} ({sheet.role}): {sheet.appearance} "
            f"Wearing {sheet.outfit}. "
            f"Distinguishing features: {', '.join(sheet.distinguishing_features) or 'none noted'}."
        ).strip()
        memory.upsert(
            character_id,
            embedding,
            metadata={
                "project_id": project.project_id,
                "name": name,
                "role": sheet.role,
                "canonical_image": card_rel,
                "colour": colour,
                "reference_count": len(usable),
                "embedding_backend": embedder.name,
            },
            document=document,
        )

        emit(
            f"  {name}: {len(usable)} reference image(s), appears in {appearance_count} panel(s)",
            data={"character_id": character_id, "canonical": static_url(card_rel)},
        )

    project.characters = sheets
    stored = memory.count()
    emit(
        f"Character memory now holds {stored} record(s) in the {memory.backend} store "
        f"({embedder.name} embeddings)",
        data={"backend": memory.backend, "embedder": embedder.name},
    )

    return {
        "characters": [s.model_dump(mode="json") for s in sheets],
        **project_update(project),
    }
