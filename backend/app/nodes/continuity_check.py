"""Node 11 - Continuity Check.

Scores every panel against its character references and, when a panel falls below
the threshold, hands it back to image generation. The retry budget lives here:
``regenerate_panel_ids`` is only populated while rounds remain, which is what
terminates the loop in the graph.
"""

from __future__ import annotations

from typing import Any

from ..continuity import get_checker
from ..schemas import ContinuityReport
from ..state import PipelineState
from .base import emit, pipeline_node, project_from, project_update
from .refs import panel_reference_paths


@pipeline_node("continuity_check", "Continuity Check")
def run(state: PipelineState) -> dict[str, Any]:
    project = project_from(state)
    checker = get_checker()
    threshold = (
        project.continuity_threshold
        if project.continuity_threshold is not None
        else checker.threshold
    )
    checker.threshold = threshold

    round_number = int(state.get("retry", 0))
    emit(
        f"Scoring {len(project.panels)} panel(s) against character references "
        f"(threshold {threshold:.2f}, {checker.embedder.name} embeddings)"
    )

    per_panel: dict[str, float] = {}
    failing: list[str] = []

    for panel in project.panels:
        if not panel.image_path:
            panel.continuity_score = 0.0
            panel.continuity_passed = False
            panel.continuity_detail = {"error": "panel was never rendered"}
            failing.append(panel.panel_id)
            continue

        references, _ = panel_reference_paths(panel.characters, project.characters)
        score = checker.score_panel(panel.panel_id, absolute_image(panel.image_path), references)

        panel.continuity_score = round(score.score, 4)
        panel.continuity_passed = score.passed
        panel.continuity_detail = score.as_dict()
        per_panel[panel.panel_id] = panel.continuity_score

        marker = "ok" if score.passed else "LOW"
        emit(
            f"  {panel.panel_id} [{marker}] {score.score:.3f} "
            f"(embedding {score.embedding_score:.3f}, colour {score.colour_score:.3f}"
            f"{', face detected' if score.face_found else ''})",
            level="info" if score.passed else "warning",
            data={"panel_id": panel.panel_id, "score": panel.continuity_score},
        )
        if not score.passed:
            failing.append(panel.panel_id)

    scores = list(per_panel.values())
    mean_score = round(sum(scores) / len(scores), 4) if scores else 0.0
    min_score = round(min(scores), 4) if scores else 0.0

    regenerate: list[str] = []
    if failing and round_number < checker.max_retries:
        for panel in project.panels:
            if panel.panel_id in failing:
                panel.regenerations += 1
        regenerate = list(failing)
        round_number += 1
        emit(
            f"{len(failing)} panel(s) below threshold - regenerating "
            f"(round {round_number}/{checker.max_retries})",
            level="warning",
            data={"panels": regenerate},
        )
    elif failing:
        emit(
            f"{len(failing)} panel(s) still below threshold after "
            f"{checker.max_retries} retries; keeping the best attempt",
            level="warning",
            data={"panels": failing},
        )
    else:
        emit(f"All panels passed continuity (mean {mean_score:.3f}, worst {min_score:.3f})")

    report = ContinuityReport(
        threshold=threshold,
        mean_score=mean_score,
        min_score=min_score,
        passed=not failing,
        rounds=round_number,
        per_panel=per_panel,
        regenerated=regenerate,
    )
    project.continuity = report

    return {
        "panels": [p.model_dump(mode="json") for p in project.panels],
        "continuity": report.model_dump(mode="json"),
        "regenerate_panel_ids": regenerate,
        "retry": round_number,
        **project_update(project),
    }


def absolute_image(rel_path: str) -> str:
    from ..storage import abs_path

    return str(abs_path(rel_path))
