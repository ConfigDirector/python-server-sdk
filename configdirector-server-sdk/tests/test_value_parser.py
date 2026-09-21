from __future__ import annotations

from typing import Any

import pytest

from configdirector._value_parser import parse_config_value
from configdirector.types import ConfigState, ConfigType


def state(value: str | None, *, type: ConfigType = "string", value_id: str | None = "v-1") -> ConfigState:
    return ConfigState(id="cfg-1", key="a-key", type=type, value=value, value_id=value_id)


class TestMissingValue:
    @pytest.mark.parametrize("value", [None, ""])
    def test_falls_back_when_the_config_has_no_value(self, value: str | None) -> None:
        result = parse_config_value(state(value), "fallback")

        assert result.value == "fallback"
        assert result.used_default is True
        assert result.reason == "value-missing"
        assert result.value_id is None


class TestStrings:
    def test_returns_the_stored_value(self) -> None:
        result = parse_config_value(state("hello"), "fallback")

        assert result.value == "hello"
        assert result.used_default is False
        assert result.reason == "found-match"
        assert result.value_id == "v-1"

    def test_a_string_default_takes_json_as_raw_text(self) -> None:
        assert parse_config_value(state('{"a":1}', type="json"), "fallback").value == '{"a":1}'


class TestBooleans:
    @pytest.mark.parametrize(("stored", "expected"), [("true", True), ("false", False), ("TRUE", True)])
    def test_parses_a_boolean(self, stored: str, expected: bool) -> None:
        result = parse_config_value(state(stored, type="boolean"), False)

        assert result.value is expected
        assert result.reason == "found-match"

    @pytest.mark.parametrize("stored", ["yes", "1", "0", "maybe"])
    def test_falls_back_on_a_value_that_is_not_a_boolean(self, stored: str) -> None:
        result = parse_config_value(state(stored, type="boolean"), True)

        assert result.value is True
        assert result.used_default is True
        assert result.reason == "invalid-boolean"

    def test_a_boolean_default_is_not_treated_as_an_integer(self) -> None:
        # bool subclasses int in Python, so the order of the checks is what makes this work.
        result = parse_config_value(state("26", type="integer"), True)

        assert result.reason == "invalid-boolean"


class TestIntegers:
    @pytest.mark.parametrize(("stored", "expected"), [("26", 26), ("-4", -4), ("26.0", 26)])
    def test_parses_an_integer(self, stored: str, expected: int) -> None:
        result = parse_config_value(state(stored, type="integer"), 0)

        assert result.value == expected
        assert result.reason == "found-match"

    @pytest.mark.parametrize("stored", ["26abc", "abc", "1_000", " 26", "26.5", "١٢", "Infinity"])
    def test_falls_back_on_a_value_that_is_not_a_whole_number(self, stored: str) -> None:
        result = parse_config_value(state(stored, type="integer"), 7)

        assert result.value == 7
        assert result.used_default is True
        assert result.reason == "invalid-number"


class TestFloats:
    @pytest.mark.parametrize(("stored", "expected"), [("3.5", 3.5), ("26", 26.0), ("1e3", 1000.0)])
    def test_parses_a_float(self, stored: str, expected: float) -> None:
        result = parse_config_value(state(stored, type="float"), 0.0)

        assert result.value == expected
        assert result.reason == "found-match"

    @pytest.mark.parametrize("stored", ["nan", "inf", "-Infinity", "1.2.3", "abc", "1_0"])
    def test_falls_back_on_a_value_that_is_not_a_finite_number(self, stored: str) -> None:
        result = parse_config_value(state(stored, type="float"), 1.5)

        assert result.value == 1.5
        assert result.used_default is True
        assert result.reason == "invalid-number"


class TestJson:
    @pytest.mark.parametrize(
        ("stored", "default", "expected"),
        [
            ('{"a":1}', {}, {"a": 1}),
            ("[1,2,3]", [], [1, 2, 3]),
            ('{"nested":{"b":true}}', {}, {"nested": {"b": True}}),
        ],
    )
    def test_parses_json(self, stored: str, default: Any, expected: Any) -> None:
        result = parse_config_value(state(stored, type="json"), default)

        assert result.value == expected
        assert result.reason == "found-match"

    def test_falls_back_on_malformed_json(self) -> None:
        result = parse_config_value(state("{not json", type="json"), {"a": 1})

        assert result.value == {"a": 1}
        assert result.used_default is True
        assert result.reason == "invalid-json"

    def test_a_structured_default_against_a_plain_string_falls_back(self) -> None:
        # The requested type drives the parse, so a string config asked for as a dict is a
        # mismatch rather than a dict-shaped surprise.
        result = parse_config_value(state("hello", type="string"), {"a": 1})

        assert result.value == {"a": 1}
        assert result.reason == "invalid-json"


class TestValueId:
    def test_a_matched_value_carries_its_value_id(self) -> None:
        assert parse_config_value(state("hello"), "fallback").value_id == "v-1"

    def test_a_default_carries_no_value_id(self) -> None:
        assert parse_config_value(state("hello"), 0).value_id is None
