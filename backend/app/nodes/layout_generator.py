"""Node 12 - Layout Generator.

Paginates the panels and assigns each page a grid template. The cell geometry
this produces is what the frontend renders (CSS grid) and what the export
compositor rasterises, so the editor preview and the PDF agree by construction.
"""

from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..layout_templates import choose_template, plan_page
from ..schemas import PageLayout, Panel
from ..state import PipelineState
from .base import emit, pipeline_node, project_from, project_update


def paginate(panels: list[Panel], per_page: int, template: str | None = None) -> list[PageLayout]:
    """Build the page list. Reused by the API when the user changes the layout."""
    if not panels:
        return []
    per_page = max(1, min(9, per_page))
    pages: list[PageLayout] = []
    for index, start in enumerate(range(0, len(panels), per_page), start=1):
        chunk = panels[start : start + per_page]
        pages.append(
            plan_page(
                page_id=f"page{index:02d}",
                index=index,
                panel_ids=[panel.panel_id for panel in chunk],
                template=template,
            )
        )
    return pages


@pipeline_node("layout_generator", "Layout Generator")
def run(state: PipelineState) -> dict[str, Any]:
    project = project_from(state)
    settings = get_settings()
    per_page = project.panels_per_page or settings.panels_per_page
    template = (state.get("edit_request") or {}).get("template")

    if not project.panels:
        raise ValueError("no panels to lay out")

    pages = paginate(project.panels, per_page, template)
    project.pages = pages

    emit(
        f"{len(pages)} page(s) at {per_page} panel(s) per page "
        f"({', '.join(page.template for page in pages)})",
        data={"templates": [page.template for page in pages], "pages": len(pages)},
    )
    for page in pages:
        emit(f"  {page.page_id} [{page.template}] {page.cols}x{page.rows} grid, {len(page.cells)} panel(s)")

    total_cells = sum(len(page.cells) for page in pages)
    if total_cells != len(project.panels):
        emit(
            f"layout covers {total_cells} of {len(project.panels)} panels",
            level="warning",
        )

    return {
        "pages": [page.model_dump(mode="json") for page in pages],
        **project_update(project),
    }


__all__ = ["paginate", "run", "choose_template"]
