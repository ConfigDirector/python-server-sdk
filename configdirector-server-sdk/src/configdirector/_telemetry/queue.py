from __future__ import annotations

import threading
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from ..types import Context
from .events import EvaluatedConfigEvent

__all__ = [
    "KIND_SAMPLE_LIMIT",
    "AggregatedEvent",
    "ContextRegistry",
    "EventQueue",
    "EventQueueSnapshot",
    "InvalidContextEntry",
    "InvalidContextRecording",
    "InvalidContextSubmissions",
    "aggregate",
]

KIND_SAMPLE_LIMIT = 20

InvalidContextRecording = Literal[
    "new-kind-sample",
    "known-kind-sample",
    "first-beyond-sample-limit",
    "beyond-sample-limit",
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
        self._contexts: dict[tuple[str, str], Context] = {}
        self._lock = threading.Lock()
        self._dropped_count = 0

    def add(self, context_kind: str, context_id: str, context: Context) -> None:
        with self._lock:
            # Re-assigning an existing key leaves it where it was, so a context that keeps being
            # seen is no safer from eviction than one seen once. That matches the other SDKs,
            # whose Maps behave the same way.
            self._contexts[(context_kind, context_id)] = context
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


@dataclass(frozen=True, slots=True)
class InvalidContextEntry:
    start_time: datetime
    end_time: datetime
    count: int
    kind_sample: str | None


class InvalidContextSubmissions:
    def __init__(self) -> None:
        self._counts_by_kind_sample: dict[str, int] = {}
        self._count_beyond_sample_limit = 0
        self._start_time: datetime | None = None
        self._lock = threading.Lock()

    def record(self, kind_sample: str) -> InvalidContextRecording:
        with self._lock:
            if self._start_time is None:
                self._start_time = _now()
            if kind_sample in self._counts_by_kind_sample:
                self._counts_by_kind_sample[kind_sample] += 1
                return "known-kind-sample"
            if len(self._counts_by_kind_sample) < KIND_SAMPLE_LIMIT:
                self._counts_by_kind_sample[kind_sample] = 1
                return "new-kind-sample"
            self._count_beyond_sample_limit += 1
            if self._count_beyond_sample_limit == 1:
                return "first-beyond-sample-limit"
            return "beyond-sample-limit"

    def take_snapshot(self) -> list[InvalidContextEntry]:
        with self._lock:
            end_time = _now()
            start_time = self._start_time or end_time
            entries = [
                InvalidContextEntry(
                    start_time=start_time, end_time=end_time, count=count, kind_sample=kind_sample
                )
                for kind_sample, count in self._counts_by_kind_sample.items()
            ]
            if self._count_beyond_sample_limit > 0:
                entries.append(
                    InvalidContextEntry(
                        start_time=start_time,
                        end_time=end_time,
                        count=self._count_beyond_sample_limit,
                        kind_sample=None,
                    )
                )
            self._reset()
            return entries

    def clear(self) -> None:
        with self._lock:
            self._reset()

    def _reset(self) -> None:
        self._counts_by_kind_sample.clear()
        self._count_beyond_sample_limit = 0
        self._start_time = None


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
