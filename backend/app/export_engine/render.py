"""Page compositor.

Draws a laid-out page into a bitmap: panels pasted into their grid cells, then
speech bubbles, narration captions and sound effects baked on top. This is the
single renderer behind the PDF, the PNG zip and the EPUB, so all four exports
look identical.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from ..logging_config import get_logger
from ..render_utils import draw_bubble, hex_to_rgb, mix
from ..schemas import PageLayout, Panel
from ..styles.presets import get_style_preset
from ..storage import abs_path

log = get_logger("export.render")

MARGIN = 28
GUTTER = 16
PAGE_BG = (250, 248, 244)


def cell_rect(page: PageLayout, cell) -> tuple[int, int, int, int]:
    """Grid cell -> pixel rectangle (x, y, width, height)."""
    inner_w = page.width - 2 * MARGIN - (page.cols - 1) * GUTTER
    inner_h = page.height - 2 * MARGIN - (page.rows - 1) * GUTTER
    col_unit = inner_w / page.cols
    row_unit = inner_h / page.rows

    x = int(MARGIN + (cell.col_start - 1) * (col_unit + GUTTER))
    y = int(MARGIN + (cell.row_start - 1) * (row_unit + GUTTER))
    w = int(cell.col_span * col_unit + (cell.col_span - 1) * GUTTER)
    h = int(cell.row_span * row_unit + (cell.row_span - 1) * GUTTER)
    return x, y, w, h


def _fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    from ..render_utils import fit_cover

    return fit_cover(image, size)


def _panel_image(panel: Panel) -> Image.Image | None:
    if not panel.image_path:
        return None
    path = abs_path(panel.image_path)
    if not path.exists():
        log.warning("missing panel image %s", path)
        return None
    try:
        with Image.open(path) as handle:
            return handle.convert("RGB")
    except Exception as exc:
        log.warning("cannot read panel image %s: %s", path, exc)
        return None


def _draw_panel_bubbles(
    canvas: Image.Image,
    rect: tuple[int, int, int, int],
    panel: Panel,
    style_id: str,
    palette: list[str],
) -> None:
    x, y, w, h = rect
    preset = get_style_preset(style_id)
    accent = hex_to_rgb(palette[0] if palette else "#141418")
    inset = 10
    cursor = y + inset

    if panel.narration:
        box_h = max(58, int(h * 0.20))
        draw_bubble(
            canvas,
            panel.narration,
            (x + inset, cursor, x + w - inset, cursor + box_h),
            kind="narration",
            bubble_style=preset.bubble_style,
            font_family=preset.font_family,
            accent=accent,
        )
        cursor += box_h + 8

    # dialogue: alternate sides so two speakers read as a conversation
    slot_h = max(66, int(h * 0.28))
    drawn = 0
    for line in panel.dialogue[:3]:
        if cursor + slot_h > y + h - inset:
            break
        bubble_w = min(int(w * 0.62), 340)
        on_left = drawn % 2 == 0 and len(panel.dialogue) > 1
        if len(panel.dialogue) == 1:
            on_left = True
        bx = x + inset if on_left else x + w - inset - bubble_w
        text = f"{line.speaker}: {line.text}" if line.speaker and line.speaker != "Narrator" else line.text
        draw_bubble(
            canvas,
            text,
            (bx, cursor, bx + bubble_w, cursor + slot_h),
            kind=line.kind if line.kind in ("speech", "thought", "shout", "whisper") else "speech",
            bubble_style=preset.bubble_style,
            font_family=preset.font_family,
            accent=accent,
            tail="bottom-left" if on_left else "bottom-right",
        )
        cursor += slot_h + 6
        drawn += 1

    if panel.sfx:
        sfx_w = int(w * 0.5)
        draw_bubble(
            canvas,
            panel.sfx,
            (x + w - inset - sfx_w, y + h - inset - 90, x + w - inset, y + h - inset - 10),
            kind="sfx",
            bubble_style=preset.bubble_style,
            font_family=preset.font_family,
            accent=accent,
        )


def compose_page(
    page: PageLayout,
    panels_by_id: dict[str, Panel],
    style_id: str = "manga",
    draw_bubbles: bool = True,
) -> Image.Image:
    """Render one page to a PIL image."""
    preset = get_style_preset(style_id)
    palette = preset.palette or ["#141418"]

    background = mix(PAGE_BG, hex_to_rgb(palette[-1] if palette else "#ffffff"), 0.06)
    canvas = Image.new("RGB", (page.width, page.height), background)
    draw = ImageDraw.Draw(canvas)

    missing: list[str] = []
    for cell in page.cells:
        panel = panels_by_id.get(cell.panel_id)
        rect = cell_rect(page, cell)
        x, y, w, h = rect

        if panel is None:
            missing.append(cell.panel_id)
            draw.rectangle(rect, fill=(226, 226, 230), outline=(120, 120, 130), width=3)
            draw.text((x + 12, y + 12), f"missing panel {cell.panel_id}", fill=(90, 90, 100))
            continue

        image = _panel_image(panel)
        if image is None:
            missing.append(cell.panel_id)
            draw.rectangle(rect, fill=(232, 230, 226), outline=(120, 120, 130), width=3)
            draw.text((x + 12, y + 12), f"{panel.panel_id} not rendered", fill=(90, 90, 100))
            continue

        canvas.paste(_fit(image, (w, h)), (x, y))

        # panel border, in the style's ink colour
        ink = hex_to_rgb(palette[0] if palette else "#141418")
        border = 5 if preset.line_weight == "bold" else 3
        for i in range(border):
            draw.rectangle((x + i, y + i, x + w - 1 - i, y + h - 1 - i), outline=ink)

        if draw_bubbles:
            _draw_panel_bubbles(canvas, rect, panel, style_id, palette)

    # page furniture
    ink = hex_to_rgb(palette[0] if palette else "#141418")
    draw.text((MARGIN, page.height - MARGIN + 4), f"page {page.index}", fill=ink)
    total = len(page.cells)
    draw.text(
        (page.width - MARGIN - 60, page.height - MARGIN + 4),
        f"{total} panel" + ("s" if total != 1 else ""),
        fill=ink,
    )

    if missing:
        log.warning("page %s composed with %d missing panel(s)", page.page_id, len(missing))
    return canvas


def compose_all_pages(project, draw_bubbles: bool = True) -> list[Image.Image]:
    panels_by_id = project.panel_map()
    return [
        compose_page(page, panels_by_id, project.style, draw_bubbles=draw_bubbles)
        for page in project.pages
    ]
