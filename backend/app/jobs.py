"""In-process job registry + event bus.

The pipeline runs in a worker thread (PIL and httpx are synchronous), while the
SSE endpoint runs in the event loop. Bridging the two with an asyncio queue
across threads is fiddly, so instead the registry keeps an append-only event
list guarded by a lock and the SSE endpoint polls it with a cursor. At one
generation per user this costs nothing and has no race conditions.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from .logging_config import get_logger
from .schemas import JobEvent, JobSnapshot

log = get_logger("jobs")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Job:
    job_id: str
    project_id: Optional[str] = None
    status: str = "queued"
    current_node: Optional[str] = None
    completed_nodes: list[str] = field(default_factory=list)
    total_nodes: int = 0
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    events: list[JobEvent] = field(default_factory=list)
    # monotonic so the SSE cursor stays correct even after the log is trimmed
    seq_counter: int = 0

    @property
    def progress(self) -> float:
        if self.status == "succeeded":
            return 1.0
        if self.total_nodes <= 0:
            return 0.0
        return round(min(0.99, len(self.completed_nodes) / self.total_nodes), 4)

    def snapshot(self, since_seq: int = 0) -> JobSnapshot:
        return JobSnapshot(
            job_id=self.job_id,
            project_id=self.project_id,
            status=self.status,  # type: ignore[arg-type]
            current_node=self.current_node,
            completed_nodes=list(self.completed_nodes),
            total_nodes=self.total_nodes,
            progress=self.progress,
            error=self.error,
            started_at=self.started_at,
            finished_at=self.finished_at,
            events=[e for e in self.events if e.seq > since_seq],
        )


class JobRegistry:
    """Thread-safe store of running and finished jobs."""

    def __init__(self, max_jobs: int = 50) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._max_jobs = max_jobs

    # -- lifecycle ---------------------------------------------------------
    def create(self, project_id: Optional[str], total_nodes: int) -> Job:
        job = Job(
            job_id=uuid.uuid4().hex,
            project_id=project_id,
            status="queued",
            total_nodes=total_nodes,
            started_at=_now(),
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            self._evict_locked()
        log.info("job %s created for project %s (%d nodes)", job.job_id[:8], project_id, total_nodes)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def latest_for_project(self, project_id: str) -> Optional[Job]:
        with self._lock:
            for job_id in reversed(self._order):
                job = self._jobs.get(job_id)
                if job and job.project_id == project_id:
                    return job
            return None

    def _evict_locked(self) -> None:
        while len(self._order) > self._max_jobs:
            oldest = self._order.pop(0)
            self._jobs.pop(oldest, None)

    # -- state transitions -------------------------------------------------
    def start(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = "running"
                job.started_at = job.started_at or _now()

    def set_current_node(self, job_id: str, node: str, total_nodes: int | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.current_node = node
                job.status = "running"
                if total_nodes:
                    job.total_nodes = total_nodes

    def complete_node(self, job_id: str, node: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and node not in job.completed_nodes:
                job.completed_nodes.append(node)

    def succeed(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = "succeeded"
                job.current_node = None
                job.finished_at = _now()

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.status = "failed"
                job.error = error
                job.finished_at = _now()

    # -- events ------------------------------------------------------------
    def emit(
        self,
        job_id: str,
        message: str,
        *,
        node: str | None = None,
        level: str = "info",
        data: dict[str, Any] | None = None,
    ) -> JobEvent:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.seq_counter += 1
            seq = job.seq_counter if job else 0
            event = JobEvent(
                seq=seq,
                node=node,
                level=level,  # type: ignore[arg-type]
                message=message,
                progress=job.progress if job else 0.0,
                data=data or {},
            )
            if job:
                # keep the log bounded; the SSE cursor still advances monotonically
                if len(job.events) >= 500:
                    job.events = job.events[-250:]
                job.events.append(event)
        log.debug("[%s] %s", node or "-", message)
        return event

    def snapshot(self, job_id: str, since_seq: int = 0) -> Optional[JobSnapshot]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.snapshot(since_seq) if job else None

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()
            self._order.clear()


registry = JobRegistry()
