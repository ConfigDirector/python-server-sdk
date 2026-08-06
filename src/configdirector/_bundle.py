from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from .evaluation._json_value import to_json_string
from .evaluation.types import (
    Condition,
    ConditionalRule,
    Config,
    EnumTypeConstraints,
    NumericTypeConstraints,
    Percentage,
    PercentageRule,
    Rule,
    RuleValue,
    TargetingRules,
    Variation,
)
from .types import ConfigDirectorLogger, ConfigType

__all__ = ["BundleKind", "ConfigBundle", "parse_bundle"]

BundleKind = Literal["full", "delta"]


@dataclass(frozen=True, slots=True)
class ConfigBundle:
    configs: dict[str, Config] = field(default_factory=dict)
    kind: BundleKind = "full"
    environment_id: str | None = None
    project_id: str | None = None
    # Echoed back on the next poll so the server can answer with a delta. The server may omit
    # it, in which case every poll returns a full bundle.
    timestamp: str | None = None


def parse_bundle(payload: str, logger: ConfigDirectorLogger) -> ConfigBundle:
    document = json.loads(payload)
    if not isinstance(document, dict):
        raise ValueError(f"Expected the config bundle to be a JSON object, got {type(document).__name__}")

    return ConfigBundle(
        configs=_parse_configs(document.get("configs"), logger),
        kind="delta" if document.get("kind") == "delta" else "full",
        environment_id=_optional_string(document.get("environmentId")),
        project_id=_optional_string(document.get("projectId")),
        timestamp=_optional_string(document.get("timestamp")),
    )


def _parse_configs(raw: Any, logger: ConfigDirectorLogger) -> dict[str, Config]:
    if not isinstance(raw, dict):
        return {}

    configs: dict[str, Config] = {}
    for key, definition in raw.items():
        try:
            configs[str(key)] = _parse_config(definition)
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            # One unreadable config must not cost the application every other config in the
            # bundle. It keeps whatever definition it already had, or falls back to defaults.
            logger.warning("Skipping the config %r, its definition could not be read: %r", key, error)
    return configs


def _parse_config(raw: Any) -> Config:
    target = raw["target"]
    return Config(
        id=str(raw["id"]),
        key=str(raw["key"]),
        type=cast(ConfigType, raw["type"]),
        target=TargetingRules(
            default_value=_as_string(target.get("defaultValue")),
            rules=[_parse_rule(rule) for rule in target.get("rules") or []],
        ),
        variations=[_parse_variation(variation) for variation in raw.get("variations") or []],
        type_constraints=_parse_type_constraints(raw.get("typeConstraints")),
    )


def _parse_rule(raw: Any) -> Rule:
    kind = raw.get("type")
    percentages = [_parse_percentage(percentage) for percentage in raw.get("percentages") or []]

    if kind == "percentage":
        return PercentageRule(
            id=str(raw["id"]),
            order=_optional_int(raw.get("order")),
            percentages=percentages,
        )

    # Anything that is not a percentage rule is carried as a conditional rule with its wire type
    # intact. A rule kind this SDK version predates is then skipped during evaluation rather than
    # discarded here, which keeps the reason for the skip visible in one place.
    return ConditionalRule(
        id=str(raw["id"]),
        order=_optional_int(raw.get("order")),
        value=_rule_value(raw.get("value")),
        conditions=[_parse_condition(condition) for condition in raw.get("conditions") or []],
        percentages=percentages,
        target=str(raw.get("target") or "value"),
        type=str(kind) if kind is not None else "conditional",
    )


def _parse_condition(raw: Any) -> Condition:
    return Condition(
        id=str(raw["id"]),
        attribute=str(raw["attribute"]),
        operator=str(raw["operator"]),
        target_type=str(raw["targetType"]),
        target_values=[_as_string(value) for value in raw.get("targetValues") or []],
        trait=_optional_string(raw.get("trait")),
    )


def _parse_percentage(raw: Any) -> Percentage:
    return Percentage(
        id=str(raw["id"]),
        percentage=float(raw["percentage"]),
        value=_rule_value(raw.get("value")),
    )


def _parse_variation(raw: Any) -> Variation:
    value = raw.get("value")
    return Variation(
        value=value if isinstance(value, (str, int, float, bool)) else _as_string(value),
        name=_optional_string(raw.get("name")),
    )


def _parse_type_constraints(raw: Any) -> NumericTypeConstraints | EnumTypeConstraints | None:
    if not isinstance(raw, dict):
        return None
    if "valueType" in raw:
        return EnumTypeConstraints(
            value_type="number" if raw.get("valueType") == "number" else "string",
            values=[_as_string(value) for value in raw.get("values") or []],
        )
    return NumericTypeConstraints(min=raw.get("min"), max=raw.get("max"))


def _rule_value(value: Any) -> RuleValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    # A structured value reaches the application as the JSON text it was sent as.
    return json.dumps(value, separators=(",", ":"))


def _as_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        # Rendered the way every other ConfigDirector SDK renders it, so that a rule written
        # against `true` or `26` compares the same everywhere.
        return to_json_string(value)
    return json.dumps(value, separators=(",", ":"))


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: Any) -> int | None:
    # Rules without a usable order evaluate last, in the order the server sent them.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)
