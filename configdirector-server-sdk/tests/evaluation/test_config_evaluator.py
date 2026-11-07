from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from configdirector import ConfigState, Context, Metadata, Variation
from configdirector._evaluation import (
    AttributeCondition,
    ConditionalRule,
    Config,
    ConfigEvaluator,
    ConfigVariation,
    EvaluationContext,
    Percentage,
    PercentageRule,
    Rule,
    TargetingRules,
)
from tests.helpers import create_stubbed_logger

CONFIG_ID = "11111111-1111-4111-8111-111111111111"

logger = create_stubbed_logger()
evaluator = ConfigEvaluator(logger)


def uid() -> str:
    return str(uuid.uuid4())


def ctx(**kwargs: Any) -> EvaluationContext:
    return EvaluationContext(context=Context(**kwargs))


def identifier_is(value: str) -> AttributeCondition:
    return AttributeCondition(
        id=uid(),
        attribute="identifier",
        operator="=",
        trait=None,
        target_type="text",
        target_values=[value],
    )


def plan_is(value: str) -> AttributeCondition:
    return AttributeCondition(
        id=uid(),
        attribute="traits",
        operator="=",
        trait="/plan",
        target_type="text",
        target_values=[value],
    )


def name_is(value: str) -> AttributeCondition:
    return AttributeCondition(
        id=uid(),
        attribute="name",
        operator="equals",
        trait=None,
        target_type="text",
        target_values=[value],
    )


def config_requiring(*conditions: AttributeCondition) -> Config:
    return Config(
        id=CONFIG_ID,
        key="config-with-a-two-condition-rule",
        type="string",
        variations=[],
        target=TargetingRules(
            default_value="this-is-the-default",
            rules=[
                ConditionalRule(
                    id=uid(),
                    order=0,
                    target="value",
                    value="Rule A Value",
                    percentages=[],
                    conditions=list(conditions),
                )
            ],
        ),
    )


def test_evaluates_to_the_default_value_when_there_are_no_targeting_rules() -> None:
    config = Config(
        id=CONFIG_ID,
        key="config-without-rules",
        type="string",
        variations=[],
        target=TargetingRules(default_value="this-is-the-default", rules=[]),
    )

    config_state = evaluator.evaluate(config)

    assert config_state.id == config.id
    assert config_state.key == config.key
    assert config_state.type == config.type
    assert config_state.value == "this-is-the-default"


class TestPercentageRules:
    def test_assigns_percentages_when_they_add_up_to_100(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="config-without-rules",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="this-is-the-default",
                rules=[
                    PercentageRule(
                        id=uid(),
                        order=0,
                        target="percentage",
                        percentages=[
                            Percentage(value="Group A", percentage=50.5, id=uid()),
                            Percentage(value="Group B", percentage=49.5, id=uid()),
                        ],
                    )
                ],
            ),
        )

        assert evaluator.evaluate(config, ctx(id="10")).value == "Group A"
        assert evaluator.evaluate(config, ctx(id="15")).value == "Group A"
        assert evaluator.evaluate(config, ctx(id="20")).value == "Group B"

    # A bucket spans [start, end), so a 0% bucket is empty and unreachable no matter who asks.
    # With an inclusive boundary it would take one of the 1000 reachable hash values, and a
    # variation turned down to 0% would still serve roughly 0.1% of traffic.
    def test_a_zero_percent_bucket_is_unreachable_for_every_identifier(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="config-without-rules",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="this-is-the-default",
                rules=[
                    PercentageRule(
                        id=uid(),
                        order=0,
                        percentages=[
                            Percentage(value="never", percentage=0, id=uid()),
                            Percentage(value="always", percentage=100, id=uid()),
                        ],
                    )
                ],
            ),
        )

        for i in range(4_000):
            assert evaluator.evaluate(config, ctx(id=f"user-{i}")).value == "always"

    def test_falls_back_to_the_default_when_percentages_do_not_add_up_to_100(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="config-without-rules",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="this-is-the-default",
                rules=[
                    PercentageRule(
                        id=uid(),
                        order=0,
                        target="percentage",
                        percentages=[
                            Percentage(value="Group A", percentage=20, id=uid()),
                            Percentage(value="Group B", percentage=30, id=uid()),
                        ],
                    )
                ],
            ),
        )

        assert evaluator.evaluate(config, ctx(id="10")).value == "Group A"
        assert evaluator.evaluate(config, ctx(id="15")).value == "Group B"
        assert evaluator.evaluate(config, ctx(id="80")).value == "this-is-the-default"

    def test_falls_back_to_the_default_if_a_percentage_does_not_have_a_value(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="config-without-rules",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="this-is-the-default",
                rules=[
                    PercentageRule(
                        id=uid(),
                        order=0,
                        target="percentage",
                        percentages=[
                            Percentage(value="Group A", percentage=50.5, id=uid()),
                            Percentage(value=None, percentage=49.5, id=uid()),
                        ],
                    )
                ],
            ),
        )

        assert evaluator.evaluate(config, ctx(id="10")).value == "Group A"
        assert evaluator.evaluate(config, ctx(id="15")).value == "Group A"
        assert evaluator.evaluate(config, ctx(id="20")).value == "this-is-the-default"


class TestConditionalRules:
    def test_evaluates_a_value_based_conditional_rule(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="config-without-rules",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="this-is-the-default",
                rules=[
                    ConditionalRule(
                        id=uid(),
                        order=0,
                        target="value",
                        value="Rule A Value",
                        percentages=[],
                        conditions=[identifier_is("10")],
                    )
                ],
            ),
        )

        assert evaluator.evaluate(config, ctx(id="10")).value == "Rule A Value"
        assert evaluator.evaluate(config, ctx(id="20")).value == "this-is-the-default"

    def test_evaluates_a_percentage_based_conditional_rule(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="config-without-rules",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="this-is-the-default",
                rules=[
                    ConditionalRule(
                        id=uid(),
                        order=0,
                        target="percentage",
                        value=None,
                        percentages=[
                            Percentage(value="Group A", percentage=50.5, id=uid()),
                            Percentage(value="Group B", percentage=49.5, id=uid()),
                        ],
                        conditions=[identifier_is("10")],
                    )
                ],
            ),
        )

        assert evaluator.evaluate(config, ctx(id="10")).value == "Group A"
        assert evaluator.evaluate(config, ctx(id="20")).value == "this-is-the-default"

    def test_cycles_through_multiple_rules(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="config-without-rules",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="this-is-the-default",
                rules=[
                    ConditionalRule(
                        id=uid(),
                        order=0,
                        target="value",
                        value="Rule A Value",
                        percentages=[],
                        conditions=[identifier_is("10")],
                    ),
                    ConditionalRule(
                        id=uid(),
                        order=1,
                        target="value",
                        value="Rule B Value",
                        percentages=[],
                        conditions=[identifier_is("15")],
                    ),
                ],
            ),
        )

        assert evaluator.evaluate(config, ctx(id="10")).value == "Rule A Value"
        assert evaluator.evaluate(config, ctx(id="15")).value == "Rule B Value"
        assert evaluator.evaluate(config, ctx(id="20")).value == "this-is-the-default"

    def test_a_rule_with_no_conditions_applies_to_every_context(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="config-without-rules",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="this-is-the-default",
                rules=[
                    ConditionalRule(
                        id=uid(),
                        order=0,
                        target="value",
                        value="Rule A Value",
                        percentages=[],
                        conditions=[],
                    )
                ],
            ),
        )

        assert evaluator.evaluate(config, ctx(id="10")).value == "Rule A Value"
        assert evaluator.evaluate(config).value == "Rule A Value"

    def test_a_rule_with_several_conditions_matches_when_every_condition_matches(self) -> None:
        config = config_requiring(identifier_is("10"), plan_is("pro"))

        assert evaluator.evaluate(config, ctx(id="10", traits={"plan": "pro"})).value == "Rule A Value"

    def test_a_rule_with_several_conditions_does_not_match_when_only_the_first_matches(self) -> None:
        config = config_requiring(identifier_is("10"), plan_is("pro"))

        assert (
            evaluator.evaluate(config, ctx(id="10", traits={"plan": "free"})).value == "this-is-the-default"
        )

    def test_a_rule_with_several_conditions_does_not_match_when_only_the_second_matches(self) -> None:
        config = config_requiring(identifier_is("10"), plan_is("pro"))

        assert evaluator.evaluate(config, ctx(id="20", traits={"plan": "pro"})).value == "this-is-the-default"

    def test_a_rule_with_several_conditions_does_not_match_when_no_condition_matches(self) -> None:
        config = config_requiring(identifier_is("10"), plan_is("pro"))

        assert (
            evaluator.evaluate(config, ctx(id="20", traits={"plan": "free"})).value == "this-is-the-default"
        )

    def test_a_rule_whose_conditions_cannot_all_hold_never_matches(self) -> None:
        config = config_requiring(identifier_is("10"), identifier_is("20"))

        assert evaluator.evaluate(config, ctx(id="10")).value == "this-is-the-default"
        assert evaluator.evaluate(config, ctx(id="20")).value == "this-is-the-default"

    def test_falls_back_to_the_default_when_the_condition_matches_but_the_value_is_none(
        self,
    ) -> None:
        config = Config(
            id=CONFIG_ID,
            key="config-without-rules",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="this-is-the-default",
                rules=[
                    ConditionalRule(
                        id=uid(),
                        order=0,
                        target="value",
                        value=None,
                        percentages=[],
                        conditions=[identifier_is("10")],
                    )
                ],
            ),
        )

        assert evaluator.evaluate(config, ctx(id="10")).value == "this-is-the-default"

    def test_falls_back_to_the_default_when_no_context_is_provided(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="config-without-rules",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="this-is-the-default",
                rules=[
                    ConditionalRule(
                        id=uid(),
                        order=0,
                        target="value",
                        value="Rule A Value",
                        percentages=[],
                        conditions=[identifier_is("10")],
                    )
                ],
            ),
        )

        assert evaluator.evaluate(config).value == "this-is-the-default"


class TestRuleOrdering:
    def test_evaluates_rules_in_ascending_order_regardless_of_array_order(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="config-without-rules",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="this-is-the-default",
                rules=[
                    ConditionalRule(
                        id=uid(),
                        order=1,
                        target="value",
                        value="Rule B Value",
                        percentages=[],
                        conditions=[identifier_is("10")],
                    ),
                    ConditionalRule(
                        id=uid(),
                        order=0,
                        target="value",
                        value="Rule A Value",
                        percentages=[],
                        conditions=[identifier_is("10")],
                    ),
                ],
            ),
        )

        # order 0 rule should win even though it appears second in the array
        assert evaluator.evaluate(config, ctx(id="10")).value == "Rule A Value"


class TestMixedRuleTypes:
    def test_evaluates_a_percentage_rule_followed_by_a_conditional_rule_in_order(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="config-without-rules",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="this-is-the-default",
                rules=[
                    PercentageRule(
                        id=uid(),
                        order=0,
                        target="percentage",
                        percentages=[Percentage(value="Percentage Group", percentage=100, id=uid())],
                    ),
                    ConditionalRule(
                        id=uid(),
                        order=1,
                        target="value",
                        value="Conditional Value",
                        percentages=[],
                        conditions=[identifier_is("10")],
                    ),
                ],
            ),
        )

        # the percentage rule (order 0) always matches at 100%, so the conditional rule is
        # never reached
        assert evaluator.evaluate(config, ctx(id="10")).value == "Percentage Group"
        assert evaluator.evaluate(config, ctx(id="99")).value == "Percentage Group"


class TestContextsWithoutAnIdentifier:
    def _rollout(self, order: int = 0) -> PercentageRule:
        return PercentageRule(
            id=uid(),
            order=order,
            target="percentage",
            percentages=[Percentage(value="Only Group", percentage=100, id=uid())],
        )

    def _config_with(self, *rules: Rule) -> Config:
        return Config(
            id=CONFIG_ID,
            key="config-with-a-rollout",
            type="string",
            variations=[],
            target=TargetingRules(default_value="this-is-the-default", rules=list(rules)),
        )

    def test_no_context_skips_a_percentage_rule_and_gets_the_default_targeting_rule_value(self) -> None:
        state = evaluator.evaluate(self._config_with(self._rollout()))

        assert state.value == "this-is-the-default"

    def test_a_context_without_an_id_skips_a_percentage_rule_and_gets_the_default_targeting_rule_value(
        self,
    ) -> None:
        state = evaluator.evaluate(self._config_with(self._rollout()), ctx(name="Ada"))

        assert state.value == "this-is-the-default"

    def test_a_context_without_an_id_skips_the_rollout_of_a_matching_conditional_rule(self) -> None:
        config = self._config_with(
            ConditionalRule(
                id=uid(),
                order=0,
                target="percentage",
                conditions=[name_is("Ada")],
                percentages=[Percentage(value="Only Group", percentage=100, id=uid())],
            )
        )

        state = evaluator.evaluate(config, ctx(name="Ada"))

        assert state.value == "this-is-the-default"

    def test_the_rules_after_a_skipped_rollout_are_tried(self) -> None:
        config = self._config_with(
            self._rollout(order=0),
            ConditionalRule(id=uid(), order=1, value="Later Rule", conditions=[name_is("Ada")]),
        )

        served_config = evaluator.evaluate_with_reason(config, ctx(name="Ada"))

        assert served_config.state.value == "Later Rule"
        assert served_config.reason == "found-match"

    def test_a_context_without_an_id_matching_a_conditional_rollout_is_served_a_later_rule_on_the_app_version(
        self,
    ) -> None:
        app_version_is_at_least_2 = AttributeCondition(
            id=uid(),
            attribute="appVersion",
            operator=">=",
            trait=None,
            target_type="semver",
            target_values=["2.0.0"],
        )
        config = self._config_with(
            ConditionalRule(
                id=uid(),
                order=0,
                target="percentage",
                conditions=[plan_is("pro")],
                percentages=[Percentage(value="Only Group", percentage=100, id=uid())],
            ),
            ConditionalRule(
                id=uid(), order=1, value="New copy for 2.x", conditions=[app_version_is_at_least_2]
            ),
        )
        context = EvaluationContext(
            context=Context(traits={"plan": "pro"}), metadata=Metadata(app_version="2.1.0")
        )

        served_config = evaluator.evaluate_with_reason(config, context)

        assert served_config.state.value == "New copy for 2.x"
        assert served_config.reason == "found-match"

    def test_the_default_after_a_skipped_rollout_that_no_later_rule_matches_keeps_the_skip_reason(
        self,
    ) -> None:
        config = self._config_with(
            self._rollout(order=0),
            ConditionalRule(id=uid(), order=1, value="Later Rule", conditions=[name_is("Grace")]),
        )

        served_config = evaluator.evaluate_with_reason(config, ctx(name="Ada"))

        assert served_config.state.value == "this-is-the-default"
        assert served_config.reason == "rollout-skipped-no-identifier"

    def test_the_rules_after_a_conditional_rule_whose_conditions_do_not_match_are_tried(self) -> None:
        config = self._config_with(
            ConditionalRule(
                id=uid(),
                order=0,
                target="percentage",
                conditions=[name_is("Grace")],
                percentages=[Percentage(value="Only Group", percentage=100, id=uid())],
            ),
            ConditionalRule(id=uid(), order=1, value="Later Rule", conditions=[name_is("Ada")]),
        )

        served_config = evaluator.evaluate_with_reason(config, ctx(name="Ada"))

        assert served_config.state.value == "Later Rule"
        assert served_config.reason == "found-match"

    def test_a_rule_that_serves_a_single_value_still_applies(self) -> None:
        config = self._config_with(
            ConditionalRule(id=uid(), order=0, value="Single Value", conditions=[name_is("Ada")]),
            self._rollout(order=1),
        )

        served_config = evaluator.evaluate_with_reason(config, ctx(name="Ada"))

        assert served_config.state.value == "Single Value"
        assert served_config.reason == "found-match"

    def test_a_rule_without_percentages_is_not_a_skipped_rollout_and_the_next_rule_is_tried(self) -> None:
        config = self._config_with(
            ConditionalRule(
                id=uid(), order=0, target="percentage", percentages=None, conditions=[name_is("Ada")]
            ),
            ConditionalRule(id=uid(), order=1, value="Later Rule", conditions=[name_is("Ada")]),
        )

        served_config = evaluator.evaluate_with_reason(config, ctx(name="Ada"))

        assert served_config.state.value == "Later Rule"
        assert served_config.reason == "found-match"

    def test_a_rollout_whose_percentages_are_empty_is_skipped_and_the_next_rule_is_tried(self) -> None:
        config = self._config_with(
            PercentageRule(id=uid(), order=0, percentages=[]),
            ConditionalRule(id=uid(), order=1, value="Later Rule", conditions=[name_is("Ada")]),
        )

        served_config = evaluator.evaluate_with_reason(config, ctx(name="Ada"))

        assert served_config.state.value == "Later Rule"
        assert served_config.reason == "found-match"

    def test_a_skipped_rollout_gives_the_reason_for_the_skip(self) -> None:
        served_config = evaluator.evaluate_with_reason(self._config_with(self._rollout()), ctx(name="Ada"))

        assert served_config.reason == "rollout-skipped-no-identifier"

    def test_a_context_with_an_id_is_served_the_rollout_with_a_found_match(self) -> None:
        served_config = evaluator.evaluate_with_reason(self._config_with(self._rollout()), ctx(id="user-1"))

        assert served_config.state.value == "Only Group"
        assert served_config.reason == "found-match"

    def test_the_default_targeting_rule_value_reached_without_a_rollout_is_a_found_match(self) -> None:
        served_config = evaluator.evaluate_with_reason(self._config_with(), ctx(name="Ada"))

        assert served_config.state.value == "this-is-the-default"
        assert served_config.reason == "found-match"


class TestPercentageRulesByKind:
    def _config_split_at_8_and_50(self) -> Config:
        return Config(
            id=CONFIG_ID,
            key="split",
            type="string",
            target=TargetingRules(
                default_value="this-is-the-default",
                rules=[
                    PercentageRule(
                        id=uid(),
                        order=0,
                        percentages=[
                            Percentage(value="below 8", percentage=8, id=uid()),
                            Percentage(value="8 to 50", percentage=42, id=uid()),
                            Percentage(value="50 and above", percentage=50, id=uid()),
                        ],
                    )
                ],
            ),
        )

    def test_a_context_without_a_kind_keeps_its_user_assignment(self) -> None:
        assert evaluator.evaluate(self._config_split_at_8_and_50(), ctx(id="user-1")).value == "below 8"

    def test_a_context_whose_kind_is_user_keeps_its_user_assignment(self) -> None:
        state = evaluator.evaluate(self._config_split_at_8_and_50(), ctx(id="user-1", kind="user"))

        assert state.value == "below 8"

    def test_a_device_with_the_same_identifier_gets_an_assignment_of_its_own(self) -> None:
        state = evaluator.evaluate(self._config_split_at_8_and_50(), ctx(id="user-1", kind="device"))

        assert state.value == "50 and above"

    def test_a_tenant_with_the_same_identifier_gets_an_assignment_of_its_own(self) -> None:
        state = evaluator.evaluate(self._config_split_at_8_and_50(), ctx(id="user-1", kind="tenant"))

        assert state.value == "8 to 50"

    def test_a_device_without_an_identifier_skips_the_rollout(self) -> None:
        state = evaluator.evaluate(self._config_split_at_8_and_50(), ctx(kind="device"))

        assert state.value == "this-is-the-default"


@dataclass(frozen=True, slots=True)
class _UnknownRule:
    id: str
    order: int | None
    type: str = "unknown"


class TestUnknownRuleType:
    def test_skips_an_unknown_rule_type_and_falls_back_to_the_default_value(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="config-without-rules",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="this-is-the-default",
                rules=[_UnknownRule(id=uid(), order=0)],  # type: ignore[list-item]
            ),
        )

        assert evaluator.evaluate(config, ctx(id="10")).value == "this-is-the-default"


class TestResilienceToMalformedRuntimeConditionData:
    def _config_with(self, condition: AttributeCondition) -> Config:
        return Config(
            id=CONFIG_ID,
            key="cfg",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="default",
                rules=[
                    ConditionalRule(
                        id=uid(),
                        order=0,
                        target="value",
                        value="rule-value",
                        percentages=[],
                        conditions=[condition],
                    )
                ],
            ),
        )

    def test_text_condition_with_no_target_values(self) -> None:
        config = self._config_with(
            AttributeCondition(
                id=uid(),
                attribute="identifier",
                operator="=",
                target_type="text",
                target_values=None,  # type: ignore[arg-type]
            )
        )

        assert evaluator.evaluate(config, ctx(id="10")).value == "default"

    def test_numeric_condition_with_no_target_values(self) -> None:
        config = self._config_with(
            AttributeCondition(
                id=uid(),
                attribute="identifier",
                operator="=",
                target_type="number",
                target_values=None,  # type: ignore[arg-type]
            )
        )

        assert evaluator.evaluate(config, ctx(id="10")).value == "default"

    def test_semver_condition_with_no_target_values(self) -> None:
        config = self._config_with(
            AttributeCondition(
                id=uid(),
                attribute="appVersion",
                operator=">",
                target_type="semver",
                target_values=None,  # type: ignore[arg-type]
            )
        )

        context = EvaluationContext(context=Context(id="10"), metadata=Metadata(app_version="2.0.0"))
        assert evaluator.evaluate(config, context).value == "default"

    def test_datetime_condition_with_no_target_values(self) -> None:
        config = self._config_with(
            AttributeCondition(
                id=uid(),
                attribute="traits",
                trait="/createdAt",
                operator="is after",
                target_type="datetime",
                target_values=None,  # type: ignore[arg-type]
            )
        )

        context = ctx(id="10", traits={"createdAt": "2024-01-01T00:00:00Z"})
        assert evaluator.evaluate(config, context).value == "default"

    def test_array_condition_with_no_target_values(self) -> None:
        config = self._config_with(
            AttributeCondition(
                id=uid(),
                attribute="traits",
                trait="/roles",
                operator="contains any of",
                target_type="array",
                target_values=None,  # type: ignore[arg-type]
            )
        )

        context = ctx(id="10", traits={"roles": ["admin", "user"]})
        assert evaluator.evaluate(config, context).value == "default"


class TestNumericComparisonEdgeCases:
    def test_does_not_raise_when_an_integer_trait_meets_a_decimal_target(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="cfg",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="default",
                rules=[
                    ConditionalRule(
                        id=uid(),
                        order=0,
                        target="value",
                        value="rule-value",
                        percentages=[],
                        conditions=[
                            AttributeCondition(
                                id=uid(),
                                attribute="traits",
                                trait="/score",
                                operator=">=",
                                target_type="number",
                                target_values=["3.14"],
                            )
                        ],
                    )
                ],
            ),
        )

        evaluator.evaluate(config, ctx(id="10", traits={"score": 5}))

    def test_does_not_raise_with_an_empty_target_values_array(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="cfg",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="default",
                rules=[
                    ConditionalRule(
                        id=uid(),
                        order=0,
                        target="value",
                        value="rule-value",
                        percentages=[],
                        conditions=[
                            AttributeCondition(
                                id=uid(),
                                attribute="traits",
                                trait="/score",
                                operator="=",
                                target_type="number",
                                target_values=[],
                            )
                        ],
                    )
                ],
            ),
        )

        evaluator.evaluate(config, ctx(id="10", traits={"score": 5}))


class TestRuleOrderingWithMissingOrderValues:
    def test_evaluates_rules_in_a_stable_order_when_order_is_missing(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="cfg",
            type="string",
            variations=[],
            target=TargetingRules(
                default_value="default",
                rules=[
                    ConditionalRule(
                        id=uid(),
                        order=None,
                        target="value",
                        value="first-rule",
                        percentages=[],
                        conditions=[identifier_is("10")],
                    ),
                    ConditionalRule(
                        id=uid(),
                        order=0,
                        target="value",
                        value="second-rule",
                        percentages=[],
                        conditions=[identifier_is("10")],
                    ),
                ],
            ),
        )

        assert evaluator.evaluate(config, ctx(id="10")).value == "second-rule"


class TestValueIds:
    """Each value the server can select carries the ID the server gave it."""

    def test_the_targeting_default_value_carries_its_id(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="greeting",
            type="string",
            target=TargetingRules(default_value="hello", default_value_id="id-default", rules=[]),
        )

        state = evaluator.evaluate(config)

        assert state.value == "hello"
        assert state.value_id == "id-default"

    def test_a_matched_conditional_rule_carries_its_id(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="greeting",
            type="string",
            target=TargetingRules(
                default_value="hello",
                default_value_id="id-default",
                rules=[
                    ConditionalRule(
                        id=uid(),
                        order=0,
                        value="bonjour",
                        value_id="id-rule",
                        conditions=[identifier_is("user-1")],
                    )
                ],
            ),
        )

        state = evaluator.evaluate(config, ctx(id="user-1"))

        assert state.value == "bonjour"
        assert state.value_id == "id-rule"

    def test_a_matched_percentage_bucket_carries_its_id(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="greeting",
            type="string",
            target=TargetingRules(
                default_value="hello",
                default_value_id="id-default",
                rules=[
                    PercentageRule(
                        id=uid(),
                        order=0,
                        percentages=[
                            Percentage(id=uid(), percentage=100.0, value="rolled", value_id="id-bucket")
                        ],
                    )
                ],
            ),
        )

        state = evaluator.evaluate(config, ctx(id="user-1"))

        assert state.value == "rolled"
        assert state.value_id == "id-bucket"

    def test_an_unmatched_rule_falls_back_to_the_default_value_id(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="greeting",
            type="string",
            target=TargetingRules(
                default_value="hello",
                default_value_id="id-default",
                rules=[
                    ConditionalRule(
                        id=uid(),
                        order=0,
                        value="bonjour",
                        value_id="id-rule",
                        conditions=[identifier_is("someone-else")],
                    )
                ],
            ),
        )

        state = evaluator.evaluate(config, ctx(id="user-1"))

        assert state.value == "hello"
        assert state.value_id == "id-default"


class TestVariationsAndRolloutShares:
    CONTROL_ID = "77777777-7777-4777-8777-777777777777"
    TREATMENT_ID = "88888888-8888-4888-8888-888888888888"
    UNNAMED_ID = "99999999-9999-4999-8999-999999999999"
    EMPTY_NAME_ID = "99999999-9999-4999-8999-99999999999a"
    RULE_ID = "22222222-2222-4222-8222-222222222222"
    SHARE_ID = "66666666-6666-4666-8666-666666666666"

    def _treatment_share(self) -> Percentage:
        return Percentage(
            id=self.SHARE_ID,
            percentage=100,
            value="Try it free",
            value_id="value-id-treatment",
            variation_id=self.TREATMENT_ID,
        )

    def _experiment(self, *rules: Rule) -> Config:
        return Config(
            id=CONFIG_ID,
            key="checkout-cta-copy",
            type="string",
            variations=[
                ConfigVariation(id=self.CONTROL_ID, name="control", value="Start free trial"),
                ConfigVariation(id=self.TREATMENT_ID, name="treatment", value="Try it free"),
                ConfigVariation(id=self.UNNAMED_ID, name=None, value="Get started"),
                ConfigVariation(id=self.EMPTY_NAME_ID, name="", value="Begin"),
            ],
            target=TargetingRules(
                default_value="Start free trial",
                default_value_id="value-id-control",
                default_variation_id=self.CONTROL_ID,
                rules=list(rules),
            ),
        )

    def _rule_serving(self, value: str, variation_id: str) -> ConditionalRule:
        return ConditionalRule(
            id=self.RULE_ID,
            order=0,
            value=value,
            value_id=f"value-id-{value}",
            variation_id=variation_id,
            conditions=[identifier_is("user-1")],
        )

    def test_a_percentage_rule_serves_the_variation_rule_and_share_of_its_bucket(self) -> None:
        config = self._experiment(
            PercentageRule(id=self.RULE_ID, order=0, percentages=[self._treatment_share()])
        )

        state = evaluator.evaluate(config, ctx(id="user-1"))

        assert state == ConfigState(
            id=CONFIG_ID,
            key="checkout-cta-copy",
            type="string",
            value="Try it free",
            value_id="value-id-treatment",
            variation=Variation(id=self.TREATMENT_ID, name="treatment"),
            rule_id=self.RULE_ID,
            share_id=self.SHARE_ID,
        )

    def test_a_conditional_rules_rollout_serves_the_variation_rule_and_share_of_its_bucket(self) -> None:
        config = self._experiment(
            ConditionalRule(
                id=self.RULE_ID,
                order=0,
                target="percentage",
                conditions=[identifier_is("user-1")],
                percentages=[self._treatment_share()],
            )
        )

        state = evaluator.evaluate(config, ctx(id="user-1"))

        assert state.variation == Variation(id=self.TREATMENT_ID, name="treatment")
        assert state.rule_id == self.RULE_ID
        assert state.share_id == self.SHARE_ID

    def test_a_conditional_rules_value_carries_its_variation_and_no_rule_or_share(self) -> None:
        config = self._experiment(self._rule_serving("Try it free", self.TREATMENT_ID))

        state = evaluator.evaluate(config, ctx(id="user-1"))

        assert state.variation == Variation(id=self.TREATMENT_ID, name="treatment")
        assert state.rule_id is None
        assert state.share_id is None

    def test_the_default_targeting_rule_value_carries_its_variation_and_no_rule_or_share(self) -> None:
        state = evaluator.evaluate(self._experiment(), ctx(id="user-1"))

        assert state.value == "Start free trial"
        assert state.variation == Variation(id=self.CONTROL_ID, name="control")
        assert state.rule_id is None
        assert state.share_id is None

    def test_a_skipped_rollout_carries_the_default_targeting_rule_values_variation_and_no_rule_or_share(
        self,
    ) -> None:
        config = self._experiment(
            PercentageRule(id=self.RULE_ID, order=0, percentages=[self._treatment_share()])
        )

        state = evaluator.evaluate(config, ctx(name="Ada"))

        assert state.value == "Start free trial"
        assert state.value_id == "value-id-control"
        assert state.variation == Variation(id=self.CONTROL_ID, name="control")
        assert state.rule_id is None
        assert state.share_id is None

    def test_a_variation_without_a_name_has_its_id_and_no_name(self) -> None:
        config = self._experiment(self._rule_serving("Get started", self.UNNAMED_ID))

        state = evaluator.evaluate(config, ctx(id="user-1"))

        assert state.variation == Variation(id=self.UNNAMED_ID, name=None)

    def test_a_variation_whose_name_is_empty_has_its_id_and_no_name(self) -> None:
        config = self._experiment(self._rule_serving("Begin", self.EMPTY_NAME_ID))

        state = evaluator.evaluate(config, ctx(id="user-1"))

        assert state.variation == Variation(id=self.EMPTY_NAME_ID, name=None)

    def test_a_variation_id_the_config_does_not_list_gives_no_variation(self) -> None:
        config = self._experiment(self._rule_serving("Gone", "00000000-0000-4000-8000-000000000000"))

        state = evaluator.evaluate(config, ctx(id="user-1"))

        assert state.value == "Gone"
        assert state.variation is None

    def test_a_flag_in_a_rollout_carries_its_rule_and_share_and_no_variation(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="dark-mode",
            type="boolean",
            target=TargetingRules(
                default_value="false",
                rules=[
                    PercentageRule(
                        id=self.RULE_ID,
                        order=0,
                        percentages=[Percentage(id=self.SHARE_ID, percentage=100, value="true")],
                    )
                ],
            ),
        )

        state = evaluator.evaluate(config, ctx(id="user-1"))

        assert state.variation is None
        assert state.rule_id == self.RULE_ID
        assert state.share_id == self.SHARE_ID

    def test_a_flag_without_rules_carries_no_variation_rule_or_share(self) -> None:
        config = Config(
            id=CONFIG_ID,
            key="dark-mode",
            type="boolean",
            target=TargetingRules(default_value="false", rules=[]),
        )

        state = evaluator.evaluate(config, ctx(id="user-1"))

        assert state.variation is None
        assert state.rule_id is None
        assert state.share_id is None
