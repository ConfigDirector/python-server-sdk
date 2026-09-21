from __future__ import annotations

import threading
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone

from ..types import Context
from .events import EvaluatedConfigEvent

__all__ = [
    "AggregatedEvent",
    "ContextRegistry",
    "EventQueue",
    "EventQueueSnapshot",
    "aggregate",
]


@dataclass(frozen=True, slots=True)
class EventQueueSnapshot:
    start_time: datetime
    end_time: datetime
    events: list[EvaluatedConfigEvent]
    dropped_count: int

    @property
    def is_empty(self) -> bool:
        return not self.events and self.dropped_count == 0


@dataclass(frozen=True, slots=True)
class AggregatedEvent:
    start_time: datetime
    end_time: datetime
    count: int
    event: EvaluatedConfigEvent


class EventQueue:
    def __init__(self, limit: int) -> None:
        self._events: deque[EvaluatedConfigEvent] = deque(maxlen=limit)
        self._lock = threading.Lock()
        self._start_time: datetime | None = None
        self._dropped_count = 0

    def push(self, event: EvaluatedConfigEvent) -> None:
        with self._lock:
            if self._start_time is None:
                self._start_time = _now()
            # A bounded deque discards from the left on its own once it is full, so all that is
            # left to do is count what it discarded.
            if len(self._events) == self._events.maxlen:
                self._dropped_count += 1
            self._events.append(event)

    # Empties the queue, leaving it ready to collect the next batch.
    def take_snapshot(self) -> EventQueueSnapshot:
        with self._lock:
            end_time = _now()
            snapshot = EventQueueSnapshot(
                start_time=self._start_time or end_time,
                end_time=end_time,
                events=list(self._events),
                dropped_count=self._dropped_count,
            )
            self._reset()
            return snapshot

    def clear(self) -> None:
        with self._lock:
            self._reset()

    def _reset(self) -> None:
        self._events.clear()
        self._start_time = None
        self._dropped_count = 0


class ContextRegistry:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._contexts: dict[str, Context] = {}
        self._lock = threading.Lock()
        self._dropped_count = 0

    def add(self, context_id: str, context: Context) -> None:
        with self._lock:
            # Re-assigning an existing key leaves it where it was, so a context that keeps being
            # seen is no safer from eviction than one seen once. That matches the other SDKs,
            # whose Maps behave the same way.
            self._contexts[context_id] = context
            while len(self._contexts) > self._limit:
                del self._contexts[next(iter(self._contexts))]
                self._dropped_count += 1

    # Returns the contexts collected so far and how many were dropped, then starts over.
    def take_snapshot(self) -> tuple[list[Context], int]:
        with self._lock:
            snapshot = (list(self._contexts.values()), self._dropped_count)
            self._reset()
            return snapshot

    def clear(self) -> None:
        with self._lock:
            self._reset()

    def _reset(self) -> None:
        self._contexts.clear()
        self._dropped_count = 0


def aggregate(
    events: list[EvaluatedConfigEvent], start_time: datetime, end_time: datetime
) -> list[AggregatedEvent]:
    # Counter preserves first-seen order, so the report keeps the order events were recorded in.
    counts = Counter(events)

    return [
        AggregatedEvent(start_time=start_time, end_time=end_time, count=count, event=event)
        for event, count in counts.items()
    ]


def _now() -> datetime:
    return datetime.now(timezone.utc)
