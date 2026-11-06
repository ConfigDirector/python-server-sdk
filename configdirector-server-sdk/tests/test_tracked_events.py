from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any, cast

import pytest

from configdirector import ConnectionOptions, Context
from configdirector.client import _ConfigDirectorClient
from tests.helpers import RecordingLogger, ReportingTelemetry, StubHttp, TransportRecorder

SDK_KEY = "test-server-sdk-key"


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


def entries_sent_on_close(client: _ConfigDirectorClient, http: StubHttp) -> list[dict[str, Any]]:
    client.close()
    entries: list[dict[str, Any]] = http.payload["discreteEvents"]["trackedEvents"]
    return entries


def value_as_written_on_close(client: _ConfigDirectorClient, http: StubHttp) -> str:
    client.close()
    payload = json.loads(http.calls[-1].body, parse_int=str, parse_float=str)
    value: str = payload["discreteEvents"]["trackedEvents"][0]["value"]
    return value


def without_the_time(entry: dict[str, Any]) -> dict[str, Any]:
    return {field: value for field, value in entry.items() if field != "happenedAt"}


def test_sends_an_event_tracked_for_a_context_on_the_next_telemetry_batch_with_its_value_and_details(
    client: _ConfigDirectorClient, http: StubHttp
) -> None:
    client.track(
        "checkout-completed",
        Context(id="user-1"),
        value=49.9,
        details={"plan": "pro", "seats": 3, "trial": False, "items": [{"sku": "book"}]},
    )

    entries = entries_sent_on_close(client, http)

    assert [without_the_time(entry) for entry in entries] == [
        {
            "name": "checkout-completed",
            "contextKind": "user",
            "contextIdentifier": "user-1",
            "value": 49.9,
            "details": {"plan": "pro", "seats": 3, "trial": False, "items": [{"sku": "book"}]},
        }
    ]


def test_stamps_an_event_with_the_time_track_was_called_rather_than_the_time_it_was_sent(
    client: _ConfigDirectorClient, http: StubHttp
) -> None:
    before_the_call = datetime.now(timezone.utc).replace(microsecond=0)
    client.track("checkout-completed")
    after_the_call = datetime.now(timezone.utc)
    time.sleep(0.01)

    entries = entries_sent_on_close(client, http)

    happened_at = datetime.fromisoformat(entries[0]["happenedAt"].replace("Z", "+00:00"))
    assert before_the_call <= happened_at <= after_the_call
    assert entries[0]["happenedAt"].endswith("Z")


def test_sends_an_event_tracked_without_a_context_with_no_context_kind_or_identifier_and_logs_nothing(
    client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
) -> None:
    client.track("nightly-import-finished")

    entries = entries_sent_on_close(client, http)

    assert [without_the_time(entry) for entry in entries] == [{"name": "nightly-import-finished"}]
    assert logger.messages("warning") == []
    assert logger.messages("error") == []


def test_sends_an_event_for_a_context_without_an_id_with_no_context_kind_or_identifier_and_logs_nothing(
    client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
) -> None:
    client.track("checkout-completed", Context(kind="organization", name="Acme"))

    entries = entries_sent_on_close(client, http)

    assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]
    assert logger.messages("warning") == []
    assert logger.messages("error") == []


def test_sends_the_kind_of_the_context_an_event_was_tracked_for(
    client: _ConfigDirectorClient, http: StubHttp
) -> None:
    client.track("seat-added", Context(id="acme", kind="organization"))

    entries = entries_sent_on_close(client, http)

    assert entries[0]["contextKind"] == "organization"
    assert entries[0]["contextIdentifier"] == "acme"


def test_withholds_the_identifier_of_an_anonymous_context_from_the_event_tracked_for_it(
    client: _ConfigDirectorClient, http: StubHttp
) -> None:
    client.track("checkout-completed", Context(id="visitor-7", anonymous=True))

    entries = entries_sent_on_close(client, http)

    assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]


def test_logs_the_invalid_kind_of_a_context_as_evaluations_do_and_sends_the_event_without_a_context(
    client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
) -> None:
    client.track("checkout-completed", Context(id="acme", kind="Tenant"))

    entries = entries_sent_on_close(client, http)

    assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]
    errors = logger.messages("error")
    assert len(errors) == 1
    assert "'Tenant'" in errors[0]


def test_sends_the_event_in_the_report_that_carries_the_invalid_kind_of_its_context(
    client: _ConfigDirectorClient, http: StubHttp
) -> None:
    client.track("checkout-completed", Context(id="acme", kind="Tenant"))

    client.close()

    assert len(http.calls) == 1
    assert http.payload["discreteEvents"]["trackedEvents"][0]["name"] == "checkout-completed"
    assert http.payload["aggregatedEvents"]["invalidContext"][0]["event"]["kindSample"] == "Tenant"


class TestEventNames:
    def test_sends_an_event_whose_name_has_150_characters(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("n" * 150)

        entries = entries_sent_on_close(client, http)

        assert [entry["name"] for entry in entries] == ["n" * 150]
        assert logger.messages("warning") == []

    def test_counts_a_character_outside_the_basic_plane_as_one_character_of_the_name(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("😀" * 150)

        entries = entries_sent_on_close(client, http)

        assert len(entries) == 1
        assert logger.messages("warning") == []

    def test_does_not_send_an_event_whose_name_has_151_characters_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("n" * 151)
        client.track("checkout-completed")

        entries = entries_sent_on_close(client, http)

        assert [entry["name"] for entry in entries] == ["checkout-completed"]
        assert len(logger.messages("warning")) == 1

    def test_does_not_send_an_event_whose_name_is_empty_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("")
        client.track("checkout-completed")

        entries = entries_sent_on_close(client, http)

        assert [entry["name"] for entry in entries] == ["checkout-completed"]
        assert len(logger.messages("warning")) == 1

    def test_does_not_send_an_event_whose_name_is_not_a_string_without_raising(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track(cast(str, ["checkout-completed"]))
        client.track("checkout-completed")

        entries = entries_sent_on_close(client, http)

        assert [entry["name"] for entry in entries] == ["checkout-completed"]
        assert len(logger.messages("warning")) == 1


class TestWarnings:
    def test_logs_a_repeated_cause_once_until_the_telemetry_batch_is_sent_and_again_in_the_following_batch(
        self, client: _ConfigDirectorClient, reporting: ReportingTelemetry, logger: RecordingLogger
    ) -> None:
        client.track("")
        client.track("")
        warning_count_before_the_batch = len(logger.messages("warning"))

        reporting.last.flush()
        client.track("")

        assert warning_count_before_the_batch == 1
        assert len(logger.messages("warning")) == 2


class TestValues:
    def test_sends_a_float_with_every_digit_it_was_given(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        client.track("checkout-completed", value=1234567.891)

        assert value_as_written_on_close(client, http) == "1234567.891"

    def test_sends_a_whole_number(self, client: _ConfigDirectorClient, http: StubHttp) -> None:
        client.track("seats-added", value=3)

        assert value_as_written_on_close(client, http) == "3"

    def test_sends_a_value_of_zero(self, client: _ConfigDirectorClient, http: StubHttp) -> None:
        client.track("checkout-completed", value=0)

        assert value_as_written_on_close(client, http) == "0"

    def test_sends_a_decimal_as_it_was_written(self, client: _ConfigDirectorClient, http: StubHttp) -> None:
        client.track("checkout-completed", value=Decimal("49.90"))

        assert value_as_written_on_close(client, http) == "49.90"

    def test_sends_a_decimal_with_more_digits_than_a_float_holds_without_rounding_it(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        client.track("checkout-completed", value=Decimal("1234567890.12345678901234567890"))

        assert value_as_written_on_close(client, http) == "1234567890.12345678901234567890"

    def test_sends_a_decimal_with_an_exponent_as_a_json_number(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        client.track("checkout-completed", value=Decimal("1E+3"))

        client.close()

        assert http.payload["discreteEvents"]["trackedEvents"][0]["value"] == 1000

    def test_leaves_out_a_value_that_is_not_a_number_sends_the_event_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", Context(id="user-1"), value=float("nan"), details={"plan": "pro"})

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [
            {
                "name": "checkout-completed",
                "contextKind": "user",
                "contextIdentifier": "user-1",
                "details": {"plan": "pro"},
            }
        ]
        assert len(logger.messages("warning")) == 1

    def test_leaves_out_an_infinite_value_sends_the_event_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", value=float("inf"))

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]
        assert len(logger.messages("warning")) == 1

    def test_leaves_out_a_decimal_that_is_not_a_number_sends_the_event_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", value=Decimal("NaN"))

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]
        assert len(logger.messages("warning")) == 1

    def test_leaves_out_an_infinite_decimal_sends_the_event_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", value=Decimal("Infinity"))

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]
        assert len(logger.messages("warning")) == 1

    def test_leaves_out_a_boolean_value_sends_the_event_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", value=True)

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]
        assert len(logger.messages("warning")) == 1

    def test_leaves_out_a_value_of_false_sends_the_event_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", value=False)

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]
        assert len(logger.messages("warning")) == 1

    def test_leaves_out_a_whole_number_too_long_to_write_sends_the_event_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", value=10**5_000)

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]
        assert len(logger.messages("warning")) == 1

    def test_leaves_out_a_string_value_sends_the_event_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", value=cast(float, "49.90"))

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]
        assert len(logger.messages("warning")) == 1


def details_with_keys(count: int) -> dict[str, int]:
    return {f"key-{number}": number for number in range(1, count + 1)}


class TestDetails:
    def test_sends_details_with_20_top_level_keys(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", details=details_with_keys(20))

        entries = entries_sent_on_close(client, http)

        assert len(entries[0]["details"]) == 20
        assert logger.messages("warning") == []

    def test_leaves_out_details_with_21_top_level_keys_sends_the_event_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", value=49.9, details=details_with_keys(21))

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [
            {"name": "checkout-completed", "value": 49.9}
        ]
        assert len(logger.messages("warning")) == 1

    def test_sends_details_of_exactly_1024_bytes_as_json(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", details={"note": "a" * 1_013})

        entries = entries_sent_on_close(client, http)

        assert entries[0]["details"] == {"note": "a" * 1_013}
        assert logger.messages("warning") == []

    def test_leaves_out_details_of_1025_bytes_as_json_sends_the_event_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", details={"note": "a" * 1_014})

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]
        assert len(logger.messages("warning")) == 1

    def test_sends_details_in_the_same_bytes_they_were_measured_in(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        client.track("checkout-completed", details={"plan": "pro", "seats": 3, "note": "é"})

        client.close()

        assert '"details":{"plan":"pro","seats":3,"note":"é"}'.encode() in http.calls[-1].body

    def test_sends_506_two_byte_characters_which_are_within_1024_bytes_as_json(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", details={"note": "é" * 506})

        entries = entries_sent_on_close(client, http)

        assert entries[0]["details"] == {"note": "é" * 506}
        assert logger.messages("warning") == []

    def test_measures_details_in_bytes_so_507_two_byte_characters_are_left_out(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", details={"note": "é" * 507})

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]
        assert len(logger.messages("warning")) == 1

    def test_leaves_out_details_that_cannot_be_written_as_json_without_raising(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        circular: dict[str, Any] = {}
        circular["self"] = circular

        client.track("checkout-completed", details=circular)

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]
        assert len(logger.messages("warning")) == 1

    def test_leaves_out_details_that_are_a_list_rather_than_an_object(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", details=cast(dict[str, Any], ["pro"]))

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]
        assert len(logger.messages("warning")) == 1

    def test_sends_a_datetime_inside_details_as_iso_text_and_logs_no_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("trial-started", details={"ends_at": datetime(2026, 12, 1, tzinfo=timezone.utc)})

        client.close()

        assert b'"details":{"ends_at":"2026-12-01T00:00:00+00:00"}' in http.calls[-1].body
        assert logger.messages("warning") == []

    def test_sends_a_datetime_nested_in_a_mapping_as_text(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        client.track(
            "trial-started",
            details={"trial": {"ends_at": datetime(2026, 12, 1, tzinfo=timezone.utc)}},
        )

        entries = entries_sent_on_close(client, http)

        assert entries[0]["details"] == {"trial": {"ends_at": "2026-12-01T00:00:00+00:00"}}

    def test_sends_a_datetime_nested_in_a_list_as_text(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        client.track(
            "reminders-scheduled",
            details={"reminders": [datetime(2026, 12, 1, tzinfo=timezone.utc)]},
        )

        entries = entries_sent_on_close(client, http)

        assert entries[0]["details"] == {"reminders": ["2026-12-01T00:00:00+00:00"]}

    def test_sends_a_datetime_with_the_offset_it_has(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        ends_at = datetime(2026, 12, 1, 9, 30, tzinfo=timezone(timedelta(hours=-5)))

        client.track("trial-started", details={"ends_at": ends_at})

        entries = entries_sent_on_close(client, http)

        assert entries[0]["details"] == {"ends_at": "2026-12-01T09:30:00-05:00"}

    def test_sends_a_datetime_without_an_offset_as_text_without_one(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        client.track("trial-started", details={"ends_at": datetime(2026, 12, 1, 9, 30)})

        entries = entries_sent_on_close(client, http)

        assert entries[0]["details"] == {"ends_at": "2026-12-01T09:30:00"}

    def test_sends_details_holding_a_datetime_at_exactly_1024_bytes_measured_on_the_text(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track(
            "trial-started",
            details={"note": "a" * 975, "ends_at": datetime(2026, 12, 1, tzinfo=timezone.utc)},
        )

        entries = entries_sent_on_close(client, http)

        assert entries[0]["details"] == {"note": "a" * 975, "ends_at": "2026-12-01T00:00:00+00:00"}
        assert logger.messages("warning") == []

    def test_leaves_out_details_a_datetime_takes_to_1025_bytes_measured_on_the_text(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track(
            "trial-started",
            details={"note": "a" * 976, "ends_at": datetime(2026, 12, 1, tzinfo=timezone.utc)},
        )

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [{"name": "trial-started"}]
        assert len(logger.messages("warning")) == 1

    def test_leaves_out_details_holding_a_plain_date_sends_the_event_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        details = cast(dict[str, Any], {"ends_on": date(2026, 12, 1)})

        client.track("trial-started", details=details)

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [{"name": "trial-started"}]
        assert len(logger.messages("warning")) == 1

    def test_leaves_out_details_holding_a_decimal_sends_the_event_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        details = cast(dict[str, Any], {"tax": Decimal("4.90")})

        client.track("checkout-completed", details=details)

        entries = entries_sent_on_close(client, http)

        assert [without_the_time(entry) for entry in entries] == [{"name": "checkout-completed"}]
        assert len(logger.messages("warning")) == 1

    def test_sends_a_number_that_is_not_finite_inside_details_as_null(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.track("checkout-completed", details={"ratio": float("nan"), "plan": "pro"})

        entries = entries_sent_on_close(client, http)

        assert entries[0]["details"] == {"ratio": None, "plan": "pro"}
        assert logger.messages("warning") == []

    def test_sends_details_held_in_any_mapping_and_sequence(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        client.track(
            "checkout-completed",
            details=MappingProxyType({"plan": "pro", "skus": ("book", "pen")}),
        )

        entries = entries_sent_on_close(client, http)

        assert entries[0]["details"] == {"plan": "pro", "skus": ["book", "pen"]}

    def test_sends_the_details_as_they_were_when_the_event_was_tracked(
        self, client: _ConfigDirectorClient, http: StubHttp
    ) -> None:
        details: dict[str, Any] = {"plan": "pro", "items": [{"sku": "book"}]}

        client.track("checkout-completed", details=details)
        details["plan"] = "enterprise"
        details["items"][0]["sku"] = "pen"

        entries = entries_sent_on_close(client, http)

        assert entries[0]["details"] == {"plan": "pro", "items": [{"sku": "book"}]}


def track_events(client: _ConfigDirectorClient, count: int) -> None:
    for number in range(1, count + 1):
        client.track(f"event-{number}")


class TestTheLimitOfOneThousandEventsPerTelemetryBatch:
    def test_sends_1000_events_tracked_before_a_batch_is_sent(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        track_events(client, 1_000)

        entries = entries_sent_on_close(client, http)

        assert len(entries) == 1_000
        assert logger.messages("warning") == []

    def test_does_not_send_the_1001st_event_tracked_before_a_batch_is_sent_and_logs_a_warning(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        track_events(client, 1_001)

        entries = entries_sent_on_close(client, http)

        assert len(entries) == 1_000
        assert entries[0]["name"] == "event-1"
        assert entries[999]["name"] == "event-1000"
        assert len(logger.messages("warning")) == 1

    def test_logs_one_warning_however_many_events_go_beyond_the_limit_of_one_batch(
        self, client: _ConfigDirectorClient, logger: RecordingLogger
    ) -> None:
        track_events(client, 1_003)

        assert len(logger.messages("warning")) == 1

    def test_logs_only_the_warning_about_the_limit_for_an_event_beyond_it_whose_value_would_be_left_out(
        self, client: _ConfigDirectorClient, logger: RecordingLogger
    ) -> None:
        track_events(client, 1_000)

        client.track("checkout-completed", value=float("nan"))

        assert len(logger.messages("warning")) == 1

    def test_sends_events_tracked_after_a_full_batch_was_sent_on_the_following_batch(
        self, client: _ConfigDirectorClient, reporting: ReportingTelemetry, http: StubHttp
    ) -> None:
        track_events(client, 1_001)
        reporting.last.flush()

        client.track("checkout-completed")
        reporting.last.flush()

        assert len(http.calls) == 2
        assert [entry["name"] for entry in http.payload["discreteEvents"]["trackedEvents"]] == [
            "checkout-completed"
        ]


def test_logs_each_cause_of_one_batch_separately(
    client: _ConfigDirectorClient, logger: RecordingLogger
) -> None:
    client.track("")
    client.track("checkout-completed", value=float("nan"))
    client.track("checkout-completed", details=cast(dict[str, Any], ["pro"]))

    assert len(logger.messages("warning")) == 3


class UnreadableContext:
    @property
    def kind(self) -> str:
        raise RuntimeError("The session is gone")


def test_does_not_raise_and_logs_a_warning_when_the_context_cannot_be_read(
    client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
) -> None:
    client.track("checkout-completed", cast(Context, UnreadableContext()))
    client.track("nightly-import-finished")

    entries = entries_sent_on_close(client, http)

    assert [entry["name"] for entry in entries] == ["nightly-import-finished"]
    assert len(logger.messages("warning")) == 1


def test_keeps_reporting_tracked_events_after_a_report_too_large_for_configdirector(
    client: _ConfigDirectorClient, reporting: ReportingTelemetry, http: StubHttp
) -> None:
    http.status = 413
    client.track("too-large")
    reporting.last.flush()

    http.status = 204
    client.track("checkout-completed")
    reporting.last.flush()

    assert [entry["name"] for entry in http.payload["discreteEvents"]["trackedEvents"]] == [
        "checkout-completed"
    ]


class TestAClientThatSendsNoTelemetry:
    @pytest.fixture
    def offline_client(self, logger: RecordingLogger) -> Iterator[_ConfigDirectorClient]:
        client = _ConfigDirectorClient(None, connection=ConnectionOptions(mode="offline"), logger=logger)
        client.initialize()
        yield client
        client.close()

    def test_logs_no_warning_for_an_event_tracked_in_offline_mode_that_would_not_be_reported(
        self, offline_client: _ConfigDirectorClient, logger: RecordingLogger
    ) -> None:
        offline_client.track("")

        assert logger.messages("warning") == []

    def test_logs_no_error_for_an_event_tracked_in_offline_mode_for_a_context_with_an_invalid_kind(
        self, offline_client: _ConfigDirectorClient, logger: RecordingLogger
    ) -> None:
        offline_client.track("checkout-completed", Context(id="acme", kind="Tenant"))

        assert logger.messages("error") == []

    def test_sends_nothing_and_logs_nothing_for_an_event_tracked_after_close(
        self, client: _ConfigDirectorClient, http: StubHttp, logger: RecordingLogger
    ) -> None:
        client.close()

        client.track("")
        client.track("checkout-completed", Context(id="acme", kind="Tenant"))

        assert http.calls == []
        assert logger.messages("warning") == []
        assert logger.messages("error") == []

    def test_logs_no_warning_for_an_event_tracked_after_configdirector_refused_the_sdk_key(
        self,
        client: _ConfigDirectorClient,
        reporting: ReportingTelemetry,
        http: StubHttp,
        logger: RecordingLogger,
    ) -> None:
        http.status = 401
        client.track("checkout-completed")
        reporting.last.flush()
        warnings_before_the_event = list(logger.messages("warning"))

        client.track("")

        assert logger.messages("warning") == warnings_before_the_event
