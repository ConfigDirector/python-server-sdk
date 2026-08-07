from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..types import ConfigType, Context, Metadata

__all__ = [
    "ARRAY_OPERATORS",
    "DATETIME_OPERATORS",
    "NUMBER_OPERATORS",
    "SEMVER_OPERATORS",
    "TEXT_OPERATORS",
    "Condition",
    "ConditionalRule",
    "Config",
    "EnumTypeConstraints",
    "EvaluationContext",
    "NumericTypeConstraints",
    "Percentage",
    "PercentageRule",
    "Rule",
    "RuleValue",
    "Target",
    "TargetType",
    "TargetingRules",
    "Variation",
]

TEXT_OPERATORS = (
    "equals",
    "does NOT equal",
    "is one of",
    "is NOT one of",
    "starts with any of",
    "does NOT start with any of",
    "ends with any of",
    "does NOT end with any of",
    "matches regex",
    "does NOT match regex",
)
NUMBER_OPERATORS = ("=", "!=", ">", ">=", "<", "<=")
SEMVER_OPERATORS = ("is one of", "is NOT one of", ">", ">=", "<", "<=")
DATETIME_OPERATORS = ("is before", "is after")
ARRAY_OPERATORS = ("contains any of", "does NOT contain any of")

Target = Literal["value", "percentage"]
TargetType = Literal["text", "number", "semver", "datetime", "array"]

# The value a rule or percentage bucket resolves to, before it is rendered to a string.
RuleValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class Condition:
    id: str
    attribute: str
    operator: str
    target_type: str
    target_values: list[str]
    trait: str | None = None


@dataclass(frozen=True, slots=True)
class Percentage:
    id: str
    percentage: float
    value: RuleValue = None
    value_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConditionalRule:
    id: str
    order: int | None
    value: RuleValue = None
    conditions: list[Condition] = field(default_factory=list)
    percentages: list[Percentage] = field(default_factory=list)
    target: str = "value"
    type: str = "conditional"
    value_id: str | None = None


@dataclass(frozen=True, slots=True)
class PercentageRule:
    id: str
    order: int | None
    percentages: list[Percentage] = field(default_factory=list)
    target: str = "percentage"
    type: str = "percentage"


Rule = ConditionalRule | PercentageRule


@dataclass(frozen=True, slots=True)
class TargetingRules:
    default_value: str
    rules: list[Rule] = field(default_factory=list)
    default_value_id: str | None = None


@dataclass(frozen=True, slots=True)
class Variation:
    value: str | int | float | bool
    name: str | None = None


@dataclass(frozen=True, slots=True)
class NumericTypeConstraints:
    min: dict[str, Any] | None = None
    max: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class EnumTypeConstraints:
    value_type: Literal["string", "number"]
    values: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Config:
    id: str
    key: str
    type: ConfigType
    target: TargetingRules
    variations: list[Variation] = field(default_factory=list)
    type_constraints: NumericTypeConstraints | EnumTypeConstraints | None = None


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    context: Context | None = None
    metadata: Metadata | None = None
