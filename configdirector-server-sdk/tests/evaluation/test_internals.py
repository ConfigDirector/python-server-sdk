from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from configdirector._evaluation._json_pointer import find_by_pointer
from configdirector._evaluation._json_value import to_json_string
from configdirector._evaluation.date_comparison import compare_date

ELEVEN_ELEMENTS = {
    "list": ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
}


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

    def test_a_lone_tilde_invalidates_the_pointer(self) -> None:
        assert find_by_pointer("/~", {"~": "found"}) is None

    def test_a_tilde_followed_by_two_invalidates_the_pointer(self) -> None:
        assert find_by_pointer("/~2", {"~2": "found"}) is None

    def test_a_tilde_followed_by_a_letter_invalidates_the_pointer(self) -> None:
        assert find_by_pointer("/~a", {"~a": "found"}) is None

    def test_a_trailing_tilde_invalidates_the_pointer(self) -> None:
        assert find_by_pointer("/a~", {"a~": "found"}) is None

    def test_a_tilde_followed_by_a_tilde_invalidates_the_pointer(self) -> None:
        assert find_by_pointer("/~~", {"~~": "found"}) is None

    def test_an_invalid_escape_before_a_valid_one_invalidates_the_pointer(self) -> None:
        assert find_by_pointer("/~~1", {"~/": "found"}) is None

    def test_an_invalid_escape_after_a_valid_one_invalidates_the_pointer(self) -> None:
        assert find_by_pointer("/~0~2", {"~~2": "found"}) is None

    def test_an_invalid_escape_in_the_first_of_two_tokens_invalidates_the_pointer(self) -> None:
        assert find_by_pointer("/a~/b", {"a~": {"b": "found"}}) is None

    def test_an_invalid_escape_in_the_last_of_two_tokens_invalidates_the_pointer(self) -> None:
        assert find_by_pointer("/a/~2", {"a": {"~2": "found"}}) is None

    def test_an_invalid_escape_invalidates_the_pointer_even_when_later_tokens_resolve(self) -> None:
        assert find_by_pointer("/~2/b", {"~2": {"b": "found"}}) is None

    def test_tilde_zero_decodes_to_a_tilde(self) -> None:
        assert find_by_pointer("/~0", {"~": "found"}) == "found"

    def test_tilde_one_decodes_to_a_slash(self) -> None:
        assert find_by_pointer("/~1", {"/": "found"}) == "found"

    def test_tilde_zero_one_decodes_to_a_tilde_and_a_one(self) -> None:
        assert find_by_pointer("/~01", {"~1": "found", "/": "wrong"}) == "found"

    def test_tilde_one_zero_decodes_to_a_slash_and_a_zero(self) -> None:
        assert find_by_pointer("/~10", {"/0": "found", "~0": "wrong"}) == "found"

    def test_repeated_tilde_zero_escapes_decode_to_tildes(self) -> None:
        assert find_by_pointer("/~0~0", {"~~": "found"}) == "found"

    def test_repeated_tilde_one_escapes_decode_to_slashes(self) -> None:
        assert find_by_pointer("/~1~1", {"//": "found"}) == "found"

    def test_mixed_escapes_decode_in_place(self) -> None:
        assert find_by_pointer("/a~0b~1c", {"a~b/c": "found"}) == "found"

    def test_escapes_decode_in_every_token(self) -> None:
        assert find_by_pointer("/~1/~0", {"/": {"~": "found"}}) == "found"

    def test_percent_encoding_is_not_decoded(self) -> None:
        assert find_by_pointer("/%25", {"%25": "found", "%": "wrong"}) == "found"

    def test_an_array_index_of_zero_selects_the_first_element(self) -> None:
        assert find_by_pointer("/list/0", ELEVEN_ELEMENTS) == "zero"

    def test_a_multi_digit_array_index_selects_its_element(self) -> None:
        assert find_by_pointer("/list/10", ELEVEN_ELEMENTS) == "ten"

    def test_an_array_index_equal_to_the_length_selects_nothing(self) -> None:
        assert find_by_pointer("/list/11", ELEVEN_ELEMENTS) is None

    def test_an_array_index_with_a_leading_zero_selects_nothing(self) -> None:
        assert find_by_pointer("/list/01", ELEVEN_ELEMENTS) is None

    def test_a_double_zero_array_index_selects_nothing(self) -> None:
        assert find_by_pointer("/list/00", ELEVEN_ELEMENTS) is None

    def test_a_multi_digit_array_index_with_a_leading_zero_selects_nothing(self) -> None:
        assert find_by_pointer("/list/010", ELEVEN_ELEMENTS) is None

    def test_an_array_index_with_a_plus_sign_selects_nothing(self) -> None:
        assert find_by_pointer("/list/+1", ELEVEN_ELEMENTS) is None

    def test_a_negative_zero_array_index_selects_nothing(self) -> None:
        assert find_by_pointer("/list/-0", ELEVEN_ELEMENTS) is None

    def test_an_array_index_with_a_leading_space_selects_nothing(self) -> None:
        assert find_by_pointer("/list/ 1", ELEVEN_ELEMENTS) is None

    def test_an_array_index_with_a_trailing_space_selects_nothing(self) -> None:
        assert find_by_pointer("/list/1 ", ELEVEN_ELEMENTS) is None

    def test_an_array_index_with_a_leading_tab_selects_nothing(self) -> None:
        assert find_by_pointer("/list/\t1", ELEVEN_ELEMENTS) is None

    def test_an_array_index_with_a_trailing_newline_selects_nothing(self) -> None:
        assert find_by_pointer("/list/1\n", ELEVEN_ELEMENTS) is None

    def test_an_array_index_with_an_underscore_separator_selects_nothing(self) -> None:
        assert find_by_pointer("/list/1_0", ELEVEN_ELEMENTS) is None

    def test_an_array_index_in_arabic_indic_digits_selects_nothing(self) -> None:
        assert find_by_pointer("/list/\u0661", ELEVEN_ELEMENTS) is None

    def test_an_array_index_ending_in_a_non_ascii_digit_selects_nothing(self) -> None:
        assert find_by_pointer("/list/1\u0660", ELEVEN_ELEMENTS) is None

    def test_an_array_index_in_fullwidth_digits_selects_nothing(self) -> None:
        assert find_by_pointer("/list/\uff11", ELEVEN_ELEMENTS) is None

    def test_a_decimal_array_index_selects_nothing(self) -> None:
        assert find_by_pointer("/list/1.0", ELEVEN_ELEMENTS) is None

    def test_an_exponent_array_index_selects_nothing(self) -> None:
        assert find_by_pointer("/list/1e0", ELEVEN_ELEMENTS) is None

    def test_the_past_the_end_array_token_selects_nothing(self) -> None:
        assert find_by_pointer("/list/-", ELEVEN_ELEMENTS) is None

    def test_an_empty_array_token_selects_nothing(self) -> None:
        assert find_by_pointer("/list/", ELEVEN_ELEMENTS) is None

    def test_a_numeric_token_selects_an_object_member_by_name(self) -> None:
        assert find_by_pointer("/01", {"01": "found", "1": "wrong"}) == "found"

    def test_a_numeric_token_does_not_select_a_non_string_object_key(self) -> None:
        assert find_by_pointer("/0", {0: "wrong"}) is None

    def test_a_string_is_not_indexed_by_character(self) -> None:
        assert find_by_pointer("/text/0", {"text": "abc"}) is None

    def test_a_boolean_is_not_traversed(self) -> None:
        assert find_by_pointer("/flag/0", {"flag": True}) is None

    def test_a_number_is_not_traversed(self) -> None:
        assert find_by_pointer("/count/0", {"count": 1}) is None

    def test_a_tuple_is_not_traversed_as_an_array(self) -> None:
        assert find_by_pointer("/pair/0", {"pair": ("first", "second")}) is None


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
