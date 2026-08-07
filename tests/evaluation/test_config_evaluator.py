from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from configdirector import Context, Metadata
from configdirector._evaluation import (
    Condition,
    ConditionalRule,
    Config,
    ConfigEvaluator,
    EvaluationContext,
    Percentage,
    PercentageRule,
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


def identifier_is(value: str) -> Condition:
    return Condition(
        id=uid(),
        attribute="identifier",
        operator="=",
        trait=None,
        target_type="text",
        target_values=[value],
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

    def test_falls_back_to_the_default_when_conditions_array_is_empty(self) -> None:
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

        assert evaluator.evaluate(config, ctx(id="10")).value == "this-is-the-default"

    def test_matches_on_the_first_true_condition(self) -> None:
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
                        conditions=[identifier_is("10"), identifier_is("20")],
                    )
                ],
            ),
        )

        assert evaluator.evaluate(config, ctx(id="10")).value == "Rule A Value"
        assert evaluator.evaluate(config, ctx(id="20")).value == "Rule A Value"
        assert evaluator.evaluate(config, ctx(id="30")).value == "this-is-the-default"

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


class TestNoContext:
    def test_returns_a_value_for_a_percentage_rule_when_no_context_is_provided(self) -> None:
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
                        percentages=[Percentage(value="Only Group", percentage=100, id=uid())],
                    )
                ],
            ),
        )

        # with no context, a random UUID is used — at 100% the bucket always matches
        assert evaluator.evaluate(config).value == "Only Group"


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
    def _config_with(self, condition: Condition) -> Config:
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
            Condition(
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
            Condition(
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
            Condition(
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
            Condition(
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
            Condition(
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
                            Condition(
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
                            Condition(
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
