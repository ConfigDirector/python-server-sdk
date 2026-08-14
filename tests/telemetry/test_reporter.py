from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

import pytest

from configdirector import _http
from configdirector._http import HttpClient
from configdirector._telemetry import reporter as reporter_module
from configdirector._telemetry.events import EvaluatedConfigEvent
from configdirector._telemetry.queue import AggregatedEvent
from configdirector._telemetry.reporter import EventReport, HttpEventReporter
from configdirector._version import SdkIdentity
from configdirector.errors import ConfigDirectorConnectionError, ConfigDirectorValidationError
from configdirector.types import Context
from tests.helpers import RecordingLogger

BASE_URL = "https://server-sdk-api.configdirector.com"
START = datetime(2026, 1, 1, 0, 0, 0, 500_000, tzinfo=timezone.utc)
END = datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc)


@dataclass
class Call:
    url: str
    body: bytes
    headers: Mapping[str, str]
    timeout: float

    @property
    def payload(self) -> Any:
        return json.loads(self.body)


class StubHttp:
    """Stands in for the HTTP layer, recording what was posted and replying as told."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.status = 204
        self.error: BaseException | None = None

    def post(self, url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> _http.HttpResponse:
        self.calls.append(Call(url=url, body=body, headers=headers, timeout=timeout))
        if self.error is not None:
            raise self.error
        return _http.HttpResponse(status=self.status, body="")

    @property
    def payload(self) -> Any:
        return self.calls[-1].payload


@pytest.fixture
def http() -> StubHttp:
    # Injected as the reporter's HttpClient, so nothing has to be patched into place.
    return StubHttp()


@pytest.fixture
def logger() -> RecordingLogger:
    return RecordingLogger()


@pytest.fixture
def reporter(logger: RecordingLogger, http: StubHttp) -> HttpEventReporter:
    return HttpEventReporter(
        server_sdk_key="sdk-key",
        base_url=BASE_URL,
        sdk_identity=SdkIdentity(sdk_name="telemetry-tests", sdk_version="1.2.3"),
        logger=logger,
        http=cast(HttpClient, http),
    )


def event(key: str = "my-config", context_id: str | None = None) -> EvaluatedConfigEvent:
    return EvaluatedConfigEvent.of(
        key=key,
        default="default",
        value="hello",
        used_default=False,
        reason="found-match",
        context_id=context_id,
        config_type="string",
    )


def report(
    *events: EvaluatedConfigEvent,
    contexts: list[Context] | None = None,
    dropped_evaluations: int = 0,
    dropped_contexts: int = 0,
) -> EventReport:
    return EventReport(
        evaluations=[AggregatedEvent(start_time=START, end_time=END, count=1, event=e) for e in events],
        dropped_evaluations=dropped_evaluations,
        contexts=contexts or [],
        dropped_contexts=dropped_contexts,
    )


class TestRequest:
    def test_posts_to_the_telemetry_endpoint(self, reporter: HttpEventReporter, http: StubHttp) -> None:
        reporter.report(report(event()))

        assert http.calls[0].url == f"{BASE_URL}/server/telemetry/v1"

    def test_keeps_the_path_of_a_proxy_base_url(self, logger: RecordingLogger, http: StubHttp) -> None:
        proxied = HttpEventReporter(
            server_sdk_key="sdk-key",
            base_url="https://proxy.example.com/configdirector",
            sdk_identity=SdkIdentity(sdk_name="tests", sdk_version="1.2.3"),
            logger=logger,
            http=cast(HttpClient, http),
        )

        proxied.report(report(event()))

        assert http.calls[0].url == "https://proxy.example.com/configdirector/server/telemetry/v1"

    def test_identifies_the_sdk_and_sends_json(self, reporter: HttpEventReporter, http: StubHttp) -> None:
        reporter.report(report(event()))

        headers = http.calls[0].headers
        assert headers["Content-Type"] == "application/json"
        assert headers["User-Agent"].startswith("python-server-sdk/")

    def test_gives_up_on_a_request_sooner_than_the_transport_does(
        self, reporter: HttpEventReporter, http: StubHttp
    ) -> None:
        reporter.report(report(event()))

        assert http.calls[0].timeout == reporter_module.REQUEST_TIMEOUT


class TestPayload:
    def test_sends_the_sdk_key(self, reporter: HttpEventReporter, http: StubHttp) -> None:
        reporter.report(report(event()))

        assert http.payload["serverSdkKey"] == "sdk-key"

    def test_sends_the_sdk_name_and_version(self, reporter: HttpEventReporter, http: StubHttp) -> None:
        reporter.report(report(event()))

        assert http.payload["metaContext"]["sdkName"] == "telemetry-tests"
        assert http.payload["metaContext"]["sdkVersion"] == "1.2.3"

    def test_sends_each_aggregated_evaluation_with_its_window_and_count(
        self, reporter: HttpEventReporter, http: StubHttp
    ) -> None:
        reporter.report(report(event()))

        assert http.payload["aggregatedEvents"]["evaluatedConfig"] == [
            {
                "startTime": "2026-01-01T00:00:00.500Z",
                "endTime": "2026-01-01T00:01:00.000Z",
                "count": 1,
                "event": {
                    "key": "my-config",
                    "type": "string",
                    "defaultValue": {"value": "default"},
                    "requestedType": "str",
                    "evaluatedValue": {"value": "hello"},
                    "usedDefault": False,
                    "evaluationReason": "found-match",
                },
            }
        ]

    def test_timestamps_are_rfc3339_in_utc(self, reporter: HttpEventReporter, http: StubHttp) -> None:
        reporter.report(report(event()))

        aggregated = http.payload["aggregatedEvents"]["evaluatedConfig"][0]
        for field in ("startTime", "endTime"):
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", aggregated[field])

    def test_sends_the_captured_contexts(self, reporter: HttpEventReporter, http: StubHttp) -> None:
        reporter.report(
            report(event(), contexts=[Context(id="user-a", name="Admin", traits={"plan": "pro"})])
        )

        assert http.payload["discreteEvents"]["capturedContexts"] == [
            {"id": "user-a", "name": "Admin", "traits": {"plan": "pro"}}
        ]

    def test_omits_context_fields_that_were_not_supplied(
        self, reporter: HttpEventReporter, http: StubHttp
    ) -> None:
        reporter.report(report(event(), contexts=[Context(id="user-a")]))

        assert http.payload["discreteEvents"]["capturedContexts"] == [{"id": "user-a"}]

    def test_always_sends_both_dropped_counts(self, reporter: HttpEventReporter, http: StubHttp) -> None:
        # The server rejects a droppedEvents object without an evaluatedConfig count.
        reporter.report(report(event()))

        assert http.payload["droppedEvents"] == {"evaluatedConfig": 0, "capturedContexts": 0}

    def test_reports_what_was_dropped(self, reporter: HttpEventReporter, http: StubHttp) -> None:
        reporter.report(report(event(), dropped_evaluations=7, dropped_contexts=3))

        assert http.payload["droppedEvents"] == {"evaluatedConfig": 7, "capturedContexts": 3}

    def test_sends_the_context_id_an_event_was_evaluated_against(
        self, reporter: HttpEventReporter, http: StubHttp
    ) -> None:
        reporter.report(report(event(context_id="user-a")))

        assert http.payload["aggregatedEvents"]["evaluatedConfig"][0]["event"]["contextId"] == "user-a"


class TestEmptyReports:
    def test_does_not_send_a_report_with_nothing_in_it(
        self, reporter: HttpEventReporter, http: StubHttp
    ) -> None:
        response = reporter.report(report())

        assert http.calls == []
        assert response.success is True

    def test_sends_a_report_that_holds_only_dropped_counts(
        self, reporter: HttpEventReporter, http: StubHttp
    ) -> None:
        # Losing every event is exactly what ConfigDirector needs to hear about.
        reporter.report(report(dropped_evaluations=5))

        assert len(http.calls) == 1

    def test_sends_a_report_that_holds_only_contexts(
        self, reporter: HttpEventReporter, http: StubHttp
    ) -> None:
        reporter.report(report(contexts=[Context(id="user-a")]))

        assert len(http.calls) == 1


class TestFailures:
    def test_a_successful_status_reports_success(self, reporter: HttpEventReporter, http: StubHttp) -> None:
        http.status = 204

        assert reporter.report(report(event())) == reporter_module.ReporterResponse(success=True)

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 429])
    def test_a_client_error_is_fatal(
        self, reporter: HttpEventReporter, http: StubHttp, status: int, logger: RecordingLogger
    ) -> None:
        http.status = status

        response = reporter.report(report(event()))

        assert response.success is False
        assert response.fatal is True
        assert any(str(status) in message for message in logger.messages("warning"))

    @pytest.mark.parametrize("status", [500, 502, 503])
    def test_a_server_error_is_worth_retrying(
        self, reporter: HttpEventReporter, http: StubHttp, status: int
    ) -> None:
        http.status = status

        response = reporter.report(report(event()))

        assert response.success is False
        assert response.fatal is False

    def test_stops_sending_after_a_fatal_response(self, reporter: HttpEventReporter, http: StubHttp) -> None:
        http.status = 401
        reporter.report(report(event()))

        http.status = 204
        response = reporter.report(report(event()))

        assert len(http.calls) == 1
        assert response.fatal is True

    def test_a_connection_error_is_worth_retrying(
        self, reporter: HttpEventReporter, http: StubHttp, logger: RecordingLogger
    ) -> None:
        http.error = ConfigDirectorConnectionError("refused")

        response = reporter.report(report(event()))

        assert response.success is False
        assert response.fatal is False
        assert any("Error attempting to send" in m for m in logger.messages("warning"))

    def test_an_unusable_url_is_fatal(
        self, reporter: HttpEventReporter, http: StubHttp, logger: RecordingLogger
    ) -> None:
        # Every retry would fail identically, so there is no point making them.
        http.error = ConfigDirectorValidationError("no host")

        response = reporter.report(report(event()))

        assert response.fatal is True
        assert any("unusable" in m for m in logger.messages("warning"))
