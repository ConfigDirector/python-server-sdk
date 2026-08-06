"""Collecting config evaluations and reporting them on an interval."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from ..types import ConfigDirectorLogger, ConfigType, ConfigValue, Context, EvaluationReason
from .events import EvaluatedConfigEvent
from .queue import ContextRegistry, EventQueue, aggregate
from .reporter import EventReport, EventReporter, HttpEventReporter

__all__ = [
    "DEFAULT_EVENT_QUEUE_LIMIT",
    "DEFAULT_FLUSH_INTERVAL",
    "MAX_EVENT_QUEUE_LIMIT",
    "MIN_EVENT_QUEUE_LIMIT",
    "TelemetryCollector",
    "TelemetryCollectorOptions",
]

DEFAULT_EVENT_QUEUE_LIMIT = 5_000
DEFAULT_FLUSH_INTERVAL = 30.0

MIN_EVENT_QUEUE_LIMIT = 100
MAX_EVENT_QUEUE_LIMIT = 100_000

# The first flush comes early so that a process that runs briefly still reports what it evaluated.
INITIAL_FLUSH_DELAY = 5.0

# How long close() waits for a report already in flight to return.
_JOIN_TIMEOUT = 5.0

# The queue limit is split between the two things a report carries. Evaluations outnumber the
# distinct contexts they were evaluated against by a wide margin, so they get the larger share.
_EVALUATION_SHARE = 7


@dataclass(frozen=True, slots=True)
class TelemetryCollectorOptions:
    server_sdk_key: str
    base_url: str
    logger: ConfigDirectorLogger
    event_queue_limit: int = DEFAULT_EVENT_QUEUE_LIMIT
    flush_interval: float = DEFAULT_FLUSH_INTERVAL
    initial_flush_delay: float = INITIAL_FLUSH_DELAY
    # Supplied by tests; in production the collector builds its own HTTP reporter.
    reporter: EventReporter | None = field(default=None, compare=False)


class TelemetryCollector:
    def __init__(self, options: TelemetryCollectorOptions) -> None:
        self._logger = options.logger
        self._flush_interval = options.flush_interval
        self._initial_flush_delay = options.initial_flush_delay
        self._reporter = options.reporter or HttpEventReporter(
            server_sdk_key=options.server_sdk_key,
            base_url=options.base_url,
            logger=options.logger,
        )

        limit = options.event_queue_limit
        evaluation_limit = limit * _EVALUATION_SHARE // 10
        self._events = EventQueue(evaluation_limit)
        self._contexts = ContextRegistry(limit - evaluation_limit)

        self._lock = threading.Lock()
        # Held for the whole of a flush, so that a report triggered by close() cannot overtake
        # one the interval already started.
        self._flush_lock = threading.Lock()
        self._collecting = True
        self._closed = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="configdirector-telemetry", daemon=True)
        self._thread.start()

    # On the client's hot path, so this returns without doing any appreciable work.
    def record_evaluation(
        self,
        *,
        key: str,
        default: ConfigValue,
        value: ConfigValue,
        used_default: bool,
        reason: EvaluationReason,
        context: Context | None = None,
        config_type: ConfigType | None = None,
        value_id: str | None = None,
    ) -> None:
        if not self._is_collecting():
            return

        # An anonymous context still targets rules, but it is not persisted and must not be
        # identifiable in what is reported.
        context_id: str | None = None
        if context is not None and context.id and not context.anonymous:
            context_id = context.id
            self._contexts.add(context_id, context)

        self._events.push(
            EvaluatedConfigEvent.of(
                key=key,
                default=default,
                value=value,
                used_default=used_default,
                reason=reason,
                context_id=context_id,
                config_type=config_type,
                value_id=value_id,
            )
        )

    # Reports everything collected so far without waiting for the next interval, blocking until
    # the request completes. Nothing is sent when there is nothing to report.
    def flush(self) -> None:
        with self._flush_lock:
            snapshot = self._events.take_snapshot()
            contexts, dropped_contexts = self._contexts.take_snapshot()
            report = EventReport(
                evaluations=aggregate(
                    [event.compacted() for event in snapshot.events],
                    snapshot.start_time,
                    snapshot.end_time,
                ),
                dropped_evaluations=snapshot.dropped_count,
                contexts=contexts,
                dropped_contexts=dropped_contexts,
            )
            if report.is_empty:
                return

            try:
                response = self._reporter.report(report)
            except Exception as error:  # a failed report must not take down the flush thread
                self._logger.warning("[TelemetryCollector] Error reporting telemetry data: %r", error)
                return

        if response.fatal:
            self._stop_collecting()

    # Reports whatever is left and stops collecting. Safe to call more than once.
    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            was_collecting, self._collecting = self._collecting, False

        self._stop.set()
        # Joining from the flush thread itself would deadlock.
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=_JOIN_TIMEOUT)

        # Nothing left to say to a server that already rejected us.
        if was_collecting:
            self.flush()
        self._events.clear()
        self._contexts.clear()

    def _run(self) -> None:
        delay = self._initial_flush_delay
        while not self._stop.wait(delay):
            self.flush()
            if not self._is_collecting():
                return
            delay = self._flush_interval

    def _is_collecting(self) -> bool:
        with self._lock:
            return self._collecting

    def _stop_collecting(self) -> None:
        with self._lock:
            if not self._collecting:
                return
            self._collecting = False

        self._stop.set()
        self._events.clear()
        self._contexts.clear()
        self._logger.warning(
            "[TelemetryCollector] Received a fatal error while reporting telemetry. No longer "
            "collecting events."
        )
