from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .._evaluation._json_value import to_json_string
from ..types import ConfigType, ConfigValue, EvaluationReason
from .compact_json import to_compact_json
from .value_id import generate_value_id

__all__ = [
    "CONFIG_VALUE_MAX_LENGTH",
    "EvaluatedConfigEvent",
    "TelemetryValue",
    "render_value",
    "requested_type_of",
    "value_id_for",
]

# Values longer than this are reported by ID rather than inline, to keep telemetry payloads small.
CONFIG_VALUE_MAX_LENGTH = 500


# The name reported for the type a caller asked a config to be returned as. Each SDK reports the
# name its own language uses, so this is str/int/dict where the JavaScript SDK reports
# string/number/Object.
def requested_type_of(default: ConfigValue) -> str:
    return type(default).__name__


@dataclass(frozen=True, slots=True)
class TelemetryValue:
    value: str | None = None
    value_id: str | None = None
    type: ConfigType | None = None

    # `value_id` is the ID the server sent along with the config state, when there was one.
    @classmethod
    def of(
        cls,
        value: ConfigValue,
        *,
        value_id: str | None = None,
        config_type: ConfigType | None = None,
    ) -> TelemetryValue:
        if _is_json(value, config_type):
            if value_id is not None:
                return cls(value_id=value_id, type="json")
            return cls(value=render_value(value, config_type), type="json")

        rendered = render_value(value, config_type)
        if len(rendered) <= CONFIG_VALUE_MAX_LENGTH:
            return cls(value=rendered)
        return cls(value_id=value_id) if value_id is not None else cls(value=rendered)

    # The form that is sent to the server: values too large to report inline, and every JSON
    # document, are replaced by their ID. This is the only step that hashes, which is why it
    # runs on the flush thread rather than on the caller's.
    def compacted(self) -> TelemetryValue:
        if self.value_id is not None:
            return TelemetryValue(value_id=self.value_id)
        if self.value and (self.type == "json" or len(self.value) > CONFIG_VALUE_MAX_LENGTH):
            return TelemetryValue(value_id=generate_value_id(self.value))
        return TelemetryValue(value=self.value)

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {}
        if self.value is not None:
            wire["value"] = self.value
        if self.value_id is not None:
            wire["valueId"] = self.value_id
        if self.type is not None:
            wire["type"] = self.type
        return wire


@dataclass(frozen=True, slots=True)
class EvaluatedConfigEvent:
    key: str
    default_value: TelemetryValue
    evaluated_value: TelemetryValue
    requested_type: str
    used_default: bool
    evaluation_reason: EvaluationReason
    context_id: str | None = None
    type: ConfigType | None = None
    evaluated_value_id: str | None = None

    @classmethod
    def of(
        cls,
        *,
        key: str,
        default: ConfigValue,
        value: ConfigValue,
        used_default: bool,
        reason: EvaluationReason,
        context_id: str | None = None,
        config_type: ConfigType | None = None,
        value_id: str | None = None,
    ) -> EvaluatedConfigEvent:
        return cls(
            key=key,
            default_value=TelemetryValue.of(default, config_type=config_type),
            evaluated_value=TelemetryValue.of(value, value_id=value_id, config_type=config_type),
            requested_type=requested_type_of(default),
            used_default=used_default,
            evaluation_reason=reason,
            context_id=context_id,
            type=config_type,
            evaluated_value_id=value_id,
        )

    def compacted(self) -> EvaluatedConfigEvent:
        return replace(
            self,
            default_value=self.default_value.compacted(),
            evaluated_value=self.evaluated_value.compacted(),
        )

    def to_wire(self) -> dict[str, Any]:
        wire: dict[str, Any] = {}
        if self.context_id is not None:
            wire["contextId"] = self.context_id
        wire["key"] = self.key
        if self.type is not None:
            wire["type"] = self.type
        wire["defaultValue"] = self.default_value.to_wire()
        wire["requestedType"] = self.requested_type
        wire["evaluatedValue"] = self.evaluated_value.to_wire()
        if self.evaluated_value_id is not None:
            wire["evaluatedValueId"] = self.evaluated_value_id
        wire["usedDefault"] = self.used_default
        wire["evaluationReason"] = self.evaluation_reason
        return wire


def render_value(value: ConfigValue, config_type: ConfigType | None = None) -> str:
    if _is_json(value, config_type):
        try:
            return to_compact_json(value)
        except TypeError:
            # A default the caller built out of something JSON cannot represent is still worth
            # counting, so fall back to however the value describes itself.
            return str(value)
    return to_json_string(value)


def value_id_for(value: ConfigValue, config_type: ConfigType | None = None) -> str:
    return generate_value_id(render_value(value, config_type))


def _is_json(value: ConfigValue, config_type: ConfigType | None) -> bool:
    # An evaluation that found no config state has no declared type, so the value itself is all
    # there is to go on.
    return config_type == "json" or (config_type is None and isinstance(value, (dict, list)))
