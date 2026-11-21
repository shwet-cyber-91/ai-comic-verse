"""Continuity checker tests: does it actually tell a character apart from not?"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.continuity import cv2_available, get_checker
from app.embeddings import cosine_similarity, get_embedder


def _write(path: Path, image: Image.Image) -> Path:
    image.save(path)
    return path


@pytest.fixture
def character_reference(tmp_path: Path) -> Path:
    image = Image.new("RGB", (256, 256), (214, 184, 142))
    draw = ImageDraw.Draw(image)
    draw.ellipse((76, 50, 180, 168), fill=(240, 216, 188))  # face
    draw.rectangle((104, 84, 122, 102), fill=(26, 22, 28))  # eyes
    draw.rectangle((138, 84, 156, 102), fill=(26, 22, 28))
    draw.rectangle((88, 30, 172, 62), fill=(38, 30, 46))  # hair
    draw.rectangle((40, 184, 216, 256), fill=(44, 82, 126))  # jacket
    return _write(tmp_path / "mira.png", image)


@pytest.fixture
def same_character(tmp_path: Path, character_reference: Path) -> Path:
    """The reference in a wider panel, the way the renderer composites it.

    ``fit_cover`` scales the art until it *covers* the panel and then centre-crops
    the overflow, so the character fills the frame rather than floating in a dead
    border. Reproducing that here matters: a panel that is mostly background is a
    panel no continuity checker should be expected to match, and testing against
    one would only measure the fixture's empty margin.
    """
    panel = Image.new("RGB", (384, 256), (52, 48, 64))
    with Image.open(character_reference) as reference:
        covering = reference.convert("RGB").resize((384, 384))  # cover the width
        panel.paste(covering.crop((0, 64, 384, 320)), (0, 0))  # centre-crop to height
    draw = ImageDraw.Draw(panel)
    draw.rectangle((0, 0, 384, 12), fill=(20, 18, 26))
    return _write(tmp_path / "panel_same.png", panel)


@pytest.fixture
def different_scene(tmp_path: Path) -> Path:
    """A green field with a white sun: same shape of picture, nothing in common."""
    panel = Image.new("RGB", (384, 256), (28, 122, 54))
    draw = ImageDraw.Draw(panel)
    draw.ellipse((280, 24, 348, 92), fill=(248, 244, 220))
    for x in range(0, 384, 24):
        draw.line((x, 256, x + 40, 150), fill=(18, 90, 40), width=5)
    return _write(tmp_path / "panel_diff.png", panel)


# --------------------------------------------------------------------------- #
# Embeddings
# --------------------------------------------------------------------------- #


def test_cosine_similarity_is_sane():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([], []) == 0.0


def test_embedder_is_deterministic(character_reference: Path):
    embedder = get_embedder()
    with Image.open(character_reference) as image:
        rgb = image.convert("RGB")
        first = embedder.embed_pil(rgb)
        second = embedder.embed_pil(rgb)

    assert first == second
    assert len(first) == embedder.dim
    assert any(value != 0.0 for value in first)


def test_embedder_separates_a_portrait_from_a_landscape(
    character_reference: Path, different_scene: Path
):
    embedder = get_embedder()
    with Image.open(character_reference) as a, Image.open(different_scene) as b:
        same = cosine_similarity(embedder.embed_pil(a.convert("RGB")), embedder.embed_pil(a.convert("RGB")))
        other = cosine_similarity(embedder.embed_pil(a.convert("RGB")), embedder.embed_pil(b.convert("RGB")))

    assert same == pytest.approx(1.0)
    assert other < same, "an unrelated image must not score as high as the image itself"


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def test_same_character_scores_high_and_passes(same_character: Path, character_reference: Path):
    checker = get_checker()
    score = checker.score_panel("p001", same_character, [str(character_reference)])

    assert score.passed, f"expected a pass, got {score.score} ({score.details})"
    assert score.score > checker.threshold
    assert score.embedding_score > 0.5
    assert score.best_reference == character_reference.name
    assert score.details["threshold"] == checker.threshold


def test_a_different_scene_scores_lower_than_the_right_one(
    same_character: Path, different_scene: Path, character_reference: Path
):
    checker = get_checker()
    good = checker.score_panel("p001", same_character, [str(character_reference)])
    bad = checker.score_panel("p002", different_scene, [str(character_reference)])

    assert bad.score < good.score, (
        f"the checker must prefer the real character ({good.score}) "
        f"over an unrelated panel ({bad.score})"
    )


def test_threshold_decides_pass_and_fail(same_character: Path, different_scene: Path, character_reference: Path):
    checker = get_checker()
    good = checker.score_panel("p001", same_character, [str(character_reference)])
    bad = checker.score_panel("p002", different_scene, [str(character_reference)])
    assert good.score > bad.score, "the two panels must be distinguishable for this test to mean anything"

    # a bar set between the two scores must let the right panel through and stop the other
    checker.threshold = (good.score + bad.score) / 2
    assert checker.score_panel("p001", same_character, [str(character_reference)]).passed
    assert not checker.score_panel("p002", different_scene, [str(character_reference)]).passed

    # and a bar above every attainable score stops everything, since the score
    # is a convex blend of two values that are themselves clipped to 0..1
    checker.threshold = 1.0001
    assert not checker.score_panel("p001", same_character, [str(character_reference)]).passed


def test_a_panel_with_no_reference_is_skipped_not_failed(tmp_path: Path):
    """Otherwise the retry loop would spin on panels nobody was cast in."""
    panel = _write(tmp_path / "crowd.png", Image.new("RGB", (128, 128), (90, 90, 100)))
    score = get_checker().score_panel("p003", panel, [])

    assert score.passed
    assert score.details.get("skipped")


def test_a_missing_panel_image_fails_rather_than_crashing(character_reference: Path, tmp_path: Path):
    score = get_checker().score_panel("p004", tmp_path / "nope.png", [str(character_reference)])

    assert not score.passed
    assert score.score == 0.0
    assert "error" in score.details


def test_scoring_is_deterministic(same_character: Path, character_reference: Path):
    checker = get_checker()
    first = checker.score_panel("p001", same_character, [str(character_reference)])
    second = checker.score_panel("p001", same_character, [str(character_reference)])

    assert first.score == pytest.approx(second.score)


def test_checker_reports_which_extras_are_installed(same_character: Path, character_reference: Path):
    """The checker must work without OpenCV, and say so when it does."""
    score = get_checker().score_panel("p001", same_character, [str(character_reference)])
    assert isinstance(cv2_available(), bool)
    assert isinstance(score.details["opencv"], bool)
    assert score.details["per_reference"]
