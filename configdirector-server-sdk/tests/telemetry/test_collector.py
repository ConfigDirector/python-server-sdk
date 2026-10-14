from __future__ import annotations

import threading
from collections.abc import Callable, Iterator

import pytest

from configdirector._telemetry.collector import TelemetryCollector, TelemetryCollectorOptions
from configdirector._telemetry.reporter import EventReport, ReporterResponse
from configdirector._version import SdkIdentity
from configdirector.types import Context
from tests.helpers import RecordingLogger, wait_for

# Long enough that the flush thread never fires on its own; tests that care about the interval
# ask for a short one.
NEVER = 3_600.0


class FakeReporter:
    def __init__(self) -> None:
        self.reports: list[EventReport] = []
        self.response = ReporterResponse(success=True)
        self.error: BaseException | None = None
        self.reported = threading.Event()

    def report(self, report: EventReport) -> ReporterResponse:
        self.reports.append(report)
        self.reported.set()
        if self.error is not None:
            raise self.error
        return self.response

    @property
    def events(self) -> list[tuple[str, int]]:
        """Every aggregated evaluation reported so far, as (config key, count)."""
        return [(a.event.key, a.count) for report in self.reports for a in report.evaluations]

    @property
    def contexts(self) -> list[str]:
        return [c.id or "" for report in self.reports for c in report.contexts]

    @property
    def invalid_contexts(self) -> list[tuple[str | None, int]]:
        return [
            (entry.kind_sample, entry.count) for report in self.reports for entry in report.invalid_contexts
        ]


@pytest.fixture
def reporter() -> FakeReporter:
    return FakeReporter()


@pytest.fixture
def logger() -> RecordingLogger:
    return RecordingLogger()


Factory = Callable[..., TelemetryCollector]


@pytest.fixture
def make_collector(reporter: FakeReporter, logger: RecordingLogger) -> Iterator[Factory]:
    collectors: list[TelemetryCollector] = []

    def build(**overrides: object) -> TelemetryCollector:
        options: dict[str, object] = {
            "server_sdk_key": "sdk-key",
            "base_url": "https://server-sdk-api.configdirector.com",
            "meta_context": {"sdkName": "telemetry-tests", "sdkVersion": "1.2.3"},
            "sdk_identity": SdkIdentity(sdk_name="telemetry-tests", sdk_version="1.2.3"),
            "logger": logger,
            "flush_interval": NEVER,
            "initial_flush_delay": NEVER,
            "reporter": reporter,
        }
        options.update(overrides)
        collector = TelemetryCollector(TelemetryCollectorOptions(**options))  # type: ignore[arg-type]
        collectors.append(collector)
        return collector

    yield build
    for collector in collectors:
        collector.close()


@pytest.fixture
def collector(make_collector: Factory) -> TelemetryCollector:
    return make_collector()


def flush_thread_running() -> bool:
    return any(thread.name == "configdirector-telemetry" for thread in threading.enumerate())


def record(collector: TelemetryCollector, key: str = "my-config", **overrides: object) -> None:
    arguments: dict[str, object] = {
        "key": key,
        "default": "default",
        "value": "hello",
        "used_default": False,
        "reason": "found-match",
    }
    arguments.update(overrides)
    collector.record_evaluation(**arguments)  # type: ignore[arg-type]


class TestRecording:
    def test_reports_what_was_recorded_on_flush(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        record(collector)

        collector.flush()

        assert reporter.events == [("my-config", 1)]

    def test_collapses_identical_evaluations_into_a_count(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        for _ in range(3):
            record(collector)

        collector.flush()

        assert reporter.events == [("my-config", 3)]

    def test_keeps_evaluations_of_different_configs_apart(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        record(collector, "config-a")
        record(collector, "config-b")

        collector.flush()

        assert sorted(reporter.events) == [("config-a", 1), ("config-b", 1)]

    def test_a_flush_does_not_resend_what_was_already_reported(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        record(collector)
        collector.flush()

        record(collector, "config-b")
        collector.flush()

        assert reporter.events == [("my-config", 1), ("config-b", 1)]

    def test_sends_nothing_when_there_is_nothing_to_report(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        collector.flush()

        assert reporter.reports == []

    def test_reports_a_value_too_large_to_send_inline_by_id(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        record(collector, value="x" * 600)

        collector.flush()

        reported = reporter.reports[0].evaluations[0].event
        assert reported.evaluated_value.value is None
        assert reported.evaluated_value.value_id is not None

    def test_reports_how_many_evaluations_were_dropped(
        self, make_collector: Factory, reporter: FakeReporter
    ) -> None:
        collector = make_collector(event_queue_limit=100)  # 70 evaluations, 30 contexts
        for index in range(75):
            record(collector, f"config-{index}")

        collector.flush()

        assert reporter.reports[0].dropped_evaluations == 5
        assert len(reporter.reports[0].evaluations) == 70


class TestContexts:
    def test_captures_the_context_an_evaluation_was_made_against(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        record(collector, context=Context(id="user-a"))

        collector.flush()

        assert reporter.contexts == ["user-a"]
        assert reporter.reports[0].evaluations[0].event.context_id == "user-a"

    def test_captures_each_distinct_context_once(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        record(collector, context=Context(id="user-a"))
        record(collector, context=Context(id="user-a"))
        record(collector, context=Context(id="user-b"))

        collector.flush()

        assert sorted(reporter.contexts) == ["user-a", "user-b"]

    def test_ignores_a_context_without_an_id(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        record(collector, context=Context(name="No Id"))

        collector.flush()

        assert reporter.contexts == []
        assert reporter.reports[0].evaluations[0].event.context_id is None

    def test_an_anonymous_context_is_neither_captured_nor_identified(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        record(collector, context=Context(id="user-a", anonymous=True))

        collector.flush()

        assert reporter.contexts == []
        assert reporter.reports[0].evaluations[0].event.context_id is None

    def test_a_flush_does_not_resend_contexts(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        record(collector, context=Context(id="user-a"))
        collector.flush()

        record(collector, context=Context(id="user-b"))
        collector.flush()

        assert reporter.contexts == ["user-a", "user-b"]

    def test_captures_contexts_of_different_kinds_sharing_an_identifier_separately(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        user = Context(id="42", name="Ada")
        device = Context(id="42", name="Kiosk", kind="device")
        record(collector, context=user)
        record(collector, context=device)

        collector.flush()

        assert reporter.reports[0].contexts == [user, device]

    def test_tags_each_event_with_the_kind_of_its_context(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        record(collector, context=Context(id="42"))
        record(collector, context=Context(id="42", kind="device"))

        collector.flush()

        events = [aggregated.event for aggregated in reporter.reports[0].evaluations]
        assert [(event.context_id, event.context_kind) for event in events] == [
            ("42", "user"),
            ("42", "device"),
        ]

    def test_an_event_without_a_captured_context_has_no_kind(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        record(collector, context=Context(name="No Id", kind="device"))

        collector.flush()

        assert reporter.reports[0].evaluations[0].event.context_kind is None

    def test_reports_how_many_contexts_were_dropped(
        self, make_collector: Factory, reporter: FakeReporter
    ) -> None:
        collector = make_collector(event_queue_limit=100)  # 70 evaluations, 30 contexts
        for index in range(35):
            record(collector, context=Context(id=f"user-{index}"))

        collector.flush()

        assert reporter.reports[0].dropped_contexts == 5
        assert len(reporter.reports[0].contexts) == 30


class TestInvalidContexts:
    def test_counts_the_submissions_of_each_invalid_kind(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        collector.record_invalid_context("Device")
        collector.record_invalid_context("")
        collector.record_invalid_context("Device")

        collector.flush()

        assert reporter.invalid_contexts == [("Device", 2), ("", 1)]

    def test_says_whether_a_kind_sample_is_new_to_the_interval(self, collector: TelemetryCollector) -> None:
        assert collector.record_invalid_context("Device") == "new-kind-sample"
        assert collector.record_invalid_context("Device") == "known-kind-sample"
        assert collector.record_invalid_context("Tenant") == "new-kind-sample"

    def test_keeps_20_kind_samples_and_counts_further_submissions_without_one(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        for index in range(20):
            collector.record_invalid_context(f"Kind-{index}")

        recordings = [
            collector.record_invalid_context("Kind-20"),
            collector.record_invalid_context("Kind-21"),
            collector.record_invalid_context("Kind-20"),
            collector.record_invalid_context("Kind-0"),
        ]
        collector.flush()

        assert recordings == [
            "first-beyond-sample-limit",
            "beyond-sample-limit",
            "beyond-sample-limit",
            "known-kind-sample",
        ]
        assert reporter.invalid_contexts == [
            *((f"Kind-{index}", 2 if index == 0 else 1) for index in range(20)),
            (None, 3),
        ]

    def test_a_flush_starts_the_kind_samples_over(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        for index in range(21):
            collector.record_invalid_context(f"Kind-{index}")
        collector.flush()

        assert collector.record_invalid_context("Kind-0") == "new-kind-sample"
        assert collector.record_invalid_context("Kind-20") == "new-kind-sample"
        collector.flush()
        assert reporter.invalid_contexts[-2:] == [("Kind-0", 1), ("Kind-20", 1)]

    def test_reports_the_window_the_submissions_were_made_in(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        collector.record_invalid_context("Device")
        record(collector)

        collector.flush()

        entry = reporter.reports[0].invalid_contexts[0]
        assert entry.start_time <= entry.end_time
        assert entry.start_time <= reporter.reports[0].evaluations[0].start_time

    def test_reports_invalid_contexts_when_nothing_else_was_recorded(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        collector.record_invalid_context("Device")

        collector.flush()

        assert len(reporter.reports) == 1
        assert reporter.reports[0].evaluations == []

    def test_stops_reporting_invalid_contexts_after_a_fatal_response(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        reporter.response = ReporterResponse(success=False, fatal=True)
        record(collector)
        collector.flush()

        collector.record_invalid_context("Device")
        collector.flush()

        assert len(reporter.reports) == 1
        assert reporter.invalid_contexts == []

    def test_after_a_fatal_response_each_kind_sample_stays_known_for_good(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        reporter.response = ReporterResponse(success=False, fatal=True)
        record(collector)
        collector.flush()

        first = collector.record_invalid_context("Device")
        collector.flush()
        second = collector.record_invalid_context("Device")

        assert (first, second) == ("new-kind-sample", "known-kind-sample")

    def test_reports_invalid_contexts_left_on_close(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        collector.record_invalid_context("Device")

        collector.close()

        assert reporter.invalid_contexts == [("Device", 1)]

    def test_after_close_invalid_contexts_are_not_reported_and_each_kind_sample_stays_known(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        collector.close()

        first = collector.record_invalid_context("Device")
        collector.flush()
        second = collector.record_invalid_context("Device")

        assert (first, second) == ("new-kind-sample", "known-kind-sample")
        assert reporter.reports == []

    def test_after_close_keeps_logging_bounded_to_20_kind_samples(
        self, collector: TelemetryCollector
    ) -> None:
        collector.close()
        for index in range(20):
            collector.record_invalid_context(f"Kind-{index}")

        assert collector.record_invalid_context("Kind-20") == "first-beyond-sample-limit"
        assert collector.record_invalid_context("Kind-21") == "beyond-sample-limit"


class TestFlushInterval:
    def test_flushes_on_its_own_without_being_asked(
        self, make_collector: Factory, reporter: FakeReporter
    ) -> None:
        collector = make_collector(initial_flush_delay=0.01)
        record(collector)

        assert reporter.reported.wait(timeout=5.0)
        assert reporter.events == [("my-config", 1)]

    def test_keeps_flushing_on_the_interval(self, make_collector: Factory, reporter: FakeReporter) -> None:
        collector = make_collector(initial_flush_delay=0.01, flush_interval=0.01)
        record(collector, "config-a")
        assert wait_for(lambda: len(reporter.reports) >= 1)

        record(collector, "config-b")

        assert wait_for(lambda: len(reporter.reports) >= 2)
        assert sorted(reporter.events) == [("config-a", 1), ("config-b", 1)]

    def test_an_idle_collector_makes_no_requests(
        self, make_collector: Factory, reporter: FakeReporter
    ) -> None:
        make_collector(initial_flush_delay=0.01, flush_interval=0.01)

        assert reporter.reported.wait(timeout=0.2) is False


class TestFatalErrors:
    def test_stops_collecting_after_a_fatal_response(
        self, collector: TelemetryCollector, reporter: FakeReporter, logger: RecordingLogger
    ) -> None:
        reporter.response = ReporterResponse(success=False, fatal=True)
        record(collector)
        collector.flush()

        reporter.response = ReporterResponse(success=True)
        record(collector, "config-after-fatal")
        collector.flush()

        # Only the report that failed was ever attempted; what came after it was never collected.
        assert len(reporter.reports) == 1
        assert reporter.events == [("my-config", 1)]
        assert any("No longer collecting" in m for m in logger.messages("warning"))

    def test_keeps_collecting_after_a_failure_worth_retrying(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        reporter.response = ReporterResponse(success=False, fatal=False)
        record(collector)
        collector.flush()

        record(collector, "config-b")
        collector.flush()

        assert len(reporter.reports) == 2

    def test_a_reporter_that_raises_does_not_stop_collection(
        self, collector: TelemetryCollector, reporter: FakeReporter, logger: RecordingLogger
    ) -> None:
        reporter.error = RuntimeError("boom")
        record(collector)
        collector.flush()

        reporter.error = None
        record(collector, "config-b")
        collector.flush()

        assert len(reporter.reports) == 2
        assert reporter.events[-1] == ("config-b", 1)
        assert any("Error reporting telemetry" in m for m in logger.messages("warning"))

    def test_the_flush_thread_stops_itself_after_a_fatal_response(
        self, make_collector: Factory, reporter: FakeReporter
    ) -> None:
        reporter.response = ReporterResponse(success=False, fatal=True)
        collector = make_collector(initial_flush_delay=0.01, flush_interval=0.01)
        record(collector)

        assert wait_for(lambda: not flush_thread_running())
        assert len(reporter.reports) == 1

    def test_a_reporter_that_raises_does_not_kill_the_flush_thread(
        self, make_collector: Factory, reporter: FakeReporter
    ) -> None:
        reporter.error = RuntimeError("boom")
        collector = make_collector(initial_flush_delay=0.01, flush_interval=0.01)
        record(collector)
        assert wait_for(lambda: len(reporter.reports) >= 1)

        reporter.error = None
        record(collector, "config-b")

        assert wait_for(lambda: any(key == "config-b" for key, _ in reporter.events))


class TestClose:
    def test_reports_what_is_left_on_close(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        record(collector)

        collector.close()

        assert reporter.events == [("my-config", 1)]

    def test_stops_collecting_once_closed(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        collector.close()

        record(collector)
        collector.flush()

        assert reporter.reports == []

    def test_closing_twice_reports_once(self, collector: TelemetryCollector, reporter: FakeReporter) -> None:
        record(collector)

        collector.close()
        collector.close()

        assert len(reporter.reports) == 1

    def test_does_not_report_again_after_a_fatal_error(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        reporter.response = ReporterResponse(success=False, fatal=True)
        record(collector)
        collector.flush()

        collector.close()

        assert len(reporter.reports) == 1

    def test_survives_the_closing_report_failing_fatally(
        self, collector: TelemetryCollector, reporter: FakeReporter
    ) -> None:
        reporter.response = ReporterResponse(success=False, fatal=True)
        record(collector)

        collector.close()

        assert len(reporter.reports) == 1
        assert collector._closed is True

    def test_stops_the_flush_thread(self, make_collector: Factory) -> None:
        collector = make_collector(initial_flush_delay=0.01, flush_interval=0.01)

        collector.close()

        assert wait_for(lambda: not flush_thread_running())
