from __future__ import annotations

import uuid
from dataclasses import dataclass

from ..types import ConfigDirectorLogger, ConfigState
from ._json_value import to_json_string
from .condition_evaluator import evaluate_condition
from .percent_hashing import assign_percentage
from .types import (
    ConditionalRule,
    Config,
    EvaluationContext,
    Percentage,
    PercentageRule,
    Rule,
)

__all__ = ["ConfigEvaluator"]

# Rules without an explicit order evaluate last, in the order the server sent them.
_LAST = float("inf")


@dataclass(frozen=True, slots=True)
class _RuleResult:
    matched: bool
    value: str = ""
    value_id: str | None = None


_NO_MATCH = _RuleResult(matched=False)


class ConfigEvaluator:
    def __init__(self, logger: ConfigDirectorLogger) -> None:
        self._logger = logger

    def evaluate(self, config: Config, context: EvaluationContext | None = None) -> ConfigState:
        value, value_id = self._get_config_value(config, context)
        return ConfigState(
            id=config.id,
            key=config.key,
            type=config.type,
            value=value,
            value_id=value_id,
        )

    # Returns the selected value together with the server's ID for it. The two travel as a pair
    # because which rule produced the value is the only thing that says which ID belongs to it.
    def _get_config_value(
        self, config: Config, context: EvaluationContext | None
    ) -> tuple[str | None, str | None]:
        rules = sorted(
            config.target.rules,
            key=lambda rule: _LAST if rule.order is None else rule.order,
        )
        for rule in rules:
            result = self._evaluate_rule(rule, config, context)
            if result.matched:
                return result.value, result.value_id

        return config.target.default_value, config.target.default_value_id

    def _evaluate_rule(self, rule: Rule, config: Config, context: EvaluationContext | None) -> _RuleResult:
        try:
            # Gated on the wire value as well as the Python type, so that a rule kind this version
            # of the SDK does not know about is skipped instead of crashing. The isinstance is what
            # makes the narrowing checked: a wire kind that disagrees with the object it was parsed
            # into is skipped too, rather than reaching a field it may not have.
            if rule.type == "percentage" and isinstance(rule, PercentageRule):
                return self._evaluate_percentage(rule.percentages, config, context)
            if rule.type == "conditional" and isinstance(rule, ConditionalRule):
                return self._evaluate_conditional_rule(rule, config, context)
        except Exception as error:  # malformed rule data must not break the evaluation
            self._logger.warning(
                "There was an error while evaluating a targeting rule %r for %r. "
                "The rule will be disregarded. %r",
                rule.id,
                config.key,
                error,
            )

        return _NO_MATCH

    def _evaluate_percentage(
        self,
        percentages: list[Percentage],
        config: Config,
        context: EvaluationContext | None,
    ) -> _RuleResult:
        identifier = context.context.id if context is not None and context.context is not None else None
        if identifier is None:
            # An anonymous caller still gets a bucket, just not a stable one.
            identifier = str(uuid.uuid4())

        assigned = assign_percentage(config.id, identifier)

        bucket: Percentage | None = None
        total = 0.0
        for percentage in percentages:
            if assigned <= percentage.percentage + total:
                bucket = percentage
                break
            total += percentage.percentage

        if bucket is not None and bucket.value is not None:
            return _RuleResult(matched=True, value=to_json_string(bucket.value), value_id=bucket.value_id)
        return _NO_MATCH

    def _evaluate_conditional_rule(
        self,
        rule: ConditionalRule,
        config: Config,
        context: EvaluationContext | None,
    ) -> _RuleResult:
        if not any(evaluate_condition(condition, context) for condition in rule.conditions or []):
            return _NO_MATCH
        if rule.target == "value" and rule.value is not None:
            return _RuleResult(matched=True, value=to_json_string(rule.value), value_id=rule.value_id)
        if rule.target == "percentage":
            return self._evaluate_percentage(rule.percentages, config, context)
        return _NO_MATCH
