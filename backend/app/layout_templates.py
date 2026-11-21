"""Page layout templates.

Cells are placed on a 12-column grid; ``col_start``/``row_start`` are 1-based so
the same numbers map straight onto CSS ``grid-column`` / ``grid-row`` in the
frontend editor and onto pixel rectangles in the export compositor.
"""

from __future__ import annotations

import math

from .schemas import PanelCell, PageLayout

GRID_COLS = 12

# template name -> (rows, [(col_start, col_span, row_start, row_span), ...])
TEMPLATES: dict[str, tuple[int, list[tuple[int, int, int, int]]]] = {
    "splash": (1, [(1, 12, 1, 1)]),
    "two_horizontal": (2, [(1, 12, 1, 1), (1, 12, 2, 1)]),
    "two_vertical": (1, [(1, 6, 1, 1), (7, 6, 1, 1)]),
    "three_strip": (3, [(1, 12, 1, 1), (1, 12, 2, 1), (1, 12, 3, 1)]),
    "hero_top": (2, [(1, 12, 1, 1), (1, 6, 2, 1), (7, 6, 2, 1)]),
    "hero_left": (2, [(1, 6, 1, 2), (7, 6, 1, 1), (7, 6, 2, 1)]),
    "hero_five": (3, [(1, 12, 1, 1), (1, 6, 2, 1), (7, 6, 2, 1), (1, 6, 3, 1), (7, 6, 3, 1)]),
    "grid_2x2": (2, [(1, 6, 1, 1), (7, 6, 1, 1), (1, 6, 2, 1), (7, 6, 2, 1)]),
    "grid_2x3": (3, [(1, 6, 1, 1), (7, 6, 1, 1), (1, 6, 2, 1), (7, 6, 2, 1), (1, 6, 3, 1), (7, 6, 3, 1)]),
    "grid_3x2": (2, [(1, 4, 1, 1), (5, 4, 1, 1), (9, 4, 1, 1), (1, 4, 2, 1), (5, 4, 2, 1), (9, 4, 2, 1)]),
    "grid_3x3": (
        3,
        [
            (1, 4, 1, 1), (5, 4, 1, 1), (9, 4, 1, 1),
            (1, 4, 2, 1), (5, 4, 2, 1), (9, 4, 2, 1),
            (1, 4, 3, 1), (5, 4, 3, 1), (9, 4, 3, 1),
        ],
    ),
}

# panel count -> templates worth using, cycled by page index for variety
PREFERRED: dict[int, list[str]] = {
    1: ["splash"],
    2: ["two_vertical", "two_horizontal"],
    3: ["three_strip", "hero_top"],
    4: ["grid_2x2", "hero_top"],
    5: ["hero_five"],
    6: ["grid_2x3", "grid_3x2"],
    9: ["grid_3x3"],
}


def generic_cells(count: int, per_row: int = 2) -> tuple[list[tuple[int, int, int, int]], int]:
    """A balanced grid for any panel count.

    When the final row is short, its cells stretch to fill the width rather than
    leaving a gap - which is what a real page does.
    """
    rows = max(1, math.ceil(count / per_row))
    cells: list[tuple[int, int, int, int]] = []
    remaining = count
    for row in range(1, rows + 1):
        in_row = min(per_row, remaining)
        if in_row <= 0:
            break
        span = GRID_COLS // in_row
        for column in range(in_row):
            cells.append((1 + column * span, span, row, 1))
        remaining -= in_row
    return cells, rows


def choose_template(count: int, page_index: int = 0) -> tuple[str, list[tuple[int, int, int, int]], int]:
    """Pick a template for ``count`` panels. Returns (name, cells, rows)."""
    options = PREFERRED.get(count)
    if options:
        name = options[page_index % len(options)]
        rows, cells = TEMPLATES[name]
        return name, cells, rows

    per_row = 3 if count >= 7 else 2
    cells, rows = generic_cells(count, per_row=per_row)
    return "auto_grid", cells, rows


def plan_page(
    page_id: str,
    index: int,
    panel_ids: list[str],
    template: str | None = None,
    width: int = 1200,
    height: int = 1800,
) -> PageLayout:
    """Build one page while retaining the user's selected template name.

    If the selected template cannot fit the panel count, we keep the chosen
    template as the persisted value, record the fallback, and compute a balanced
    grid for the actual cell geometry so the layout still renders correctly.
    """
    count = len(panel_ids)
    if count == 0:
        raise ValueError("a page needs at least one panel")

    fallback = False
    note = ""
    selected = template if template in {"auto_grid", *TEMPLATES.keys()} else None
    cells: list[tuple[int, int, int, int]]
    rows: int

    if selected == "auto_grid":
        _, cells, rows = choose_template(count, index)
    elif selected:
        rows, cells = TEMPLATES[selected]
        if len(cells) != count:
            fallback = True
            note = "Selected template does not fit this panel count; using a balanced grid."
            _, fallback_cells, rows = choose_template(count, index)
            cells = fallback_cells
    else:
        selected, cells, rows = choose_template(count, index)

    return PageLayout(
        page_id=page_id,
        index=index,
        template=selected,  # type: ignore[arg-type]
        template_fallback=fallback,
        template_note=note,
        cols=GRID_COLS,
        rows=rows,
        cells=[
            PanelCell(
                panel_id=panel_id,
                col_start=cell[0],
                col_span=cell[1],
                row_start=cell[2],
                row_span=cell[3],
            )
            for panel_id, cell in zip(panel_ids, cells)
        ],
        panel_ids=list(panel_ids),
        width=width,
        height=height,
    )


def available_templates() -> list[dict]:
    return [
        {"id": name, "rows": rows, "cells": len(cells)}
        for name, (rows, cells) in TEMPLATES.items()
    ] + [{"id": "auto_grid", "rows": 0, "cells": 0}]
