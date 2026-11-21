"""The LangGraph state.

Kept as plain JSON-able dicts rather than live Pydantic objects: LangGraph merges
partial updates and (optionally) checkpoints state, and both are simpler and
safer when the payload is primitives. Each node validates into Pydantic models
at its boundary, works on the typed objects, and dumps back.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class PipelineState(TypedDict, total=False):
    # run plumbing
    job_id: str
    project_id: str
    retry: int
    error: str | None

    # inputs
    request: dict[str, Any]  # StoryRequest dump
    edit_request: dict[str, Any] | None  # optional PanelUpdateRequest applied by the editor node

    # the running project (ComicProject dump) - the single source of truth nodes mutate
    project: dict[str, Any]

    # intermediate products
    plan: dict[str, Any]
    style: dict[str, Any]
    story_analysis: dict[str, Any]
    scenes: list[dict[str, Any]]
    characters: list[dict[str, Any]]
    panels: list[dict[str, Any]]
    pages: list[dict[str, Any]]
    continuity: dict[str, Any]
    exports: dict[str, str]

    # continuity retry loop
    regenerate_panel_ids: list[str]

    # append-only log; the reducer means every node's events accumulate
    events: Annotated[list[dict[str, Any]], operator.add]


def initial_state(
    project_id: str,
    request: dict[str, Any],
    job_id: str = "",
    edit_request: dict[str, Any] | None = None,
) -> PipelineState:
    return PipelineState(
        job_id=job_id,
        project_id=project_id,
        request=request,
        edit_request=edit_request,
        retry=0,
        regenerate_panel_ids=[],
        events=[],
        error=None,
    )
