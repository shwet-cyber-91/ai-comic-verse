"""Shared plumbing for pipeline nodes.

``@pipeline_node`` wraps a node function so every node gets, for free:
  * live progress events into the job registry (which is what the SSE screen reads)
  * an append-only log entry in the graph state
  * per-node timing
  * a persisting snapshot of the project after each step, so the editor can be
    opened mid-run and the API always reflects what has been produced so far
  * a ``NodeError`` with the node name attached when something goes wrong

Nodes call ``emit("...")`` from inside to report progress without having to
thread a context object through their signatures. Events are collected in
thread-local storage: the graph runs sequentially in one worker thread, so this
is safe and keeps node signatures as ``run(state) -> dict``.
"""

from __future__ import annotations

import functools
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from ..db import save_project
from ..jobs import registry
from ..logging_config import get_logger
from ..schemas import ComicProject
from ..state import PipelineState

log = get_logger("nodes")

_local = threading.local()


class NodeError(RuntimeError):
    """A pipeline node failed. Carries the node name for the UI."""

    def __init__(self, node: str, message: str) -> None:
        super().__init__(f"[{node}] {message}")
        self.node = node
        self.message = message


@dataclass
class NodeSpec:
    name: str
    label: str
    description: str
    run: Callable[[PipelineState], dict[str, Any]]


# --------------------------------------------------------------------------- #
# Progress reporting
# --------------------------------------------------------------------------- #


def emit(message: str, level: str = "info", data: dict[str, Any] | None = None) -> None:
    """Report progress from inside a node."""
    node = getattr(_local, "node", None)
    job_id = getattr(_local, "job_id", "")
    if job_id:
        registry.emit(job_id, message, node=node, level=level, data=data or {})
    events = getattr(_local, "events", None)
    if events is not None:
        events.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "node": node,
                "level": level,
                "message": message,
                "data": data or {},
            }
        )
    log.debug("[%s] %s", node or "-", message)


# --------------------------------------------------------------------------- #
# Decorator
# --------------------------------------------------------------------------- #


def pipeline_node(name: str, label: str):
    def decorator(fn: Callable[[PipelineState], dict[str, Any]]):
        @functools.wraps(fn)
        def wrapper(state: PipelineState) -> dict[str, Any]:
            job_id = state.get("job_id", "")
            _local.node = name
            _local.job_id = job_id
            _local.events = []

            if job_id:
                registry.set_current_node(job_id, name)

            started = time.perf_counter()
            log.info("--> %s", name)

            try:
                update = fn(state) or {}
            except NodeError:
                raise
            except Exception as exc:
                log.exception("node %s failed", name)
                if job_id:
                    registry.emit(job_id, f"{label} failed: {exc}", node=name, level="error")
                raise NodeError(name, str(exc)) from exc

            elapsed = time.perf_counter() - started
            collected = list(getattr(_local, "events", []))
            update.setdefault("events", [])
            update["events"] = collected + update["events"]

            merged = merge_state(state, update)
            _persist(merged)

            if job_id:
                registry.complete_node(job_id, name)
                registry.emit(
                    job_id,
                    f"{label} complete ({elapsed:.2f}s)",
                    node=name,
                    level="success",
                    data={"elapsed": round(elapsed, 3)},
                )

            log.info("<-- %s (%.2fs)", name, elapsed)
            _local.node = None
            _local.events = []
            return update

        wrapper.__node_name__ = name  # type: ignore[attr-defined]
        return wrapper

    return decorator


def merge_state(state: PipelineState, update: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge that appends rather than replaces the event log."""
    merged: dict[str, Any] = dict(state)
    for key, value in update.items():
        if key == "events":
            merged["events"] = list(state.get("events", [])) + list(value)
        else:
            merged[key] = value
    return merged


def _persist(state: dict[str, Any]) -> None:
    """Snapshot the project to the database. Best-effort: never fails a node."""
    payload = state.get("project")
    if not payload:
        return
    try:
        save_project(ComicProject.model_validate(payload))
    except Exception as exc:  # pragma: no cover - persistence must not break generation
        log.warning("could not persist project snapshot: %s", exc)


# --------------------------------------------------------------------------- #
# Helpers used by the nodes
# --------------------------------------------------------------------------- #


def project_from(state: PipelineState) -> ComicProject:
    payload = state.get("project")
    if not payload:
        raise NodeError("(state)", "no project in state - story_input must run first")
    return ComicProject.model_validate(payload)


def project_update(project: ComicProject) -> dict[str, Any]:
    """Return the state fragment that writes a project back."""
    project.updated_at = datetime.now(timezone.utc)
    return {"project": project.model_dump(mode="json")}


def request_from(state: PipelineState):
    from ..schemas import StoryRequest

    return StoryRequest.model_validate(state["request"])
