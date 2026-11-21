"""The LangGraph pipeline.

    story_input -> story_understanding -> scene_planning -> character_memory
      -> emotion_detection -> dialogue_generation -> camera_director
      -> visual_prompt_generation -> style_selection -> image_generation
      -> continuity_check --(low score)--> image_generation
                           --(pass)------> layout_generator -> editor -> export -> END

Two entry points are exported:

``run_pipeline``        full generation, used by ``POST /projects/{id}/generate``
``regenerate_panels``   re-render specific panels then re-check continuity, used
                        by the editor's "regenerate this panel" button
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .db import save_project, session_scope
from .jobs import registry
from .logging_config import get_logger
from .nodes import NODE_REGISTRY
from .nodes import camera_director as camera_node
from .nodes import continuity_check as continuity_node
from .nodes import dialogue_generation as dialogue_node
from .nodes import editor as editor_node
from .nodes import emotion_detection as emotion_node
from .nodes import image_generation as image_node
from .nodes import layout_generator as layout_node
from .nodes import style_selection as style_node
from .nodes import visual_prompt as visual_prompt_node
from .nodes.base import NodeError
from .pipeline_meta import TOTAL_NODES
from .schemas import ComicProject
from .state import PipelineState, initial_state

log = get_logger("graph")

FIRST_NODE = NODE_REGISTRY[0].name
EMOTION = "emotion_detection"
CONTINUITY = "continuity_check"
IMAGE_GENERATION = "image_generation"
LAYOUT = "layout_generator"
EDITOR = "editor"
EXPORT = "export"


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #


def route_after_continuity(state: PipelineState) -> str:
    """Send rejected panels back to image generation, otherwise lay the comic out."""
    if state.get("regenerate_panel_ids"):
        return "retry"
    return "continue"


# --------------------------------------------------------------------------- #
# Graphs
# --------------------------------------------------------------------------- #


def build_graph():
    """The full 14-node pipeline."""
    graph = StateGraph(PipelineState)

    for spec in NODE_REGISTRY:
        graph.add_node(spec.name, spec.run)

    graph.add_edge(START, FIRST_NODE)

    # every node runs straight into the next one, except the two edges the
    # continuity retry loop owns
    for previous, current in zip(NODE_REGISTRY, NODE_REGISTRY[1:]):
        if previous.name == CONTINUITY:
            continue
        if previous.name == IMAGE_GENERATION:
            continue
        graph.add_edge(previous.name, current.name)

    graph.add_conditional_edges(
        CONTINUITY,
        route_after_continuity,
        {"retry": IMAGE_GENERATION, "continue": LAYOUT},
    )
    graph.add_edge(IMAGE_GENERATION, CONTINUITY)
    graph.add_edge(EXPORT, END)

    return graph.compile()


def build_repair_graph():
    """Rebuild the panel prompt and image from the current project state, then
    re-score continuity and finalise the layout."""
    graph = StateGraph(PipelineState)

    graph.add_node(EMOTION, emotion_node.run)
    graph.add_node("dialogue_generation", dialogue_node.run)
    graph.add_node("camera_director", camera_node.run)
    graph.add_node("visual_prompt_generation", visual_prompt_node.run)
    graph.add_node("style_selection", style_node.run)
    graph.add_node(IMAGE_GENERATION, image_node.run)
    graph.add_node(CONTINUITY, continuity_node.run)
    graph.add_node(LAYOUT, layout_node.run)
    graph.add_node(EDITOR, editor_node.run)

    graph.add_edge(START, EMOTION)
    graph.add_edge(EMOTION, "dialogue_generation")
    graph.add_edge("dialogue_generation", "camera_director")
    graph.add_edge("camera_director", "visual_prompt_generation")
    graph.add_edge("visual_prompt_generation", "style_selection")
    graph.add_edge("style_selection", IMAGE_GENERATION)
    graph.add_edge(IMAGE_GENERATION, CONTINUITY)
    graph.add_conditional_edges(
        CONTINUITY,
        route_after_continuity,
        {"retry": IMAGE_GENERATION, "continue": LAYOUT},
    )
    graph.add_edge(LAYOUT, EDITOR)
    graph.add_edge(EDITOR, END)

    return graph.compile()


_graph = None
_repair_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def get_repair_graph():
    global _repair_graph
    if _repair_graph is None:
        _repair_graph = build_repair_graph()
    return _repair_graph


def reset_graphs() -> None:
    """Drop the compiled graphs. Tests call this after changing settings."""
    global _graph, _repair_graph
    _graph = None
    _repair_graph = None


# --------------------------------------------------------------------------- #
# Entry points
# --------------------------------------------------------------------------- #


def _execute(job_id: str, state: PipelineState, graph, label: str) -> ComicProject:
    """Invoke a compiled graph, recording success or failure on the job."""
    if job_id:
        registry.start(job_id)
    log.info("%s started (job %s)", label, job_id[:8] or "-")

    try:
        result = graph.invoke(state, {"recursion_limit": 2 * TOTAL_NODES + 10})
    except NodeError as exc:
        _failed(job_id, state.get("project_id", ""), f"{exc.node}: {exc.message}")
        raise
    except Exception as exc:
        log.exception("%s failed", label)
        _failed(job_id, state.get("project_id", ""), str(exc))
        raise

    project = ComicProject.model_validate(result["project"])
    save_project(project)
    if job_id:
        registry.succeed(job_id)
    log.info(
        "%s finished: %d panel(s), %d page(s)",
        label,
        len(project.panels),
        len(project.pages),
    )
    return project


def _failed(job_id: str, project_id: str, message: str) -> None:
    if job_id:
        registry.fail(job_id, message)
    if project_id:
        _mark_project_failed(project_id, message)


def _mark_project_failed(project_id: str, message: str) -> None:
    try:
        from .db import ProjectRow, load_project

        # write it into the payload, which is what the editor reads back
        project = load_project(project_id)
        if project is not None:
            project.status = "failed"
            project.error = message
            save_project(project)
            return

        with session_scope() as session:
            row = session.get(ProjectRow, project_id)
            if row is not None:
                row.status = "failed"
    except Exception as exc:  # pragma: no cover - bookkeeping only
        log.warning("could not record failure for %s: %s", project_id, exc)


def run_pipeline(project_id: str, request: dict[str, Any], job_id: str = "") -> ComicProject:
    """Run the whole pipeline. Blocking - call it from a worker thread."""
    if job_id:
        registry.set_current_node(job_id, FIRST_NODE, len(NODE_REGISTRY))
    state = initial_state(project_id, request, job_id=job_id)
    return _execute(job_id, state, get_graph(), "generation")


def regenerate_panels(
    project_id: str,
    request: dict[str, Any],
    panel_ids: list[str],
    job_id: str = "",
    edit_request: dict[str, Any] | None = None,
) -> ComicProject:
    """Re-render the named panels, re-score continuity, re-paginate and finalise.

    Used by the editor. The project is loaded from the database so a regeneration
    after a restart behaves the same as one straight after generation.
    """
    project = _load_project(project_id)
    known = {panel.panel_id for panel in project.panels}
    unknown = [panel_id for panel_id in panel_ids if panel_id not in known]
    if unknown:
        raise ValueError(f"unknown panel(s): {', '.join(unknown)}")

    if job_id:
        registry.set_current_node(job_id, IMAGE_GENERATION, TOTAL_NODES)

    state = initial_state(project_id, request, job_id=job_id, edit_request=edit_request)
    state["retry"] = 0
    state["regenerate_panel_ids"] = list(panel_ids)
    state["project"] = project.model_dump(mode="json")
    state["panels"] = [p.model_dump(mode="json") for p in project.panels]
    state["pages"] = [p.model_dump(mode="json") for p in project.pages]

    return _execute(job_id, state, get_repair_graph(), "panel regeneration")


def _load_project(project_id: str) -> ComicProject:
    from .db import load_project

    project = load_project(project_id)
    if project is None:
        raise ValueError(f"project '{project_id}' does not exist")
    return project


__all__ = [
    "CONTINUITY",
    "EXPORT",
    "FIRST_NODE",
    "IMAGE_GENERATION",
    "build_graph",
    "build_repair_graph",
    "get_graph",
    "get_repair_graph",
    "regenerate_panels",
    "reset_graphs",
    "route_after_continuity",
    "run_pipeline",
]
