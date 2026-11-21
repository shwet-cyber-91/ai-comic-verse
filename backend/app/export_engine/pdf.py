"""PDF export via reportlab: one comic page per PDF page, full bleed."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdf_canvas

from ..logging_config import get_logger
from ..styles.presets import get_style_preset
from .render import compose_all_pages

log = get_logger("export.pdf")


def export_pdf(project, output_path: Path) -> Path:
    pages = compose_all_pages(project)
    if not pages:
        raise ValueError("nothing to export: the project has no pages")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    first = pages[0]
    page_width, page_height = float(first.width), float(first.height)

    pdf = pdf_canvas.Canvas(str(output_path), pagesize=(page_width, page_height))
    pdf.setTitle(project.title)
    pdf.setAuthor("AI ComicVerse")
    pdf.setSubject(f"{get_style_preset(project.style).name} comic generated from a written story")

    for page in pages:
        pdf.drawImage(
            ImageReader(page),
            x=0,
            y=0,
            width=page_width,
            height=page_height,
            preserveAspectRatio=False,
            anchor="sw",
        )
        pdf.showPage()
    pdf.save()

    log.info("pdf written: %s (%d page(s))", output_path.name, len(pages))
    return output_path
