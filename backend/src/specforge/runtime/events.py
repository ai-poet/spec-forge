from __future__ import annotations

from dataclasses import dataclass
from queue import Queue
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class EventEnvelope:
    type: str
    snapshot: dict[str, Any] | None = None
    event: dict[str, Any] | None = None


class EventBroker:
    def __init__(self) -> None:
        self._lock = Lock()
        self._subscribers: dict[str, set[Queue[EventEnvelope]]] = {}

    def subscribe(self, iteration_id: str) -> Queue[EventEnvelope]:
        queue: Queue[EventEnvelope] = Queue()
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
            queue.put(envelope)
