from __future__ import annotations

from dataclasses import dataclass
from queue import Queue
from threading import Lock, Thread
import time
from typing import Literal, Optional

from ..core.config import settings


@dataclass(frozen=True)
class PipelineJob:
    kind: Literal["start", "resume", "resume_stopped", "manual_skip", "log_summary"]
    iteration_id: str
    checkpoint: Optional[str] = None
    node: Optional[str] = None
    note: Optional[str] = None
    enqueued_at: float = 0.0

    @property
    def dedupe_key(self) -> tuple[str, str, str]:
        if self.kind == "resume":
            return (self.iteration_id, self.kind, self.checkpoint or "")
        if self.kind == "manual_skip":
            return (self.iteration_id, self.kind, self.node or "")
        return (self.iteration_id, self.kind, "")


class PipelineJobQueue:
    def __init__(self, pipeline) -> None:
        self.pipeline = pipeline
        self._queue: Queue[PipelineJob] = Queue(maxsize=settings.job_queue_max_size)
        self._thread = Thread(target=self._run, name="specforge-pipeline-worker", daemon=True)
        self._started = False
        self._lock = Lock()
        self._pending_keys: set[tuple[str, str, str]] = set()

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()

    def enqueue_start(self, iteration_id: str) -> bool:
        return self._enqueue(PipelineJob(kind="start", iteration_id=iteration_id, enqueued_at=time.monotonic()))

    def enqueue_resume(self, iteration_id: str, checkpoint: str, note: Optional[str]) -> bool:
        return self._enqueue(PipelineJob(kind="resume", iteration_id=iteration_id, checkpoint=checkpoint, note=note, enqueued_at=time.monotonic()))

    def enqueue_resume_stopped(self, iteration_id: str, note: Optional[str] = None) -> bool:
        return self._enqueue(PipelineJob(kind="resume_stopped", iteration_id=iteration_id, note=note, enqueued_at=time.monotonic()))

    def enqueue_manual_skip(self, iteration_id: str, node: str, note: Optional[str] = None) -> bool:
        return self._enqueue(PipelineJob(kind="manual_skip", iteration_id=iteration_id, node=node, note=note, enqueued_at=time.monotonic()))

    def enqueue_log_summary(self, iteration_id: str) -> bool:
        return self._enqueue(PipelineJob(kind="log_summary", iteration_id=iteration_id, enqueued_at=time.monotonic()))

    def join(self) -> None:
        self._queue.join()

    def _enqueue(self, job: PipelineJob) -> bool:
        key = job.dedupe_key
        duplicate = False
        with self._lock:
            if key in self._pending_keys:
                duplicate = True
            else:
                self._pending_keys.add(key)
        if duplicate:
            self._record_duplicate(job)
            return False
        try:
            self._queue.put(job)
        except Exception:
            with self._lock:
                self._pending_keys.discard(key)
            raise
        return True

    def _record_duplicate(self, job: PipelineJob) -> None:
        try:
            self.pipeline._add_event(
                job.iteration_id,
                event_type="job.duplicate_ignored",
                payload={"kind": job.kind, "checkpoint": job.checkpoint, "node": job.node},
            )
        except Exception:
            pass

    def _record_stale(self, job: PipelineJob, reason: str) -> None:
        try:
            self.pipeline._add_event(
                job.iteration_id,
                event_type="job.stale_ignored",
                payload={"kind": job.kind, "checkpoint": job.checkpoint, "node": job.node, "reason": reason},
            )
        except Exception:
            pass

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job.enqueued_at:
                    self.pipeline._add_event(
                        job.iteration_id,
                        event_type="job.started",
                        payload={"kind": job.kind, "queue_wait_ms": int((time.monotonic() - job.enqueued_at) * 1000)},
                    )
                if job.kind == "start":
                    if not self.pipeline.can_start_job(job.iteration_id):
                        self._record_stale(job, "iteration is no longer queued")
                    else:
                        self.pipeline.start(job.iteration_id)
                elif job.kind == "resume":
                    assert job.checkpoint is not None
                    if not self.pipeline.can_resume(job.iteration_id, job.checkpoint):
                        self._record_stale(job, f"iteration is not awaiting {job.checkpoint}")
                    else:
                        try:
                            self.pipeline.resume(job.iteration_id, job.checkpoint, job.note or "approved")
                        except ValueError as exc:
                            if "not awaiting" in str(exc):
                                self._record_stale(job, str(exc))
                            else:
                                raise
                elif job.kind == "resume_stopped":
                    if not self.pipeline.can_resume_stopped(job.iteration_id):
                        self._record_stale(job, "iteration is not resumable")
                    else:
                        self.pipeline.resume_stopped(job.iteration_id, job.note)
                elif job.kind == "manual_skip":
                    assert job.node is not None
                    try:
                        self.pipeline.manual_skip(job.iteration_id, job.node, job.note)
                    except ValueError as exc:
                        self._record_stale(job, str(exc))
                elif job.kind == "log_summary":
                    self.pipeline.generate_log_summary(job.iteration_id)
            except Exception as exc:  # pragma: no cover - defensive guard for the worker
                try:
                    if job.kind == "log_summary":
                        self.pipeline.mark_log_summary_failed(job.iteration_id, str(exc))
                    else:
                        self.pipeline.fail_job(job.iteration_id, str(exc))
                except Exception:
                    pass
            finally:
                with self._lock:
                    self._pending_keys.discard(job.dedupe_key)
                self._queue.task_done()
