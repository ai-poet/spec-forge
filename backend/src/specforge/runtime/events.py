from __future__ import annotations

from dataclasses import dataclass
from queue import Queue
from threading import Lock
from typing import Any

from ..core.config import settings


@dataclass(frozen=True)
class EventEnvelope:
    type: str
    snapshot: dict[str, Any] | None = None
    event: dict[str, Any] | None = None


class EventBroker:
    def __init__(self, *, max_queue_size: int | None = None) -> None:
        self._lock = Lock()
        self._subscribers: dict[str, set[Queue[EventEnvelope]]] = {}
        self._max_queue_size = max_queue_size or settings.event_queue_max_size

    def subscribe(self, iteration_id: str) -> Queue[EventEnvelope]:
        queue: Queue[EventEnvelope] = Queue(maxsize=self._max_queue_size)
        with self._lock:
            self._subscribers.setdefault(iteration_id, set()).add(queue)
        return queue

    def unsubscribe(self, iteration_id: str, queue: Queue[EventEnvelope]) -> None:
        with self._lock:
            subscribers = self._subscribers.get(iteration_id)
            if not subscribers:
                return
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(iteration_id, None)

    def publish(self, iteration_id: str, envelope: EventEnvelope) -> None:
        with self._lock:
            subscribers = list(self._subscribers.get(iteration_id, set()))
        for queue in subscribers:
            self._put_bounded(queue, envelope)

    def _put_bounded(self, queue: Queue[EventEnvelope], envelope: EventEnvelope) -> None:
        with queue.mutex:
            if envelope.type == "snapshot":
                before = len(queue.queue)
                queue.queue = type(queue.queue)(item for item in queue.queue if item.type != "snapshot")
                removed = before - len(queue.queue)
                if removed and queue.unfinished_tasks > 0:
                    queue.unfinished_tasks = max(0, queue.unfinished_tasks - removed)
            while queue.maxsize > 0 and len(queue.queue) >= queue.maxsize:
                queue.queue.popleft()
                if queue.unfinished_tasks > 0:
                    queue.unfinished_tasks -= 1
            queue.queue.append(envelope)
            queue.unfinished_tasks += 1
            queue.not_empty.notify()
