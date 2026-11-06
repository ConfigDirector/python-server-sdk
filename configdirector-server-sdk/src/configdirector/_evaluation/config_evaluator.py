from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .._context_kind import effective_kind
from ..types import ConfigDirectorLogger, ConfigState, Variation
from ._json_value import to_json_string
from .condition_evaluator import evaluate_condition
from .percent_hashing import assign_percentage
from .segment_evaluator import evaluate_segment_condition
from .types import (
    Condition,
    ConditionalRule,
    Config,
    EvaluationContext,
    Percentage,
    PercentageRule,
    Rule,
    SegmentCondition,
    Segments,
)

__all__ = ["ConfigEvaluator"]

# Rules without an explicit order evaluate last, in the order the server sent them.
_LAST = float("inf")

_ServingReason = Literal["found-match", "rollout-skipped-no-identifier"]


@dataclass(frozen=True, slots=True)
class _ServedValue:
    value: str
    value_id: str | None
    variation_id: str | None
    rule_id: str | None = None
    share_id: str | None = None


@dataclass(frozen=True, slots=True)
class _RuleNotMatched:
    pass


@dataclass(frozen=True, slots=True)
class _RolloutSkippedNoIdentifier:
    pass


_RuleServing = _ServedValue | _RuleNotMatched | _RolloutSkippedNoIdentifier

_NOT_MATCHED = _RuleNotMatched()
_ROLLOUT_SKIPPED_NO_IDENTIFIER = _RolloutSkippedNoIdentifier()


@dataclass(frozen=True, slots=True)
class _ServedConfig:
    state: ConfigState
    reason: _ServingReason


class ConfigEvaluator:
    def __init__(self, logger: ConfigDirectorLogger) -> None:
        self._logger = logger

    def evaluate(
        self,
        config: Config,
        context: EvaluationContext | None = None,
        segments: Segments | None = None,
    ) -> ConfigState:
        return self.evaluate_with_reason(config, context, segments).state

    def evaluate_with_reason(
        self,
        config: Config,
        context: EvaluationContext | None = None,
        segments: Segments | None = None,
    ) -> _ServedConfig:
        rules = sorted(
            config.target.rules,
            key=lambda rule: _LAST if rule.order is None else rule.order,
        )
        for rule in rules:
            match self._evaluate_rule(rule, config, context, segments):
                case _ServedValue() as served_value:
                    return _served_config(config, served_value, "found-match")
                case _RolloutSkippedNoIdentifier():
                    return _served_config(
                        config, _default_targeting_rule_value(config), "rollout-skipped-no-identifier"
                    )
                case _RuleNotMatched():
                    pass

        return _served_config(config, _default_targeting_rule_value(config), "found-match")

    def _evaluate_rule(
        self, rule: Rule, config: Config, context: EvaluationContext | None, segments: Segments | None
    ) -> _RuleServing:
        try:
            # Gated on the wire value as well as the Python type, so that a rule kind this version
            # of the SDK does not know about is skipped instead of crashing. The isinstance is what
            # makes the narrowing checked: a wire kind that disagrees with the object it was parsed
            # into is skipped too, rather than reaching a field it may not have.
            if rule.type == "percentage" and isinstance(rule, PercentageRule):
                return self._evaluate_percentage(rule, config, context)
            if rule.type == "conditional" and isinstance(rule, ConditionalRule):
                return self._evaluate_conditional_rule(rule, config, context, segments)
        except Exception as error:  # malformed rule data must not break the evaluation
            self._logger.warning(
                "There was an error while evaluating a targeting rule %r for %r. "
                "The rule will be disregarded. %r",
                rule.id,
                config.key,
                error,
            )

        return _NOT_MATCHED

    def _evaluate_percentage(
        self,
        rule: Rule,
        config: Config,
        context: EvaluationContext | None,
    ) -> _RuleServing:
        if rule.percentages is None:
            return _NOT_MATCHED
        supplied_context = context.context if context is not None else None
        identifier = supplied_context.id if supplied_context is not None else None
        if identifier is None:
            return _ROLLOUT_SKIPPED_NO_IDENTIFIER
        assigned_percentage = assign_percentage(config.id, identifier, effective_kind(supplied_context))

        bucket: Percentage | None = None
        total = 0.0
        # A bucket spans [total, total + percentage). Strict, so a context landing exactly on a
        # boundary belongs to the bucket that starts there -- which is what keeps a 0% bucket
        # unreachable and each bucket's share exact. See SEMANTICS.md 7.1.
        for percentage in rule.percentages:
            if assigned_percentage < percentage.percentage + total:
                bucket = percentage
                break
            total += percentage.percentage

        if bucket is None or bucket.value is None:
            return _NOT_MATCHED
        return _ServedValue(
            value=to_json_string(bucket.value),
            value_id=bucket.value_id,
            variation_id=bucket.variation_id,
            rule_id=rule.id,
            share_id=bucket.id,
        )

    def _evaluate_conditional_rule(
        self,
        rule: ConditionalRule,
        config: Config,
        context: EvaluationContext | None,
        segments: Segments | None,
    ) -> _RuleServing:
        if not all(_condition_holds(condition, context, segments) for condition in rule.conditions or []):
            return _NOT_MATCHED
        if rule.target == "value" and rule.value is not None:
            return _ServedValue(
                value=to_json_string(rule.value), value_id=rule.value_id, variation_id=rule.variation_id
            )
        if rule.target == "percentage":
            return self._evaluate_percentage(rule, config, context)
        return _NOT_MATCHED


def _default_targeting_rule_value(config: Config) -> _ServedValue:
    return _ServedValue(
        value=config.target.default_value,
        value_id=config.target.default_value_id,
        variation_id=config.target.default_variation_id,
    )


def _served_config(config: Config, served_value: _ServedValue, reason: _ServingReason) -> _ServedConfig:
    return _ServedConfig(
        state=ConfigState(
            id=config.id,
            key=config.key,
            type=config.type,
            value=served_value.value,
            value_id=served_value.value_id,
            variation=_variation_with_id(config, served_value.variation_id),
            rule_id=served_value.rule_id,
            share_id=served_value.share_id,
        ),
        reason=reason,
    )


def _variation_with_id(config: Config, variation_id: str | None) -> Variation | None:
    if variation_id is None:
        return None
    for variation in config.variations:
        if variation.id == variation_id:
            return Variation(id=variation_id, name=variation.name or None)
    return None


def _condition_holds(
    condition: Condition, context: EvaluationContext | None, segments: Segments | None
) -> bool:
    if isinstance(condition, SegmentCondition):
        return evaluate_segment_condition(condition, segments, context)
    return evaluate_condition(condition, context)
