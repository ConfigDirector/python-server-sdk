from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from .._context_kind import effective_kind
from .._http import HttpClient
from .._transport.base import is_fatal_status, request_headers, resolve
from .._version import SdkIdentity
from ..errors import ConfigDirectorConnectionError, ConfigDirectorValidationError
from ..types import ConfigDirectorLogger, Context
from .queue import AggregatedEvent, InvalidContextEntry
from .tracked_events import TrackedEventEntry, number_as_json

__all__ = [
    "REQUEST_TIMEOUT",
    "EventReport",
    "EventReporter",
    "HttpEventReporter",
    "ReporterResponse",
]

_PATH = "server/telemetry/v1"
_REPORT_TOO_LARGE_STATUS = 413

# Telemetry is best-effort background work, so it waits a good deal less than the transport does
# before giving up on a request and letting the next flush carry the events instead.
REQUEST_TIMEOUT = 5.0


@dataclass(frozen=True, slots=True)
class EventReport:
    evaluations: list[AggregatedEvent]
    dropped_evaluations: int
    contexts: list[Context]
    dropped_contexts: int
    invalid_contexts: list[InvalidContextEntry] = field(default_factory=list)
    tracked_events: list[TrackedEventEntry] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return (
            not self.evaluations
            and not self.contexts
            and not self.invalid_contexts
            and not self.tracked_events
            and self.dropped_evaluations == 0
            and self.dropped_contexts == 0
        )


# The outcome of reporting a batch of events.
@dataclass(frozen=True, slots=True)
class ReporterResponse:
    success: bool
    fatal: bool = False


class EventReporter(Protocol):
    def report(self, report: EventReport) -> ReporterResponse: ...


class HttpEventReporter:
    def __init__(
        self,
        *,
        server_sdk_key: str,
        base_url: str,
        meta_context: Mapping[str, str],
        sdk_identity: SdkIdentity,
        logger: ConfigDirectorLogger,
        http: HttpClient,
        timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        self._server_sdk_key = server_sdk_key
        self._meta_context = meta_context
        self._headers = request_headers(sdk_identity)
        self._http = http
        self._url = resolve(base_url, _PATH)
        self._logger = logger
        self._timeout = timeout
        self._send_requests = True

    def report(self, report: EventReport) -> ReporterResponse:
        if not self._send_requests:
            return ReporterResponse(success=False, fatal=True)
        if report.is_empty:
            return ReporterResponse(success=True)

        response = self._send(self._body(report))
        if response.fatal:
            self._send_requests = False
        return response

    def _body(self, report: EventReport) -> bytes:
        tracked_events = ",".join(_tracked_event_to_json(entry) for entry in report.tracked_events)
        discrete_events = _with_leading_member(
            "trackedEvents",
            f"[{tracked_events}]",
            _to_json({"capturedContexts": [_context_to_wire(context) for context in report.contexts]}),
        )
        return _with_leading_member(
            "discreteEvents", discrete_events, _to_json(self._payload_without_discrete_events(report))
        ).encode("utf-8", "replace")

    def _payload_without_discrete_events(self, report: EventReport) -> dict[str, Any]:
        return {
            "serverSdkKey": self._server_sdk_key,
            "metaContext": dict(self._meta_context),
            "aggregatedEvents": {
                "evaluatedConfig": [_aggregated_to_wire(event) for event in report.evaluations],
                "invalidContext": [_invalid_context_to_wire(entry) for entry in report.invalid_contexts],
            },
            "droppedEvents": {
                "evaluatedConfig": report.dropped_evaluations,
                "capturedContexts": report.dropped_contexts,
            },
        }

    def _send(self, body: bytes) -> ReporterResponse:
        try:
            response = self._http.post(self._url, body, self._headers, self._timeout)
        except ConfigDirectorValidationError as error:
            # The URL itself is unusable, so every retry would fail identically.
            self._logger.warning(
                "[EventReporter] The telemetry URL %r is unusable: %r. No more telemetry data will be sent.",
                self._url,
                error,
            )
            return ReporterResponse(success=False, fatal=True)
        except ConfigDirectorConnectionError as error:
            self._logger.warning("[EventReporter] Error attempting to send telemetry data: %r", error)
            return ReporterResponse(success=False)

        if _stops_reporting(response.status):
            self._logger.warning(
                "[EventReporter] Received a fatal status response (%s) from the telemetry "
                "endpoint. No more telemetry data will be sent.",
                response.status,
            )
            return ReporterResponse(success=False, fatal=True)

        if response.ok:
            self._logger.debug("[EventReporter] Telemetry report successfully sent.")
        else:
            self._logger.warning(
                "[EventReporter] The telemetry endpoint responded with status %s. The events in "
                "this report were discarded.",
                response.status,
            )

        return ReporterResponse(success=response.ok)


def _stops_reporting(status: int | None) -> bool:
    return is_fatal_status(status) and status != _REPORT_TOO_LARGE_STATUS


def _aggregated_to_wire(aggregated: AggregatedEvent) -> dict[str, Any]:
    return {
        "startTime": _timestamp(aggregated.start_time),
        "endTime": _timestamp(aggregated.end_time),
        "count": aggregated.count,
        "event": aggregated.event.to_wire(),
    }


def _invalid_context_to_wire(entry: InvalidContextEntry) -> dict[str, Any]:
    event: dict[str, Any] = {"reason": "invalid-context-kind"}
    if entry.kind_sample is not None:
        event["kindSample"] = entry.kind_sample
    return {
        "startTime": _timestamp(entry.start_time),
        "endTime": _timestamp(entry.end_time),
        "count": entry.count,
        "event": event,
    }


def _context_to_wire(context: Context) -> dict[str, Any]:
    # Only identified, non-anonymous contexts are ever captured, so `anonymous` is left out
    # rather than sent as a constant false.
    wire: dict[str, Any] = {"id": context.id, "kind": effective_kind(context)}
    if context.name is not None:
        wire["name"] = context.name
    if context.traits is not None:
        wire["traits"] = context.traits
    return wire


def _tracked_event_to_json(entry: TrackedEventEntry) -> str:
    wire: dict[str, Any] = {"name": entry.name, "happenedAt": _timestamp(entry.happened_at)}
    if entry.context_kind is not None:
        wire["contextKind"] = entry.context_kind
    if entry.context_identifier is not None:
        wire["contextIdentifier"] = entry.context_identifier
    if entry.details is not None:
        wire["details"] = entry.details
    value_as_json = number_as_json(entry.value)
    return (
        _to_json(wire)
        if value_as_json is None
        else _with_leading_member("value", value_as_json, _to_json(wire))
    )


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _with_leading_member(name: str, value_as_json: str, json_object: str) -> str:
    return f'{{"{name}":{value_as_json},{json_object[1:]}'


def _timestamp(moment: datetime) -> str:
    # RFC 3339 with a trailing Z, the spelling the other SDKs send and the server parses.
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")
