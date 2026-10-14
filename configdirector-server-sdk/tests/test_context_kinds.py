from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any, cast

import pytest

from configdirector import ConfigEvaluatedEvent, Context
from configdirector._evaluation import Config, Percentage
from configdirector._http import HttpClient
from configdirector._telemetry import TelemetryCollector, TelemetryCollectorOptions
from configdirector.client import _ConfigDirectorClient
from tests.helpers import (
    RecordingLogger,
    StubHttp,
    TransportRecorder,
    bundle,
    condition,
    conditional_rule,
    config,
    percentage_rule,
)

SDK_KEY = "test-server-sdk-key"
CONFIG_ID = "11111111-1111-4111-8111-111111111111"
NEVER = 3_600.0
INVALID_KIND_MESSAGE = (
    "Ignored a context with the invalid kind '{}' and evaluated as if no context was supplied. "
    "A context kind has 1 to 64 characters, using only lowercase letters, digits, '-' and '_'."
)
FURTHER_INVALID_KINDS_MESSAGE = (
    "Ignored a context with another invalid kind and evaluated as if no context was supplied. "
    "20 different invalid kinds were logged recently, so further invalid kinds are not logged "
    "individually."
)


class ReportingTelemetry:
    def __init__(self, http: StubHttp) -> None:
        self._http = http
        self.collectors: list[TelemetryCollector] = []

    def __call__(self, options: TelemetryCollectorOptions) -> TelemetryCollector:
        collector = TelemetryCollector(
            replace(
                options,
                http=cast(HttpClient, self._http),
                flush_interval=NEVER,
                initial_flush_delay=NEVER,
            )
        )
        self.collectors.append(collector)
        return collector

    @property
    def last(self) -> TelemetryCollector:
        return self.collectors[-1]


@pytest.fixture
def http() -> StubHttp:
    return StubHttp()


@pytest.fixture
def logger() -> RecordingLogger:
    return RecordingLogger()


@pytest.fixture
def reporting(http: StubHttp) -> ReportingTelemetry:
    return ReportingTelemetry(http)


@pytest.fixture
def client(
    transports: TransportRecorder, reporting: ReportingTelemetry, logger: RecordingLogger
) -> Iterator[_ConfigDirectorClient]:
    client = _ConfigDirectorClient(
        SDK_KEY, logger=logger, transport_factory=transports, telemetry_factory=reporting
    )
    yield client
    client.close()


def greeting_for_42() -> Config:
    return config(
        "greeting",
        "hello",
        rules=[conditional_rule("hello 42", condition("identifier", "equals", "42"))],
    )


def evaluations(client: _ConfigDirectorClient) -> list[ConfigEvaluatedEvent]:
    events: list[ConfigEvaluatedEvent] = []
    client.on("config_evaluated", events.append)
    return events


def invalid_contexts_reported(http: StubHttp) -> list[tuple[str | None, int]]:
    return [
        (entry["event"].get("kindSample"), entry["count"])
        for call in http.calls
        for entry in call.payload["aggregatedEvents"]["invalidContext"]
    ]


INVALID_KINDS = ["", "a" * 65, "Device", " device ", 42]


class UnprintableKind:
    def __str__(self) -> str:
        raise RuntimeError("no string form")


class TestAnInvalidKind:
    @pytest.mark.parametrize("kind", INVALID_KINDS)
    def test_evaluates_exactly_as_the_same_call_without_a_context(
        self, client: _ConfigDirectorClient, transports: TransportRecorder, kind: Any
    ) -> None:
        transports.initial_bundle = bundle(greeting_for_42())
        client.initialize()
        events = evaluations(client)

        without_a_context = client.get_value("greeting", "in-code-default")
        with_an_invalid_kind = client.get_value("greeting", "in-code-default", Context(id="42", kind=kind))

        assert with_an_invalid_kind == without_a_context == "hello"
        assert events[1].evaluation == events[0].evaluation
        assert events[1].evaluation.reason == "found-match"
        assert events[1].evaluation.context is None

    @pytest.mark.parametrize("kind", INVALID_KINDS)
    def test_evaluates_exactly_as_the_same_call_without_a_context_before_the_client_is_ready(
        self, client: _ConfigDirectorClient, kind: Any
    ) -> None:
        events = evaluations(client)

        value = client.get_value("greeting", "in-code-default", Context(id="42", kind=kind))

        assert value == "in-code-default"
        assert events[0].evaluation.reason == "client-not-ready"
        assert events[0].evaluation.context is None

    @pytest.mark.parametrize("kind", INVALID_KINDS)
    def test_logs_an_error(self, client: _ConfigDirectorClient, logger: RecordingLogger, kind: Any) -> None:
        client.get_value("greeting", "in-code-default", Context(id="42", kind=kind))

        assert logger.messages("error") == [INVALID_KIND_MESSAGE.format(kind)]

    @pytest.mark.parametrize("kind", INVALID_KINDS)
    def test_a_watcher_receives_the_value_for_no_context(
        self, client: _ConfigDirectorClient, transports: TransportRecorder, kind: Any
    ) -> None:
        values: list[str] = []
        client.watch("greeting", "in-code-default", values.append, Context(id="42", kind=kind))
        transports.initial_bundle = bundle(greeting_for_42())

        client.initialize()

        assert values == ["hello"]

    @pytest.mark.parametrize("kind", INVALID_KINDS)
    def test_get_all_configs_evaluates_as_without_a_context(
        self, client: _ConfigDirectorClient, transports: TransportRecorder, kind: Any
    ) -> None:
        transports.initial_bundle = bundle(greeting_for_42())
        client.initialize()

        configs = client.get_all_configs(Context(id="42", kind=kind))

        assert configs["greeting"].value == "hello"

    def test_a_valid_kind_is_evaluated_and_reported_with_the_evaluation(
        self, client: _ConfigDirectorClient, transports: TransportRecorder, logger: RecordingLogger
    ) -> None:
        transports.initial_bundle = bundle(greeting_for_42())
        client.initialize()
        events = evaluations(client)
        device = Context(id="42", kind="a-device_2")

        value = client.get_value("greeting", "in-code-default", device)

        assert value == "hello 42"
        assert events[0].evaluation.context == device
        assert logger.messages("error") == []


class TestLoggingInvalidKinds:
    def test_logs_each_invalid_kind_once_per_flush_interval(
        self, client: _ConfigDirectorClient, reporting: ReportingTelemetry, logger: RecordingLogger
    ) -> None:
        client.get_value("greeting", "in-code-default", Context(kind="Device"))
        client.get_value("greeting", "in-code-default", Context(kind="Device"))
        client.get_value("greeting", "in-code-default", Context(kind="Tenant"))

        reporting.last.flush()
        client.get_value("greeting", "in-code-default", Context(kind="Device"))

        assert logger.messages("error") == [
            INVALID_KIND_MESSAGE.format("Device"),
            INVALID_KIND_MESSAGE.format("Tenant"),
            INVALID_KIND_MESSAGE.format("Device"),
        ]

    def test_logs_once_that_further_invalid_kinds_are_not_logged_after_20_in_an_interval(
        self, client: _ConfigDirectorClient, logger: RecordingLogger
    ) -> None:
        for index in range(23):
            client.get_value("greeting", "in-code-default", Context(kind=f"Kind-{index}"))

        assert logger.messages("error") == [
            *(INVALID_KIND_MESSAGE.format(f"Kind-{index}") for index in range(20)),
            FURTHER_INVALID_KINDS_MESSAGE,
        ]

    def test_logs_the_kind_cut_to_128_characters(
        self, client: _ConfigDirectorClient, logger: RecordingLogger
    ) -> None:
        client.get_value("greeting", "in-code-default", Context(kind="É" * 200))

        assert logger.messages("error") == [INVALID_KIND_MESSAGE.format("É" * 128)]

    def test_after_a_fatal_telemetry_response_each_invalid_kind_is_logged_once(
        self,
        client: _ConfigDirectorClient,
        reporting: ReportingTelemetry,
        http: StubHttp,
        logger: RecordingLogger,
    ) -> None:
        http.status = 401
        client.get_value("greeting", "in-code-default")
        reporting.last.flush()

        client.get_value("greeting", "in-code-default", Context(kind="Device"))
        reporting.last.flush()
        client.get_value("greeting", "in-code-default", Context(kind="Device"))

        assert logger.messages("error") == [INVALID_KIND_MESSAGE.format("Device")]

    def test_after_close_each_invalid_kind_is_logged_once(
        self, client: _ConfigDirectorClient, logger: RecordingLogger
    ) -> None:
        client.close()

        client.get_value("greeting", "in-code-default", Context(kind="Device"))
        client.get_value("greeting", "in-code-default", Context(kind="Device"))

        assert logger.messages("error") == [INVALID_KIND_MESSAGE.format("Device")]


class TestReportingInvalidKinds:
    def test_counts_every_evaluation_given_an_invalid_kind(
        self, client: _ConfigDirectorClient, reporting: ReportingTelemetry, http: StubHttp
    ) -> None:
        client.get_value("greeting", "in-code-default", Context(id="42", kind="Device"))
        client.get_value("greeting", "in-code-default", Context(id="42", kind="Device"))
        client.get_value("greeting", "in-code-default", Context(id="42", kind=" device"))

        reporting.last.flush()

        assert invalid_contexts_reported(http) == [("Device", 2), (" device", 1)]

    def test_counts_every_watcher_re_evaluation(
        self,
        client: _ConfigDirectorClient,
        transports: TransportRecorder,
        reporting: ReportingTelemetry,
        http: StubHttp,
    ) -> None:
        client.watch("greeting", "in-code-default", lambda _value: None, Context(id="42", kind="Device"))
        transports.initial_bundle = bundle(greeting_for_42())
        client.initialize()

        transports.last.deliver(bundle(greeting_for_42(), kind="delta"))
        transports.last.deliver(bundle(greeting_for_42(), kind="delta"))
        reporting.last.flush()

        assert invalid_contexts_reported(http) == [("Device", 3)]

    def test_get_all_configs_counts_once_per_call(
        self,
        client: _ConfigDirectorClient,
        transports: TransportRecorder,
        reporting: ReportingTelemetry,
        http: StubHttp,
    ) -> None:
        transports.initial_bundle = bundle(config("first", "1"), config("second", "2"), config("third", "3"))
        client.initialize()

        client.get_all_configs(Context(id="42", kind="Device"))
        client.get_all_configs(Context(id="42", kind="Device"))
        reporting.last.flush()

        assert invalid_contexts_reported(http) == [("Device", 2)]

    def test_sends_a_report_holding_only_invalid_contexts(
        self,
        client: _ConfigDirectorClient,
        transports: TransportRecorder,
        reporting: ReportingTelemetry,
        http: StubHttp,
    ) -> None:
        client.initialize()

        client.get_all_configs(Context(id="42", kind="Device"))
        reporting.last.flush()

        assert len(http.calls) == 1
        assert http.payload["aggregatedEvents"] == {
            "evaluatedConfig": [],
            "invalidContext": [
                {
                    "startTime": http.payload["aggregatedEvents"]["invalidContext"][0]["startTime"],
                    "endTime": http.payload["aggregatedEvents"]["invalidContext"][0]["endTime"],
                    "count": 1,
                    "event": {"reason": "invalid-context-kind", "kindSample": "Device"},
                }
            ],
        }

    def test_reports_kinds_cut_to_128_characters(
        self, client: _ConfigDirectorClient, reporting: ReportingTelemetry, http: StubHttp
    ) -> None:
        client.get_value("greeting", "in-code-default", Context(kind="A" * 129))
        client.get_value("greeting", "in-code-default", Context(kind="É" * 200))

        reporting.last.flush()

        assert invalid_contexts_reported(http) == [("A" * 128, 1), ("É" * 128, 1)]

    def test_reports_a_kind_that_is_not_a_str_as_its_string_form(
        self, client: _ConfigDirectorClient, reporting: ReportingTelemetry, http: StubHttp
    ) -> None:
        client.get_value("greeting", "in-code-default", Context(kind=42))  # type: ignore[arg-type]
        client.get_value("greeting", "in-code-default", Context(kind=True))  # type: ignore[arg-type]

        reporting.last.flush()

        assert invalid_contexts_reported(http) == [("42", 1), ("True", 1)]

    def test_reports_a_kind_whose_string_form_raises_by_its_type_name(
        self,
        client: _ConfigDirectorClient,
        reporting: ReportingTelemetry,
        http: StubHttp,
        logger: RecordingLogger,
    ) -> None:
        value = client.get_value("greeting", "in-code-default", Context(kind=UnprintableKind()))  # type: ignore[arg-type]

        reporting.last.flush()

        assert value == "in-code-default"
        assert invalid_contexts_reported(http) == [("UnprintableKind", 1)]
        assert logger.messages("error") == [INVALID_KIND_MESSAGE.format("UnprintableKind")]

    def test_keeps_20_kind_samples_and_counts_further_submissions_without_one(
        self, client: _ConfigDirectorClient, reporting: ReportingTelemetry, http: StubHttp
    ) -> None:
        for index in range(25):
            client.get_value("greeting", "in-code-default", Context(kind=f"Kind-{index}"))

        reporting.last.flush()

        assert invalid_contexts_reported(http) == [
            *((f"Kind-{index}", 1) for index in range(20)),
            (None, 5),
        ]

    def test_never_reports_the_identifier_name_or_traits_of_a_context_with_an_invalid_kind(
        self,
        client: _ConfigDirectorClient,
        transports: TransportRecorder,
        reporting: ReportingTelemetry,
        http: StubHttp,
    ) -> None:
        transports.initial_bundle = bundle(greeting_for_42())
        client.initialize()

        client.get_value(
            "greeting",
            "in-code-default",
            Context(id="secret-id", name="Secret Name", traits={"secret": "trait"}, kind="Device"),
        )
        reporting.last.flush()

        body = http.calls[0].body.decode("utf-8")
        assert "secret" not in body.lower()
        assert http.payload["discreteEvents"]["capturedContexts"] == []
        assert "contextId" not in http.payload["aggregatedEvents"]["evaluatedConfig"][0]["event"]

    def test_stops_reporting_invalid_kinds_once_telemetry_stops(
        self, client: _ConfigDirectorClient, reporting: ReportingTelemetry, http: StubHttp
    ) -> None:
        http.status = 401
        client.get_value("greeting", "in-code-default")
        reporting.last.flush()

        client.get_value("greeting", "in-code-default", Context(kind="Device"))
        reporting.last.flush()
        client.close()

        assert len(http.calls) == 1
        assert invalid_contexts_reported(http) == []


class TestReportingKinds:
    def test_reports_user_42_and_device_42_as_two_contexts_with_their_kinds(
        self, client: _ConfigDirectorClient, reporting: ReportingTelemetry, http: StubHttp
    ) -> None:
        client.get_value("greeting", "in-code-default", Context(id="42", name="Ada"))
        client.get_value("greeting", "in-code-default", Context(id="42", name="Kiosk", kind="device"))

        reporting.last.flush()

        assert http.payload["discreteEvents"]["capturedContexts"] == [
            {"id": "42", "kind": "user", "name": "Ada"},
            {"id": "42", "kind": "device", "name": "Kiosk"},
        ]
        sent = [entry["event"] for entry in http.payload["aggregatedEvents"]["evaluatedConfig"]]
        assert [(event["contextId"], event["contextKind"]) for event in sent] == [
            ("42", "user"),
            ("42", "device"),
        ]


class TestTargetingKinds:
    def test_serves_a_rule_targeting_a_kind_only_to_contexts_of_that_kind(
        self, client: _ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = bundle(
            config(
                "greeting",
                "hello",
                rules=[conditional_rule("hello device", condition("kind", "is one of", "device", "tenant"))],
            )
        )
        client.initialize()

        assert (
            client.get_value("greeting", "in-code-default", Context(id="42", kind="device")) == "hello device"
        )
        assert client.get_value("greeting", "in-code-default", Context(id="42", kind="user")) == "hello"
        assert client.get_value("greeting", "in-code-default", Context(id="42")) == "hello"
        assert client.get_value("greeting", "in-code-default") == "hello"

    def test_a_user_and_a_device_sharing_an_identifier_get_their_own_buckets(
        self, client: _ConfigDirectorClient, transports: TransportRecorder
    ) -> None:
        transports.initial_bundle = bundle(
            config(
                "split",
                "this-is-the-default",
                id=CONFIG_ID,
                rules=[
                    percentage_rule(
                        Percentage(id="b0", percentage=8, value="below 8"),
                        Percentage(id="b1", percentage=42, value="8 to 50"),
                        Percentage(id="b2", percentage=50, value="50 and above"),
                    )
                ],
            )
        )
        client.initialize()

        assert client.get_value("split", "in-code-default", Context(id="user-1")) == "below 8"
        assert (
            client.get_value("split", "in-code-default", Context(id="user-1", kind="device"))
            == "50 and above"
        )
        assert client.get_value("split", "in-code-default", Context(id="user-1", kind="tenant")) == "8 to 50"
        assert client.get_value("split", "in-code-default", Context(kind="device")) == "below 8"
