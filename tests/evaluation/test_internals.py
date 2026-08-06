from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from configdirector._evaluation._json_pointer import find_by_pointer
from configdirector._evaluation._json_value import to_json_string
from configdirector._evaluation.date_comparison import compare_date


class TestJsonPointer:
    @pytest.mark.parametrize(
        ("pointer", "document", "expected"),
        [
            ("/a", {"a": 1}, 1),
            ("/a/b", {"a": {"b": "deep"}}, "deep"),
            ("/a/b/c", {"a": {"b": {"c": None}}}, None),
            ("/tags/0", {"tags": ["x", "y"]}, "x"),
            ("/tags/1", {"tags": ["x", "y"]}, "y"),
            ("/a~1b", {"a/b": "slash"}, "slash"),
            ("/a~0b", {"a~b": "tilde"}, "tilde"),
            ("/a~01", {"a~1": "literal"}, "literal"),
            ("/", {"": "empty key"}, "empty key"),
        ],
    )
    def test_resolves(self, pointer: str, document: Any, expected: Any) -> None:
        assert find_by_pointer(pointer, document) == expected

    @pytest.mark.parametrize(
        ("pointer", "document"),
        [
            ("a", {"a": 1}),  # no leading slash is not a pointer
            ("", {"a": 1}),  # the whole-document pointer is never used for traits
            ("/missing", {"a": 1}),
            ("/a/b", {"a": "scalar"}),  # cannot step into a string
            ("/a/b", {}),
            ("/a", None),
            ("/tags/9", {"tags": ["x"]}),  # index out of range
            ("/tags/-1", {"tags": ["x"]}),  # negative indexes must not wrap around
            ("/tags/x", {"tags": ["x"]}),  # non-numeric index
        ],
    )
    def test_returns_none_when_it_cannot_resolve(self, pointer: str, document: Any) -> None:
        assert find_by_pointer(pointer, document) is None


class TestToJsonString:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (True, "true"),
            (False, "false"),
            ("already text", "already text"),
            (26, "26"),
            (-3, "-3"),
            (26.0, "26"),  # JSON has one number type, so a whole float renders without ".0"
            (1.5, "1.5"),
            (-0.25, "-0.25"),
            (float("nan"), "NaN"),
            (float("inf"), "Infinity"),
            (float("-inf"), "-Infinity"),
        ],
    )
    def test_renders_like_javascript(self, value: Any, expected: str) -> None:
        assert to_json_string(value) == expected


class TestDateParsing:
    @pytest.mark.parametrize(
        ("value", "is_before_the_target"),
        [
            ("2026-01-28", True),
            ("2026-01", True),
            ("2026", True),
            ("2026-01-28T01:24:59Z", True),
            ("2026-01-28T01:24:59.999Z", True),
            ("2026-01-28T03:24:59+02:00", True),  # 01:24:59Z once the offset is applied
            ("2026-01-28T01:25:00.001Z", False),
            ("2027-01-28", False),
        ],
    )
    def test_parses_the_supported_formats(self, value: str, is_before_the_target: bool) -> None:
        result = compare_date(value, "is before", ["2026-01-28T01:25:00.000Z"])

        assert result is is_before_the_target

    @pytest.mark.parametrize(
        "value", ["garbage", "2026-13-01", "2026-01-32", "28/01/2026", "", "2026-01-28T25:00Z"]
    )
    def test_an_unparseable_date_never_matches(self, value: str) -> None:
        target = ["2026-01-28T01:25:00.000Z"]

        assert compare_date(value, "is before", target) is False
        assert compare_date(value, "is after", target) is False

    def test_an_unparseable_target_never_matches(self) -> None:
        assert compare_date("2026-01-28", "is before", ["garbage"]) is False

    def test_a_date_time_without_an_offset_is_read_as_utc(self) -> None:
        target = "2026-01-28T01:25:00.000Z"

        assert compare_date("2026-01-28T01:24:59", "is before", [target]) is True
        assert compare_date("2026-01-28T01:25:01", "is before", [target]) is False
        assert compare_date("2026-01-28T01:25:00", "is before", [target]) is False
        assert compare_date("2026-01-28T01:25:00", "is after", [target]) is False

    def test_a_date_only_value_is_read_as_utc(self) -> None:
        # Just after midnight UTC is "after" the date itself, whatever the machine's timezone.
        just_after_midnight = datetime(2026, 1, 28, 0, 0, 1, tzinfo=timezone.utc).isoformat()

        assert compare_date(just_after_midnight, "is after", ["2026-01-28"]) is True

    def test_an_unknown_operator_never_matches(self) -> None:
        assert compare_date("2026-01-28", "is roughly", ["2026-01-29"]) is False
