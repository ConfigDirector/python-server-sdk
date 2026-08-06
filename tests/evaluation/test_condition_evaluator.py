from __future__ import annotations

from typing import Any

import pytest

from configdirector import Context, Metadata
from configdirector._evaluation import Condition, ConditionEvaluator, EvaluationContext

evaluator = ConditionEvaluator()


def ctx(**kwargs: Any) -> EvaluationContext:
    return EvaluationContext(context=Context(**kwargs))


def meta(**kwargs: Any) -> EvaluationContext:
    return EvaluationContext(metadata=Metadata(**kwargs))


def traits(value: dict[str, Any]) -> EvaluationContext:
    return EvaluationContext(context=Context(traits=value))


def condition(
    operator: str,
    targets: list[str],
    target_type: str = "text",
    attribute: str = "identifier",
    trait: str | None = None,
) -> Condition:
    return Condition(
        id="a",
        attribute=attribute,
        trait=trait,
        operator=operator,
        target_type=target_type,
        target_values=targets,
    )


class TestTextComparisonConditions:
    @pytest.mark.parametrize("operator", ["equals", "="])
    def test_evaluates_identifier_equals(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator=operator,
            target_type="text",
            target_values=["123456"],
        )

        assert evaluator.evaluate(condition, ctx(id="123456")) is True
        assert evaluator.evaluate(condition, ctx(id="123457")) is False
        assert evaluator.evaluate(condition, EvaluationContext()) is False

    @pytest.mark.parametrize("operator", ["does NOT equal", "!=", "does not equal"])
    def test_evaluates_identifier_not_equals(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator=operator,
            target_type="text",
            target_values=["123456"],
        )

        assert evaluator.evaluate(condition, ctx(id="123457")) is True
        assert evaluator.evaluate(condition, ctx()) is True
        assert evaluator.evaluate(condition, ctx(id="123456")) is False

    def test_evaluates_identifier_is_one_of(self) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator="is one of",
            target_type="text",
            target_values=["AB", "CD", "FG"],
        )

        assert evaluator.evaluate(condition, ctx(id="AB")) is True
        assert evaluator.evaluate(condition, ctx(id="CD")) is True
        assert evaluator.evaluate(condition, ctx(id="FG")) is True
        assert evaluator.evaluate(condition, ctx(id="AC")) is False
        assert evaluator.evaluate(condition, ctx(id="cd")) is False
        assert evaluator.evaluate(condition, ctx(id="ABC")) is False

    @pytest.mark.parametrize("operator", ["is NOT one of", "is not one of"])
    def test_evaluates_identifier_is_not_one_of(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator=operator,
            target_type="text",
            target_values=["AB", "CD", "FG"],
        )

        assert evaluator.evaluate(condition, ctx(id="AC")) is True
        assert evaluator.evaluate(condition, ctx(id="cd")) is True
        assert evaluator.evaluate(condition, ctx(id="")) is True
        assert evaluator.evaluate(condition, ctx()) is True
        assert evaluator.evaluate(condition, ctx(id="AB")) is False
        assert evaluator.evaluate(condition, ctx(id="CD")) is False
        assert evaluator.evaluate(condition, ctx(id="FG")) is False

    def test_evaluates_identifier_starts_with_any_of(self) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator="starts with any of",
            target_type="text",
            target_values=["A", "C", "F"],
        )

        assert evaluator.evaluate(condition, ctx(id="ABCD")) is True
        assert evaluator.evaluate(condition, ctx(id="CDE")) is True
        assert evaluator.evaluate(condition, ctx(id="FGH")) is True
        assert evaluator.evaluate(condition, ctx(id="BCDF")) is False
        assert evaluator.evaluate(condition, ctx(id="DFA")) is False
        assert evaluator.evaluate(condition, ctx(id="EACF")) is False

    @pytest.mark.parametrize("operator", ["does NOT start with any of", "does not start with any of"])
    def test_evaluates_identifier_does_not_start_with_any_of(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator=operator,
            target_type="text",
            target_values=["A", "C", "F"],
        )

        assert evaluator.evaluate(condition, ctx(id="BCDF")) is True
        assert evaluator.evaluate(condition, ctx(id="DFA")) is True
        assert evaluator.evaluate(condition, ctx(id="EACF")) is True
        assert evaluator.evaluate(condition, ctx(id="")) is True
        assert evaluator.evaluate(condition, ctx()) is True
        assert evaluator.evaluate(condition, ctx(id="ABCD")) is False
        assert evaluator.evaluate(condition, ctx(id="CDE")) is False
        assert evaluator.evaluate(condition, ctx(id="FGH")) is False

    def test_evaluates_identifier_ends_with_any_of(self) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator="ends with any of",
            target_type="text",
            target_values=["A", "C", "F"],
        )

        assert evaluator.evaluate(condition, ctx(id="123A")) is True
        assert evaluator.evaluate(condition, ctx(id="23C")) is True
        assert evaluator.evaluate(condition, ctx(id="F")) is True
        assert evaluator.evaluate(condition, ctx(id="FBCFD")) is False
        assert evaluator.evaluate(condition, ctx(id="DFAB")) is False
        assert evaluator.evaluate(condition, ctx(id="EACF1")) is False

    @pytest.mark.parametrize("operator", ["does NOT end with any of", "does not end with any of"])
    def test_evaluates_identifier_does_not_end_with_any_of(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator=operator,
            target_type="text",
            target_values=["A", "C", "F"],
        )

        assert evaluator.evaluate(condition, ctx(id="FBCFD")) is True
        assert evaluator.evaluate(condition, ctx(id="DFAB")) is True
        assert evaluator.evaluate(condition, ctx(id="EACF1")) is True
        assert evaluator.evaluate(condition, ctx(id="")) is True
        assert evaluator.evaluate(condition, ctx()) is True
        assert evaluator.evaluate(condition, ctx(id="123A")) is False
        assert evaluator.evaluate(condition, ctx(id="23C")) is False
        assert evaluator.evaluate(condition, ctx(id="F")) is False

    def test_evaluates_identifier_matches_regex(self) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator="matches regex",
            target_type="text",
            target_values=["[A-Z]"],
        )

        assert evaluator.evaluate(condition, ctx(id="ALEJANDRO")) is True
        assert evaluator.evaluate(condition, ctx(id="B")) is True
        assert evaluator.evaluate(condition, ctx(id="123456")) is False
        assert evaluator.evaluate(condition, ctx(id=".")) is False
        assert evaluator.evaluate(condition, ctx()) is False

    def test_evaluates_identifier_matches_regex_with_invalid_regex(self) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator="matches regex",
            target_type="text",
            target_values=["["],
        )

        assert evaluator.evaluate(condition, ctx(id="ALEJANDRO")) is False
        assert evaluator.evaluate(condition, ctx(id="B")) is False
        assert evaluator.evaluate(condition, ctx(id="123456")) is False
        assert evaluator.evaluate(condition, ctx(id=".")) is False

    @pytest.mark.parametrize("operator", ["does NOT match regex", "does not match regex"])
    def test_evaluates_identifier_does_not_match_regex(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator=operator,
            target_type="text",
            target_values=["[A-Z]"],
        )

        assert evaluator.evaluate(condition, ctx(id="123456")) is True
        assert evaluator.evaluate(condition, ctx(id=".")) is True
        assert evaluator.evaluate(condition, ctx()) is True
        assert evaluator.evaluate(condition, ctx(id="ALEJANDRO")) is False
        assert evaluator.evaluate(condition, ctx(id="B")) is False

    @pytest.mark.parametrize("operator", ["does NOT match regex", "does not match regex"])
    def test_evaluates_identifier_does_not_match_regex_with_invalid_regex(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator=operator,
            target_type="text",
            target_values=["["],
        )

        assert evaluator.evaluate(condition, ctx(id="ALEJANDRO")) is True
        assert evaluator.evaluate(condition, ctx(id="B")) is True
        assert evaluator.evaluate(condition, ctx(id="123456")) is True
        assert evaluator.evaluate(condition, ctx(id=".")) is True

    @pytest.mark.parametrize("operator", ["equals", "="])
    def test_evaluates_name_equals(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="name",
            trait=None,
            operator=operator,
            target_type="text",
            target_values=["John"],
        )

        assert evaluator.evaluate(condition, ctx(name="John")) is True
        assert evaluator.evaluate(condition, ctx(name="Joe")) is False
        assert evaluator.evaluate(condition, ctx(name="john")) is False

    @pytest.mark.parametrize("operator", ["equals", "="])
    def test_evaluates_app_name_equals(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="appName",
            trait=None,
            operator=operator,
            target_type="text",
            target_values=["Safari"],
        )

        assert evaluator.evaluate(condition, meta(app_name="Safari")) is True
        assert evaluator.evaluate(condition, meta(app_name="Safaris")) is False
        assert evaluator.evaluate(condition, meta(app_name="safari")) is False

    @pytest.mark.parametrize("operator", ["equals", "="])
    def test_evaluates_top_level_trait_equals(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait="/city",
            operator=operator,
            target_type="text",
            target_values=["Portland"],
        )

        assert evaluator.evaluate(condition, traits({"city": "Portland"})) is True
        assert evaluator.evaluate(condition, traits({"city": "Seattle"})) is False
        assert evaluator.evaluate(condition, traits({"City": "Portland"})) is False
        assert evaluator.evaluate(condition, traits({"location": "Portland"})) is False
        assert evaluator.evaluate(condition, traits({})) is False

    @pytest.mark.parametrize("operator", ["equals", "="])
    def test_evaluates_nested_trait_equals(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait="/location/city",
            operator=operator,
            target_type="text",
            target_values=["Portland"],
        )

        assert evaluator.evaluate(condition, traits({"location": {"city": "Portland"}})) is True
        assert evaluator.evaluate(condition, traits({"location": {"city": "Seattle"}})) is False
        assert evaluator.evaluate(condition, traits({"location": {"City": "Portland"}})) is False
        assert evaluator.evaluate(condition, traits({"location": "Portland"})) is False
        assert evaluator.evaluate(condition, traits({"city": "Portland"})) is False
        assert evaluator.evaluate(condition, traits({})) is False

    class TestAbsentValuesAreComparedAsEmptyText:
        """a missing attribute resolves to "", it is not a special case per operator."""

        def test_equals_empty_string_matches_a_missing_identifier(self) -> None:
            assert evaluator.evaluate(condition("=", [""]), EvaluationContext()) is True

        def test_does_not_equal_empty_string_does_not_match(self) -> None:
            assert evaluator.evaluate(condition("!=", [""]), EvaluationContext()) is False

        def test_is_one_of_including_empty_matches(self) -> None:
            assert evaluator.evaluate(condition("is one of", ["a", ""]), EvaluationContext()) is True

        def test_starts_with_empty_string_matches(self) -> None:
            assert evaluator.evaluate(condition("starts with any of", [""]), EvaluationContext()) is True

        @pytest.mark.parametrize("pattern", ["^u", "undefined", "[a-z]", ".+"])
        def test_a_regex_no_longer_matches_the_word_undefined(self, pattern: str) -> None:
            # The JavaScript SDK used to test the literal text "undefined" here, because it reached
            # the comparison through `value?.toString()`.
            assert evaluator.evaluate(condition("matches regex", [pattern]), EvaluationContext()) is False

        @pytest.mark.parametrize("pattern", ["^$", ".*"])
        def test_a_regex_matching_the_empty_string_does_match(self, pattern: str) -> None:
            assert evaluator.evaluate(condition("matches regex", [pattern]), EvaluationContext()) is True

        def test_a_missing_trait_behaves_the_same_as_a_missing_identifier(self) -> None:
            c = condition("=", [""], attribute="traits", trait="/x")

            assert evaluator.evaluate(c, traits({})) is True
            assert evaluator.evaluate(c, traits({"x": None})) is True

        def test_a_traits_condition_with_no_pointer_compares_as_empty(self) -> None:
            c = condition("=", [""], attribute="traits", trait=None)

            assert evaluator.evaluate(c, traits({"x": "v"})) is True

    class TestNonScalarValuesRenderAsEmptyText:
        """an array or object trait has no text form."""

        @pytest.mark.parametrize("value", [["a"], [1, 2], {"k": "v"}])
        def test_a_structured_trait_equals_the_empty_string(self, value: Any) -> None:
            c = condition("=", [""], attribute="traits", trait="/x")

            assert evaluator.evaluate(c, traits({"x": value})) is True

        def test_a_structured_trait_does_not_match_its_python_repr(self) -> None:
            c = condition("=", ["['a']"], attribute="traits", trait="/x")

            assert evaluator.evaluate(c, traits({"x": ["a"]})) is False

        @pytest.mark.parametrize(
            ("value", "expected_text"),
            [(True, "true"), (False, "false"), (26, "26"), (26.0, "26"), (26.5, "26.5")],
        )
        def test_scalars_render_as_json_text(self, value: Any, expected_text: str) -> None:
            c = condition("=", [expected_text], attribute="traits", trait="/x")

            assert evaluator.evaluate(c, traits({"x": value})) is True


class TestNumberComparisonConditions:
    @pytest.mark.parametrize("operator", ["=", "equals"])
    def test_evaluates_identifier_equals(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator=operator,
            target_type="number",
            target_values=["123456"],
        )

        assert evaluator.evaluate(condition, ctx(id="123456")) is True
        assert evaluator.evaluate(condition, ctx(id="123457")) is False
        assert evaluator.evaluate(condition, ctx()) is False

    @pytest.mark.parametrize("operator", ["!=", "does NOT equal", "does not equal"])
    def test_evaluates_identifier_not_equals(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator=operator,
            target_type="number",
            target_values=["123456"],
        )

        assert evaluator.evaluate(condition, ctx(id="123457")) is True
        assert evaluator.evaluate(condition, ctx()) is True
        assert evaluator.evaluate(condition, ctx(id="123456")) is False

    def test_evaluates_identifier_greater_than(self) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator=">",
            target_type="number",
            target_values=["10"],
        )

        assert evaluator.evaluate(condition, ctx(id="11")) is True
        assert evaluator.evaluate(condition, ctx(id="10.0001")) is True
        assert evaluator.evaluate(condition, ctx(id="10")) is False
        assert evaluator.evaluate(condition, ctx(id="9.999")) is False
        assert evaluator.evaluate(condition, ctx()) is False

    def test_evaluates_identifier_greater_than_or_equal(self) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator=">=",
            target_type="number",
            target_values=["10"],
        )

        assert evaluator.evaluate(condition, ctx(id="10")) is True
        assert evaluator.evaluate(condition, ctx(id="11")) is True
        assert evaluator.evaluate(condition, ctx(id="10.0001")) is True
        assert evaluator.evaluate(condition, ctx(id="9.999")) is False
        assert evaluator.evaluate(condition, ctx()) is False

    def test_evaluates_identifier_less_than(self) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator="<",
            target_type="number",
            target_values=["10"],
        )

        assert evaluator.evaluate(condition, ctx(id="9.999")) is True
        assert evaluator.evaluate(condition, ctx(id="10")) is False
        assert evaluator.evaluate(condition, ctx(id="11")) is False
        assert evaluator.evaluate(condition, ctx(id="10.0001")) is False
        assert evaluator.evaluate(condition, ctx()) is False

    def test_evaluates_identifier_less_than_or_equal(self) -> None:
        condition = Condition(
            id="a",
            attribute="identifier",
            trait=None,
            operator="<=",
            target_type="number",
            target_values=["10"],
        )

        assert evaluator.evaluate(condition, ctx(id="10")) is True
        assert evaluator.evaluate(condition, ctx(id="9.999")) is True
        assert evaluator.evaluate(condition, ctx(id="11")) is False
        assert evaluator.evaluate(condition, ctx(id="10.0001")) is False
        assert evaluator.evaluate(condition, ctx()) is False

    def test_evaluates_trait_greater_than_numeric_and_string_values(self) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait="/profile/age",
            operator=">",
            target_type="number",
            target_values=["25"],
        )

        assert evaluator.evaluate(condition, traits({"profile": {"age": 26}})) is True
        assert evaluator.evaluate(condition, traits({"profile": {"age": "26"}})) is True
        assert evaluator.evaluate(condition, traits({"profile": {"age": 25}})) is False
        assert evaluator.evaluate(condition, traits({"profile": {"name": "John"}})) is False
        assert evaluator.evaluate(condition, traits({})) is False

    class TestStrictNumericParsing:
        """an unparseable number decides the result instead of discarding the rule."""

        @pytest.mark.parametrize("value", ["26abc", " 42 ", "abc", "", "Infinity", "NaN"])
        def test_an_unparseable_value_is_only_ever_not_equal(self, value: str) -> None:
            assert evaluator.evaluate(condition(">", ["25"], target_type="number"), ctx(id=value)) is False
            assert evaluator.evaluate(condition("!=", ["25"], target_type="number"), ctx(id=value)) is True

        @pytest.mark.parametrize("value", ["10", "10.5", "-5", "1e3"])
        def test_a_strictly_parseable_value_compares(self, value: str) -> None:
            c = condition(">", ["-100"], target_type="number")

            assert evaluator.evaluate(c, ctx(id=value)) is True

        def test_evaluation_does_not_raise_for_an_unparseable_value(self) -> None:
            # It used to raise, which made ConfigEvaluator discard the whole rule — including any
            # sibling condition that would have matched.
            c = condition("=", ["25"], target_type="number")

            assert evaluator.evaluate(c, ctx(id="abc")) is False

        def test_a_boolean_trait_is_not_a_number(self) -> None:
            c = condition("=", ["1"], target_type="number", attribute="traits", trait="/x")

            assert evaluator.evaluate(c, traits({"x": True})) is False

        def test_an_unparseable_target_never_matches(self) -> None:
            c = condition("=", ["abc"], target_type="number")

            assert evaluator.evaluate(c, ctx(id="10")) is False


class TestSemverComparisonConditions:
    def test_evaluates_trait_greater_than(self) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait="/system/version",
            operator=">",
            target_type="semver",
            target_values=["10.0.1"],
        )

        assert evaluator.evaluate(condition, traits({"system": {"version": "10.0.2"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"version": "10.1.0"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"version": "10.0.1"}})) is False
        assert evaluator.evaluate(condition, traits({"system": {"version": "9.9.1000"}})) is False
        assert evaluator.evaluate(condition, traits({})) is False

    def test_evaluates_trait_greater_than_or_equal(self) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait="/system/version",
            operator=">=",
            target_type="semver",
            target_values=["10.0.1"],
        )

        assert evaluator.evaluate(condition, traits({"system": {"version": "10.0.2"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"version": "10.1.0"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"version": "10.0.1"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"version": "9.9.1000"}})) is False
        assert evaluator.evaluate(condition, traits({})) is False

    def test_evaluates_trait_less_than(self) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait="/system/version",
            operator="<",
            target_type="semver",
            target_values=["10.0.1"],
        )

        assert evaluator.evaluate(condition, traits({"system": {"version": "10.0.0"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"version": "9.9.1000"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"version": "10.0.2"}})) is False
        assert evaluator.evaluate(condition, traits({"system": {"version": "10.1.0"}})) is False
        assert evaluator.evaluate(condition, traits({"system": {"version": "10.0.1"}})) is False
        assert evaluator.evaluate(condition, traits({})) is False

    def test_evaluates_trait_less_than_or_equal(self) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait="/system/version",
            operator="<=",
            target_type="semver",
            target_values=["10.0.1"],
        )

        assert evaluator.evaluate(condition, traits({"system": {"version": "10.0.1"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"version": "10.0.0"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"version": "9.9.1000"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"version": "10.0.2"}})) is False
        assert evaluator.evaluate(condition, traits({})) is False

    def test_evaluates_trait_is_one_of(self) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait="/system/v",
            operator="is one of",
            target_type="semver",
            target_values=["10.0.1", "1.0", "0.1.645-a"],
        )

        assert evaluator.evaluate(condition, traits({"system": {"v": "10.0.1"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"v": "1.0"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"v": "1.0.0"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"v": "0.1.645-a"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"v": "10.0"}})) is False
        assert evaluator.evaluate(condition, traits({"system": {"v": "1.0.1"}})) is False
        assert evaluator.evaluate(condition, traits({})) is False

    def test_evaluates_trait_equals(self) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait="/system/v",
            operator="=",
            target_type="semver",
            target_values=["10.0.1"],
        )

        assert evaluator.evaluate(condition, traits({"system": {"v": "10.0.1"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"v": "10.0"}})) is False
        assert evaluator.evaluate(condition, traits({"system": {"v": "1.0.1"}})) is False
        assert evaluator.evaluate(condition, traits({})) is False

    @pytest.mark.parametrize("operator", ["is NOT one of", "is not one of"])
    def test_evaluates_trait_is_not_one_of(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait="/system/v",
            operator=operator,
            target_type="semver",
            target_values=["10.0.1", "1.0", "0.1.645-a"],
        )

        assert evaluator.evaluate(condition, traits({"system": {"v": "10.0"}})) is True
        assert evaluator.evaluate(condition, traits({"system": {"v": "1.0.1"}})) is True
        assert evaluator.evaluate(condition, traits({})) is True
        assert evaluator.evaluate(condition, traits({"system": {"v": "10.0.1"}})) is False
        assert evaluator.evaluate(condition, traits({"system": {"v": "1.0"}})) is False
        assert evaluator.evaluate(condition, traits({"system": {"v": "0.1.645-a"}})) is False

    def test_evaluates_app_version_greater_than_or_equal(self) -> None:
        condition = Condition(
            id="a",
            attribute="appVersion",
            trait=None,
            operator=">=",
            target_type="semver",
            target_values=["10.0.1"],
        )

        assert evaluator.evaluate(condition, meta(app_version="10.0.2")) is True
        assert evaluator.evaluate(condition, meta(app_version="10.1.0")) is True
        assert evaluator.evaluate(condition, meta(app_version="10.0.1")) is True
        assert evaluator.evaluate(condition, meta(app_version="9.9.1000")) is False
        assert evaluator.evaluate(condition, meta()) is False

    class TestSemverCoercion:
        """kept from the SDKs; the server was changed to match."""

        @pytest.mark.parametrize("value", ["2.3.4", "v2.3.4", "2.3.4.5", "2.3.4-beta.1"])
        def test_versions_are_coerced_before_comparison(self, value: str) -> None:
            c = condition("=", ["2.3.4"], target_type="semver", attribute="appVersion")

            assert evaluator.evaluate(c, meta(app_version=value)) is True

        def test_partial_versions_compare_as_zero_filled(self) -> None:
            c = condition("=", ["1.0"], target_type="semver", attribute="appVersion")

            assert evaluator.evaluate(c, meta(app_version="1.0.0")) is True


class TestDatetimeComparisonConditions:
    def test_evaluates_trait_is_before(self) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait="/date",
            operator="is before",
            target_type="datetime",
            target_values=["2026-01-28T01:25:00.000Z"],
        )

        assert evaluator.evaluate(condition, traits({"date": "2026-01-28"})) is True
        assert evaluator.evaluate(condition, traits({"date": "2026-01-28T01:24:59.999Z"})) is True
        assert evaluator.evaluate(condition, traits({"date": "2026-01-28T01:25:00.000Z"})) is False
        assert evaluator.evaluate(condition, traits({"date": "2026-01-29"})) is False
        assert evaluator.evaluate(condition, traits({})) is False

    def test_evaluates_trait_is_after(self) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait="/date",
            operator="is after",
            target_type="datetime",
            target_values=["2026-01-28T01:25:00.000Z"],
        )

        assert evaluator.evaluate(condition, traits({"date": "2026-01-29"})) is True
        assert evaluator.evaluate(condition, traits({"date": "2026-01-28T01:25:00.001Z"})) is True
        assert evaluator.evaluate(condition, traits({"date": "2026-01-28T01:25:00.000Z"})) is False
        assert evaluator.evaluate(condition, traits({"date": "2026-01-28"})) is False
        assert evaluator.evaluate(condition, traits({})) is False


class TestArrayComparisonConditions:
    def test_evaluates_trait_contains_any_of(self) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait="/tags",
            operator="contains any of",
            target_type="array",
            target_values=["blue", "yellow", "orange"],
        )

        assert evaluator.evaluate(condition, traits({"tags": ["black", "pink", "blue"]})) is True
        assert evaluator.evaluate(condition, traits({"tags": ["yellow", "pink"]})) is True
        assert evaluator.evaluate(condition, traits({"tags": ["white", "orange", "purple"]})) is True
        assert evaluator.evaluate(condition, traits({"tags": ["pink", "purple", "blu"]})) is False
        assert evaluator.evaluate(condition, traits({"tags": [1, 2, 3]})) is False
        assert evaluator.evaluate(condition, traits({"tags": []})) is False
        assert evaluator.evaluate(condition, traits({"tags": "blue, 2, 3"})) is False
        assert evaluator.evaluate(condition, traits({})) is False

    @pytest.mark.parametrize("operator", ["does NOT contain any of", "does not contain any of"])
    def test_evaluates_trait_does_not_contain_any_of(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait="/tags",
            operator=operator,
            target_type="array",
            target_values=["blue", "yellow", "orange"],
        )

        assert evaluator.evaluate(condition, traits({"tags": ["pink", "purple", "blu"]})) is True
        assert evaluator.evaluate(condition, traits({"tags": [1, 2, 3]})) is True
        assert evaluator.evaluate(condition, traits({"tags": [True, False, False]})) is True
        assert evaluator.evaluate(condition, traits({"tags": []})) is True
        assert evaluator.evaluate(condition, traits({"tags": "blue, 2, 3"})) is True
        assert evaluator.evaluate(condition, traits({})) is True
        assert evaluator.evaluate(condition, EvaluationContext()) is True
        assert evaluator.evaluate(condition, traits({"tags": ["black", "pink", "blue"]})) is False
        assert evaluator.evaluate(condition, traits({"tags": ["yellow", "pink"]})) is False
        assert evaluator.evaluate(condition, traits({"tags": ["white", "orange", "purple"]})) is False

    class TestArrayElementsAreRendered:
        """elements are compared as text, so a number matches a string target."""

        def test_numeric_elements_match_a_string_target(self) -> None:
            c = condition("contains any of", ["1"], target_type="array", attribute="traits", trait="/tags")

            assert evaluator.evaluate(c, traits({"tags": [1, 2]})) is True

        def test_boolean_elements_match_a_string_target(self) -> None:
            c = condition("contains any of", ["true"], target_type="array", attribute="traits", trait="/tags")

            assert evaluator.evaluate(c, traits({"tags": [True]})) is True

        def test_structured_elements_are_dropped_rather_than_matching_empty(self) -> None:
            c = condition("contains any of", [""], target_type="array", attribute="traits", trait="/tags")

            assert evaluator.evaluate(c, traits({"tags": [["a"], {"k": "v"}, None]})) is False


class TestEdgeCases:
    def test_returns_false_for_unknown_attribute(self) -> None:
        condition = Condition(
            id="a",
            attribute="unknownAttribute",
            trait=None,
            operator="equals",
            target_type="text",
            target_values=["value"],
        )

        assert evaluator.evaluate(condition, ctx()) is False

    @pytest.mark.parametrize("operator", ["equals", "="])
    def test_evaluates_app_version_with_text_equals(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="appVersion",
            trait=None,
            operator=operator,
            target_type="text",
            target_values=["1.2.3"],
        )

        assert evaluator.evaluate(condition, meta(app_version="1.2.3")) is True
        assert evaluator.evaluate(condition, meta(app_version="1.2.4")) is False
        assert evaluator.evaluate(condition, EvaluationContext()) is False

    @pytest.mark.parametrize("operator", ["equals", "="])
    def test_returns_false_when_traits_path_is_missing(self, operator: str) -> None:
        condition = Condition(
            id="a",
            attribute="traits",
            trait=None,
            operator=operator,
            target_type="text",
            target_values=["value"],
        )

        assert evaluator.evaluate(condition, traits({"key": "value"})) is False

    def test_an_unknown_attribute_never_matches_a_negative_operator(self) -> None:
        # Distinct from an absent value: there is nothing sensible to compare.
        c = condition("does not contain any of", ["x"], target_type="array", attribute="nope")

        assert evaluator.evaluate(c, EvaluationContext()) is False

    class TestEmptyTargetValues:
        """the "any of" operators fall out of an empty list; the rest cannot compare."""

        @pytest.mark.parametrize(
            "operator",
            ["is not one of", "does not start with any of", "does not end with any of"],
        )
        def test_negative_any_of_operators_are_vacuously_true(self, operator: str) -> None:
            assert evaluator.evaluate(condition(operator, []), ctx(id="abc")) is True

        @pytest.mark.parametrize(
            "operator",
            ["is one of", "starts with any of", "ends with any of", "=", "!=", "matches regex"],
        )
        def test_every_other_text_operator_is_false(self, operator: str) -> None:
            assert evaluator.evaluate(condition(operator, []), ctx(id="abc")) is False

        def test_an_array_condition_follows_the_same_rule(self) -> None:
            context = traits({"tags": ["blue"]})
            positive = condition(
                "contains any of", [], target_type="array", attribute="traits", trait="/tags"
            )
            negative = condition(
                "does not contain any of", [], target_type="array", attribute="traits", trait="/tags"
            )

            assert evaluator.evaluate(positive, context) is False
            assert evaluator.evaluate(negative, context) is True

        def test_semver_is_not_one_of_is_vacuously_true(self) -> None:
            c = condition("is not one of", [], target_type="semver", attribute="appVersion")

            assert evaluator.evaluate(c, meta(app_version="1.0.0")) is True
