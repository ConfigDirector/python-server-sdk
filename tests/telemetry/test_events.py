from __future__ import annotations

import pytest

from configdirector._telemetry.events import (
    CONFIG_VALUE_MAX_LENGTH,
    EvaluatedConfigEvent,
    TelemetryValue,
    requested_type_of,
)
from configdirector._telemetry.value_id import VALUE_ID_LENGTH, generate_value_id
from configdirector.types import ConfigType, ConfigValue


def event(**overrides: object) -> EvaluatedConfigEvent:
    arguments: dict[str, object] = {
        "key": "my-config",
        "default": "default",
        "value": "hello",
        "used_default": False,
        "reason": "found-match",
    }
    arguments.update(overrides)
    return EvaluatedConfigEvent.of(**arguments)  # type: ignore[arg-type]


class TestRequestedTypeOf:
    @pytest.mark.parametrize(
        ("default", "expected"),
        [
            ("text", "str"),
            (True, "bool"),
            (26, "int"),
            (1.5, "float"),
            ({"a": 1}, "dict"),
            ([1, 2], "list"),
        ],
    )
    def test_reports_the_python_type_name(self, default: ConfigValue, expected: str) -> None:
        assert requested_type_of(default) == expected


class TestTelemetryValue:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("hello", "hello"),
            (True, "true"),  # not Python's "True", which no other SDK would report
            (False, "false"),
            (26, "26"),
            (26.0, "26"),
            (1.5, "1.5"),
        ],
    )
    def test_reports_a_small_value_inline(self, value: ConfigValue, expected: str) -> None:
        assert TelemetryValue.of(value) == TelemetryValue(value=expected)

    def test_serializes_a_json_value_compactly(self) -> None:
        assert TelemetryValue.of({"b": 1, "a": [True]}, config_type="json") == TelemetryValue(
            value='{"b":1,"a":[true]}', type="json"
        )

    def test_treats_an_untyped_mapping_as_json(self) -> None:
        # An evaluation that found no config state has no declared type to go on.
        assert TelemetryValue.of({"a": 1}).type == "json"
        assert TelemetryValue.of([1, 2]).type == "json"

    def test_prefers_the_value_id_the_server_sent_for_a_json_value(self) -> None:
        assert TelemetryValue.of({"a": 1}, value_id="server-id", config_type="json") == TelemetryValue(
            value_id="server-id", type="json"
        )

    def test_falls_back_to_str_for_a_value_json_cannot_represent(self) -> None:
        unserializable = {"when": object()}

        reported = TelemetryValue.of(unserializable, config_type="json")

        assert reported.value == str(unserializable)
        assert reported.type == "json"

    def test_reports_an_oversized_value_by_the_id_the_server_sent(self) -> None:
        long_value = "x" * (CONFIG_VALUE_MAX_LENGTH + 1)

        assert TelemetryValue.of(long_value, value_id="server-id") == TelemetryValue(value_id="server-id")

    def test_keeps_an_oversized_value_when_the_server_sent_no_id(self) -> None:
        # It is compacted into an ID at flush time instead; the hashing does not belong on the
        # caller's thread.
        long_value = "x" * (CONFIG_VALUE_MAX_LENGTH + 1)

        assert TelemetryValue.of(long_value) == TelemetryValue(value=long_value)


class TestTelemetryValueCompacted:
    def test_leaves_a_small_value_inline(self) -> None:
        assert TelemetryValue(value="hello").compacted() == TelemetryValue(value="hello")

    def test_keeps_a_value_of_exactly_the_maximum_length_inline(self) -> None:
        at_limit = "x" * CONFIG_VALUE_MAX_LENGTH

        assert TelemetryValue(value=at_limit).compacted() == TelemetryValue(value=at_limit)

    def test_replaces_an_oversized_value_with_its_id(self) -> None:
        long_value = "x" * (CONFIG_VALUE_MAX_LENGTH + 1)

        assert TelemetryValue(value=long_value).compacted() == TelemetryValue(
            value_id=generate_value_id(long_value)
        )

    def test_replaces_every_json_document_with_its_id(self) -> None:
        assert TelemetryValue(value='{"a":1}', type="json").compacted() == TelemetryValue(
            value_id=generate_value_id('{"a":1}')
        )

    def test_keeps_an_id_it_already_has(self) -> None:
        assert TelemetryValue(value_id="server-id", type="json").compacted() == TelemetryValue(
            value_id="server-id"
        )

    def test_drops_the_declared_type(self) -> None:
        # The type is only carried so that compaction can recognise a JSON document; the server
        # reads it from the event instead.
        assert TelemetryValue(value='{"a":1}', type="json").compacted().type is None
        assert TelemetryValue(value="hello", type="string").compacted().type is None

    def test_leaves_an_empty_value_alone(self) -> None:
        assert TelemetryValue(value="").compacted() == TelemetryValue(value="")


class TestTelemetryValueToWire:
    def test_omits_what_was_not_set(self) -> None:
        assert TelemetryValue(value="hello").to_wire() == {"value": "hello"}
        assert TelemetryValue(value_id="an-id").to_wire() == {"valueId": "an-id"}

    def test_names_the_fields_the_way_the_server_reads_them(self) -> None:
        assert TelemetryValue(value="hello", value_id="an-id", type="json").to_wire() == {
            "value": "hello",
            "valueId": "an-id",
            "type": "json",
        }


class TestEvaluatedConfigEvent:
    def test_reports_both_values_and_the_requested_type(self) -> None:
        built = event(default=False, value=True, config_type="boolean")

        assert built.default_value == TelemetryValue(value="false")
        assert built.evaluated_value == TelemetryValue(value="true")
        assert built.requested_type == "bool"
        assert built.type == "boolean"

    def test_only_the_evaluated_value_carries_the_server_value_id(self) -> None:
        # A default is the caller's own literal, so the server has never seen it.
        built = event(value_id="server-id", config_type="json", default={"a": 1}, value={"b": 2})

        assert built.evaluated_value == TelemetryValue(value_id="server-id", type="json")
        assert built.default_value == TelemetryValue(value='{"a":1}', type="json")
        assert built.evaluated_value_id == "server-id"

    def test_identical_evaluations_compare_equal(self) -> None:
        # Equality is what decides which events collapse together when they are aggregated.
        assert event() == event()
        assert hash(event()) == hash(event())

    @pytest.mark.parametrize(
        "difference",
        [
            {"key": "other-config"},
            {"value": "other"},
            {"default": "other"},
            {"used_default": True},
            {"reason": "value-missing"},
            {"context_id": "user-1"},
            {"config_type": "enum"},
        ],
    )
    def test_events_that_differ_do_not_compare_equal(self, difference: dict[str, object]) -> None:
        assert event(**difference) != event()

    def test_compacting_reduces_both_values(self) -> None:
        long_value = "x" * (CONFIG_VALUE_MAX_LENGTH + 1)

        compacted = event(default=long_value, value=long_value).compacted()

        assert compacted.default_value.value_id is not None
        assert compacted.evaluated_value.value_id is not None

    def test_compacting_leaves_the_rest_of_the_event_alone(self) -> None:
        built = event(context_id="user-1", config_type="string")

        compacted = built.compacted()

        assert compacted.key == built.key
        assert compacted.context_id == "user-1"
        assert compacted.type == "string"
        assert compacted.requested_type == built.requested_type

    def test_writes_the_field_names_the_server_reads(self) -> None:
        wire = event(context_id="user-1", config_type="string").compacted().to_wire()

        assert wire == {
            "contextId": "user-1",
            "key": "my-config",
            "type": "string",
            "defaultValue": {"value": "default"},
            "requestedType": "str",
            "evaluatedValue": {"value": "hello"},
            "usedDefault": False,
            "evaluationReason": "found-match",
        }

    def test_omits_the_context_and_type_when_there_are_none(self) -> None:
        wire = event().compacted().to_wire()

        assert "contextId" not in wire
        assert "type" not in wire
        assert "evaluatedValueId" not in wire

    def test_passes_through_the_value_id_the_server_sent(self) -> None:
        wire = event(value_id="server-id").compacted().to_wire()

        assert wire["evaluatedValueId"] == "server-id"

    @pytest.mark.parametrize("config_type", ["json", None])
    def test_a_json_value_is_reported_by_id(self, config_type: ConfigType | None) -> None:
        wire = event(default={"a": 1}, value={"b": 2}, config_type=config_type).compacted().to_wire()

        assert len(wire["evaluatedValue"]["valueId"]) == VALUE_ID_LENGTH
        assert len(wire["defaultValue"]["valueId"]) == VALUE_ID_LENGTH
        assert wire["evaluatedValue"]["valueId"] != wire["defaultValue"]["valueId"]
