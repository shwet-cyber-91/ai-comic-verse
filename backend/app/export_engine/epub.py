"""EPUB export via EbookLib: one XHTML page per comic page, with a script log."""

from __future__ import annotations

from html import escape
from io import BytesIO
from pathlib import Path

from ..logging_config import get_logger
from ..styles.presets import get_style_preset
from .render import compose_all_pages

log = get_logger("export.epub")


def _png_bytes(image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def export_epub(project, output_path: Path) -> Path:
    from ebooklib import epub

    images = compose_all_pages(project)
    if not images:
        raise ValueError("nothing to export: the project has no pages")

    preset = get_style_preset(project.style)
    book = epub.EpubBook()
    book.set_identifier(f"comicverse-{project.project_id}")
    book.set_title(project.title)
    book.set_language(project.language or "en")
    book.add_author("AI ComicVerse")

    chapters = []
    for index, image in enumerate(images, start=1):
        name = f"page_{index:02d}.png"
        image_item = epub.EpubItem(
            uid=f"image_{index}",
            file_name=f"images/{name}",
            media_type="image/png",
            content=_png_bytes(image),
        )
        book.add_item(image_item)

        chapter = epub.EpubHtml(
            title=f"Page {index}",
            file_name=f"page_{index:02d}.xhtml",
            lang=project.language or "en",
        )
        chapter.content = (
            '<html xmlns="http://www.w3.org/1999/xhtml">'
            "<head><title>Page {i}</title>"
            "<style>body{{margin:0;text-align:center}}img{{max-width:100%;height:auto}}</style>"
            "</head><body>"
            '<img src="images/{n}" alt="Page {i}"/>'
            "</body></html>"
        ).format(i=index, n=name)
        book.add_item(chapter)
        chapters.append(chapter)

    if project.story_text.strip():
        script = epub.EpubHtml(title="Source story", file_name="story.xhtml", lang=project.language or "en")
        paragraphs = "".join(
            f"<p>{escape(block.strip())}</p>"
            for block in project.story_text.split("\n")
            if block.strip()
        )
        script.content = (
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Source story</title></head><body>'
            '<h1>Source story</h1>'
            f"{paragraphs}"
            "</body></html>"
        )
        book.add_item(script)
        chapters.append(script)

    toc = epub.EpubHtml(title="Table of contents", file_name="toc.xhtml", lang=project.language or "en")
    toc_items = "".join(
        f'<li><a href="{chapter.file_name}">{escape(chapter.title)}</a></li>'
        for chapter in chapters
    )
    toc.content = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Table of contents</title></head><body>'
        '<h1>Table of contents</h1><nav epub:type="toc"><ol>'
        f"{toc_items}"
        "</ol></nav></body></html>"
    )
    book.add_item(toc)
    book.add_item(epub.EpubNcx())

    book.toc = tuple(chapters)
    book.spine = chapters
    book.set_cover("cover.png", _png_bytes(images[0]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output_path), book, {})
    log.info("epub written: %s (%d page(s), %s)", output_path.name, len(images), preset.name)
    return output_path
