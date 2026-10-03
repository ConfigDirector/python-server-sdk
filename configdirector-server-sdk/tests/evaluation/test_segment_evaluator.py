from __future__ import annotations

import uuid
from typing import Any

from configdirector import Context, Metadata
from configdirector._evaluation import (
    AttributeCondition,
    Condition,
    ConditionalRule,
    Config,
    ConfigEvaluator,
    EvaluationContext,
    Segment,
    SegmentCondition,
    Segments,
    TargetingRules,
)
from tests.helpers import create_stubbed_logger

CONFIG_ID = "11111111-1111-4111-8111-111111111111"
ACME = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BETA = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
MISSING = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

evaluator = ConfigEvaluator(create_stubbed_logger())


def uid() -> str:
    return str(uuid.uuid4())


def email_ends_with(domain: str) -> AttributeCondition:
    return AttributeCondition(
        id=uid(),
        attribute="traits",
        trait="/email",
        operator="ends with any of",
        target_type="text",
        target_values=[domain],
    )


def plan_is(plan: str, operator: str = "equals") -> AttributeCondition:
    return AttributeCondition(
        id=uid(),
        attribute="traits",
        trait="/plan",
        operator=operator,
        target_type="text",
        target_values=[plan],
    )


def in_segment(segment_id: str, operator: str = "in") -> SegmentCondition:
    return SegmentCondition(id=uid(), operator=operator, segment_id=segment_id)


def config_serving(value: str, *conditions: Condition) -> Config:
    return Config(
        id=CONFIG_ID,
        key="greeting",
        type="string",
        target=TargetingRules(
            default_value="hello",
            rules=[
                ConditionalRule(id=uid(), order=0, target="value", value=value, conditions=list(conditions))
            ],
        ),
    )


def served(config: Config, segments: Segments | None, **context: Any) -> str | None:
    return evaluator.evaluate(config, EvaluationContext(context=Context(**context)), segments).value


ACME_MEMBERS: Segments = {ACME: Segment(groups=[[email_ends_with("@acme.com")]])}


class TestSegmentConditions:
    def test_in_serves_a_context_in_the_segment(self) -> None:
        config = config_serving("members", in_segment(ACME))

        assert served(config, ACME_MEMBERS, traits={"email": "ann@acme.com"}) == "members"

    def test_in_falls_through_for_a_context_outside_the_segment(self) -> None:
        config = config_serving("members", in_segment(ACME))

        assert served(config, ACME_MEMBERS, traits={"email": "bob@other.com"}) == "hello"

    def test_not_in_serves_a_context_outside_the_segment(self) -> None:
        config = config_serving("outsiders", in_segment(ACME, "not in"))

        assert served(config, ACME_MEMBERS, traits={"email": "bob@other.com"}) == "outsiders"

    def test_not_in_falls_through_for_a_context_in_the_segment(self) -> None:
        config = config_serving("outsiders", in_segment(ACME, "not in"))

        assert served(config, ACME_MEMBERS, traits={"email": "ann@acme.com"}) == "hello"

    def test_operators_are_matched_case_insensitively(self) -> None:
        config = config_serving("members", in_segment(ACME, "IN"))

        assert served(config, ACME_MEMBERS, traits={"email": "ann@acme.com"}) == "members"

    def test_an_unknown_segment_operator_never_matches(self) -> None:
        config = config_serving("members", in_segment(ACME, "within"))

        assert served(config, ACME_MEMBERS, traits={"email": "ann@acme.com"}) == "hello"

    def test_a_segment_absent_from_the_map_matches_nothing_for_in(self) -> None:
        config = config_serving("members", in_segment(MISSING))

        assert served(config, ACME_MEMBERS, traits={"email": "ann@acme.com"}) == "hello"

    def test_a_segment_absent_from_the_map_matches_nothing_for_not_in(self) -> None:
        config = config_serving("outsiders", in_segment(MISSING, "not in"))

        assert served(config, ACME_MEMBERS, traits={"email": "ann@acme.com"}) == "hello"

    def test_a_segment_condition_never_matches_without_a_segments_map(self) -> None:
        config = config_serving("outsiders", in_segment(ACME, "not in"))

        assert served(config, None, traits={"email": "bob@other.com"}) == "hello"

    def test_combines_with_attribute_conditions_by_and(self) -> None:
        config = config_serving("pro members", in_segment(ACME), plan_is("pro"))

        assert served(config, ACME_MEMBERS, traits={"email": "ann@acme.com", "plan": "pro"}) == "pro members"
        assert served(config, ACME_MEMBERS, traits={"email": "ann@acme.com", "plan": "free"}) == "hello"
        assert served(config, ACME_MEMBERS, traits={"email": "bob@other.com", "plan": "pro"}) == "hello"


class TestSegmentMembership:
    def test_any_group_matching_puts_the_context_in(self) -> None:
        segments = {
            ACME: Segment(
                groups=[[email_ends_with("@acme.com"), plan_is("pro")], [email_ends_with("@beta.com")]]
            )
        }
        config = config_serving("members", in_segment(ACME))

        assert served(config, segments, traits={"email": "ann@acme.com", "plan": "pro"}) == "members"
        assert served(config, segments, traits={"email": "ann@acme.com", "plan": "free"}) == "hello"
        assert served(config, segments, traits={"email": "cat@beta.com", "plan": "free"}) == "members"
        assert served(config, segments, traits={"email": "bob@other.com", "plan": "pro"}) == "hello"

    def test_a_group_with_no_conditions_matches_every_context(self) -> None:
        config = config_serving("everyone", in_segment(ACME))

        assert served(config, {ACME: Segment(groups=[[]])}, id="u1") == "everyone"

    def test_a_segment_with_no_groups_matches_no_context(self) -> None:
        config = config_serving("nobody", in_segment(BETA))

        assert served(config, {BETA: Segment(groups=[])}, id="u1") == "hello"

    def test_an_absent_trait_is_the_empty_string_inside_a_group(self) -> None:
        segments = {ACME: Segment(groups=[[plan_is("free", operator="is NOT one of")]])}
        config = config_serving("not free", in_segment(ACME))

        assert served(config, segments, id="u1") == "not free"

    def test_groups_see_the_metadata_of_the_evaluation(self) -> None:
        version_at_least_2 = AttributeCondition(
            id=uid(), attribute="appVersion", operator=">=", target_type="semver", target_values=["2.0.0"]
        )
        segments = {ACME: Segment(groups=[[version_at_least_2]])}
        config = config_serving("modern", in_segment(ACME))

        modern = evaluator.evaluate(
            config,
            EvaluationContext(context=Context(id="u1"), metadata=Metadata(app_version="2.1.0")),
            segments,
        )
        old = evaluator.evaluate(
            config,
            EvaluationContext(context=Context(id="u1"), metadata=Metadata(app_version="1.9.0")),
            segments,
        )

        assert modern.value == "modern"
        assert old.value == "hello"
