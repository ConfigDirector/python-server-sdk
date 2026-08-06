from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import cast

from ..types import ConfigDirectorLogger, ConfigState
from ._json_value import to_json_string
from .condition_evaluator import ConditionEvaluator
from .percent_hashing import assign_percentage
from .types import (
    Condition,
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


_NO_MATCH = _RuleResult(matched=False)


class ConfigEvaluator:
    def __init__(self, logger: ConfigDirectorLogger) -> None:
        for method in ("debug", "info", "warning", "error"):
            if not callable(getattr(logger, method, None)):
                raise TypeError(
                    f"The provided logger is not a valid ConfigDirectorLogger: it has no "
                    f"callable '{method}' method."
                )
        self._logger = logger
        self._condition_evaluator = ConditionEvaluator()

    def evaluate(self, config: Config, context: EvaluationContext | None = None) -> ConfigState:
        return ConfigState(
            id=config.id,
            key=config.key,
            type=config.type,
            value=self._get_config_value(config, context),
        )

    def _get_config_value(self, config: Config, context: EvaluationContext | None) -> str | None:
        rules = sorted(
            config.target.rules,
            key=lambda rule: _LAST if rule.order is None else rule.order,
        )
        for rule in rules:
            result = self._evaluate_rule(rule, config, context)
            if result.matched:
                return result.value

        return config.target.default_value

    def _evaluate_rule(self, rule: Rule, config: Config, context: EvaluationContext | None) -> _RuleResult:
        try:
            # Dispatched on the wire value rather than the Python type, so that a rule kind this
            # version of the SDK does not know about is skipped instead of crashing.
            if rule.type == "percentage":
                return self._evaluate_percentage(cast(PercentageRule, rule).percentages, config, context)
            if rule.type == "conditional":
                return self._evaluate_conditional_rule(cast(ConditionalRule, rule), config, context)
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
            return _RuleResult(matched=True, value=to_json_string(bucket.value))
        return _NO_MATCH

    def _evaluate_conditional_rule(
        self,
        rule: ConditionalRule,
        config: Config,
        context: EvaluationContext | None,
    ) -> _RuleResult:
        matched: Condition | None = next(
            (
                condition
                for condition in (rule.conditions or [])
                if self._condition_evaluator.evaluate(condition, context)
            ),
            None,
        )

        if matched is None:
            return _NO_MATCH
        if rule.target == "value" and rule.value is not None:
            return _RuleResult(matched=True, value=to_json_string(rule.value))
        if rule.target == "percentage":
            return self._evaluate_percentage(rule.percentages, config, context)
        return _NO_MATCH
