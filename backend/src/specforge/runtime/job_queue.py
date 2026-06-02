from __future__ import annotations

from dataclasses import dataclass
from queue import Queue
from threading import Thread
from typing import Literal, Optional


@dataclass(frozen=True)
class PipelineJob:
    kind: Literal["start", "resume", "resume_stopped", "manual_skip"]
    iteration_id: str
    checkpoint: Optional[str] = None
    node: Optional[str] = None
    note: Optional[str] = None


class PipelineJobQueue:
    def __init__(self, pipeline) -> None:
        self.pipeline = pipeline
        self._queue: Queue[PipelineJob] = Queue()
        self._thread = Thread(target=self._run, name="specforge-pipeline-worker", daemon=True)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()

    def enqueue_start(self, iteration_id: str) -> None:
        self._queue.put(PipelineJob(kind="start", iteration_id=iteration_id))

    def enqueue_resume(self, iteration_id: str, checkpoint: str, note: Optional[str]) -> None:
        self._queue.put(PipelineJob(kind="resume", iteration_id=iteration_id, checkpoint=checkpoint, note=note))

    def enqueue_resume_stopped(self, iteration_id: str, note: Optional[str] = None) -> None:
        self._queue.put(PipelineJob(kind="resume_stopped", iteration_id=iteration_id, note=note))

    def enqueue_manual_skip(self, iteration_id: str, node: str, note: Optional[str] = None) -> None:
        self._queue.put(PipelineJob(kind="manual_skip", iteration_id=iteration_id, node=node, note=note))

    def join(self) -> None:
        self._queue.join()

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job.kind == "start":
                    self.pipeline.start(job.iteration_id)
                elif job.kind == "resume":
                    assert job.checkpoint is not None
                    self.pipeline.resume(job.iteration_id, job.checkpoint, job.note or "approved")
                elif job.kind == "resume_stopped":
                    self.pipeline.resume_stopped(job.iteration_id, job.note)
                elif job.kind == "manual_skip":
                    assert job.node is not None
                    self.pipeline.manual_skip(job.iteration_id, job.node, job.note)
            except Exception as exc:  # pragma: no cover - defensive guard for the worker
                try:
                    self.pipeline.fail_job(job.iteration_id, str(exc))
                except Exception:
                    pass
            finally:
                self._queue.task_done()
