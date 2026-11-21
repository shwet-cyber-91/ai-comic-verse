"""Export engine tests: all four formats, built from a hand-made project.

The project is assembled directly rather than generated, so these tests fail for
export reasons and never because of a pipeline problem.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.config import get_settings
from app.export_engine import ALL_FORMATS, export_project
from app.layout_templates import TEMPLATES, choose_template
from app.nodes.layout_generator import paginate
from app.schemas import CameraSpec, ComicProject, DialogueLine, Panel
from app.storage import abs_path, rel_path


def _art(path: Path, colour: tuple[int, int, int], label: str) -> Path:
    image = Image.new("RGB", (512, 384), colour)
    draw = ImageDraw.Draw(image)
    draw.rectangle((16, 16, 496, 368), outline=(20, 20, 24), width=6)
    draw.ellipse((180, 90, 330, 240), fill=(240, 216, 188))
    draw.rectangle((214, 136, 232, 154), fill=(26, 22, 28))
    draw.rectangle((278, 136, 296, 154), fill=(26, 22, 28))
    draw.text((24, 336), label, fill=(250, 250, 250))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def out(relative: str) -> Path:
    """A storage-relative export path resolved to somewhere we can read."""
    return abs_path(relative)


@pytest.fixture
def project(fresh_app_state) -> ComicProject:
    panel_dir = get_settings().project_subdirs("export001")["panels"]
    panels: list[Panel] = []

    for index, colour in enumerate(
        [(54, 48, 64), (72, 44, 40), (40, 62, 74), (60, 60, 44)], start=1
    ):
        image_path = _art(panel_dir / f"p{index:03d}.png", colour, f"panel {index}")
        panels.append(
            Panel(
                panel_id=f"p{index:03d}",
                index=index,
                scene_id="s001",
                scene_summary="Mira lands on the observatory roof at dusk.",
                scene_setting="observatory roof, dusk",
                characters=["Mira"],
                action="Mira steps out of the glider.",
                emotion="determination",
                dialogue=[
                    DialogueLine(
                        speaker="Mira",
                        text=f"Line {index}: we fly it out together.",
                        kind="speech",
                    )
                ],
                narration="A beat of quiet before the storm." if index == 1 else None,
                sfx="WHOOSH" if index == 2 else None,
                camera=CameraSpec(shot="medium", lens="35mm"),
                visual_prompt="a courier on a rooftop at dusk, manga style",
                image_path=rel_path(image_path),
                image_url=f"/static/{rel_path(image_path)}",
                image_provider="mock",
                continuity_score=0.81,
                continuity_passed=True,
            )
        )

    comic = ComicProject(
        project_id="export001",
        title="The Last Star Chart",
        style="manga",
        status="ready",
        story_text="Mira lands on the roof.\nKestrel is packing star charts.",
        panel_count=len(panels),
        panels_per_page=2,
        panels=panels,
    )
    comic.pages = paginate(comic.panels, comic.panels_per_page)
    return comic


def test_every_panel_count_gets_a_usable_template():
    for count in range(1, 10):
        name, cells, rows = choose_template(count, 0)
        assert name in TEMPLATES or name == "auto_grid"
        assert len(cells) == count, f"{count} panels produced {len(cells)} cells"
        assert rows >= 1


def test_export_writes_all_four_formats(project):
    results = export_project(project, ALL_FORMATS)

    assert set(results) == set(ALL_FORMATS)
    suffixes = {"pdf": ".pdf", "png_zip": ".zip", "web": ".html", "epub": ".epub"}
    for fmt, relative in results.items():
        path = out(relative)
        assert path.name.endswith(suffixes[fmt])
        assert path.exists(), f"{fmt} was not written"
        assert path.stat().st_size > 1000, f"{fmt} looks empty"


def test_pdf_is_a_real_pdf(project):
    data = out(export_project(project, ["pdf"])["pdf"]).read_bytes()

    assert data[:4] == b"%PDF"
    assert b"%%EOF" in data[-2048:]


def test_png_zip_contains_pages_panels_and_metadata(project):
    results = export_project(project, ["png_zip"])

    with zipfile.ZipFile(out(results["png_zip"])) as archive:
        names = set(archive.namelist())
        assert {"project.json", "story.txt", "README.txt"} <= names
        assert sum(1 for name in names if name.startswith("pages/")) == len(project.pages)
        assert sum(1 for name in names if name.startswith("panels/")) == len(project.panels)

        payload = json.loads(archive.read("project.json"))
        assert payload["title"] == project.title
        assert len(payload["panels"]) == len(project.panels)
        assert archive.read("pages/page01.png")[:8] == b"\x89PNG\r\n\x1a\n"
        assert b"The Last Star Chart" in archive.read("README.txt")


def test_web_export_is_self_contained_html(project):
    html = out(export_project(project, ["web"])["web"]).read_text(encoding="utf-8")

    assert html.lstrip().startswith("<!doctype html>")
    assert "data:image/jpeg;base64," in html, "images must be embedded, not linked"
    assert project.title in html
    assert html.count("<figure") == len(project.pages)
    assert "http://" not in html and "https://" not in html, "no external assets allowed"


def test_epub_is_a_valid_zip_with_the_comic_in_it(project):
    results = export_project(project, ["epub"])

    with zipfile.ZipFile(out(results["epub"])) as archive:
        names = archive.namelist()
        assert "mimetype" in names
        assert archive.read("mimetype") == b"application/epub+zip"
        assert any(name.endswith(".opf") for name in names)
        assert any(name.endswith(".ncx") for name in names)
        pngs = [name for name in names if name.endswith(".png")]
        assert len(pngs) >= len(project.pages), "every page plus the cover must be in the book"


def test_export_rejects_an_empty_project(project):
    project.panels = []
    project.pages = []

    with pytest.raises(ValueError):
        export_project(project, ["pdf"])


def test_export_rejects_unknown_formats(project):
    with pytest.raises(ValueError):
        export_project(project, ["docx"])


def test_one_broken_format_does_not_block_the_others(project, monkeypatch):
    import app.export_engine as engine

    def boom(project, output_path):
        raise RuntimeError("PDF backend unavailable")

    monkeypatch.setitem(engine.EXPORTERS, "pdf", (boom, ".pdf"))
    results = export_project(project, ["pdf", "web"])

    assert "pdf" not in results
    assert "web" in results


def test_export_records_paths_on_the_project(project):
    results = export_project(project, ["web", "pdf"])
    recorded = project.exports.as_dict()

    assert set(recorded) == set(results)
    assert recorded["web"].endswith(".html")
    assert recorded["pdf"].endswith(".pdf")
