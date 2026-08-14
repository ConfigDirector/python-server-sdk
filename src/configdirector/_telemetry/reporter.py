from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .._http import HttpClient
from .._transport.base import REQUEST_HEADERS, is_fatal_status, resolve
from .._version import SdkIdentity
from ..errors import ConfigDirectorConnectionError, ConfigDirectorValidationError
from ..types import ConfigDirectorLogger, Context
from .queue import AggregatedEvent

__all__ = [
    "REQUEST_TIMEOUT",
    "EventReport",
    "EventReporter",
    "HttpEventReporter",
    "ReporterResponse",
]

_PATH = "server/telemetry/v1"

# Telemetry is best-effort background work, so it waits a good deal less than the transport does
# before giving up on a request and letting the next flush carry the events instead.
REQUEST_TIMEOUT = 5.0


@dataclass(frozen=True, slots=True)
class EventReport:
    evaluations: list[AggregatedEvent]
    dropped_evaluations: int
    contexts: list[Context]
    dropped_contexts: int

    @property
    def is_empty(self) -> bool:
        return (
            not self.evaluations
            and not self.contexts
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
        sdk_identity: SdkIdentity,
        logger: ConfigDirectorLogger,
        http: HttpClient,
        timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        self._server_sdk_key = server_sdk_key
        self._sdk_identity = sdk_identity
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

        response = self._send(json.dumps(self._payload(report)).encode("utf-8"))
        if response.fatal:
            self._send_requests = False
        return response

    def _payload(self, report: EventReport) -> dict[str, Any]:
        return {
            "serverSdkKey": self._server_sdk_key,
            "metaContext": {
                "sdkName": self._sdk_identity.sdk_name,
                "sdkVersion": self._sdk_identity.sdk_version,
            },
            "discreteEvents": {
                "capturedContexts": [_context_to_wire(context) for context in report.contexts]
            },
            "aggregatedEvents": {
                "evaluatedConfig": [_aggregated_to_wire(event) for event in report.evaluations]
            },
            "droppedEvents": {
                "evaluatedConfig": report.dropped_evaluations,
                "capturedContexts": report.dropped_contexts,
            },
        }

    def _send(self, body: bytes) -> ReporterResponse:
        try:
            response = self._http.post(self._url, body, REQUEST_HEADERS, self._timeout)
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

        if is_fatal_status(response.status):
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


def _aggregated_to_wire(aggregated: AggregatedEvent) -> dict[str, Any]:
    return {
        "startTime": _timestamp(aggregated.start_time),
        "endTime": _timestamp(aggregated.end_time),
        "count": aggregated.count,
        "event": aggregated.event.to_wire(),
    }


def _context_to_wire(context: Context) -> dict[str, Any]:
    # Only identified, non-anonymous contexts are ever captured, so `anonymous` is left out
    # rather than sent as a constant false.
    wire: dict[str, Any] = {"id": context.id}
    if context.name is not None:
        wire["name"] = context.name
    if context.traits is not None:
        wire["traits"] = context.traits
    return wire


def _timestamp(moment: datetime) -> str:
    # RFC 3339 with a trailing Z, the spelling the other SDKs send and the server parses.
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")
