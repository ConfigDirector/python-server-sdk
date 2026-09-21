from __future__ import annotations

import json
import math
from dataclasses import dataclass

from .types import ConfigState, ConfigValue, EvaluationReason

__all__ = ["ParseResult", "parse_config_value"]

# The only characters a decimal literal may contain. Checking membership up front rules out
# what int() and float() would otherwise accept: surrounding whitespace, digit separators such
# as 1_000, non-ASCII digits, and the words "inf" and "nan".
_DECIMAL_CHARACTERS = frozenset("0123456789+-.eE")


@dataclass(frozen=True, slots=True)
class ParseResult:
    value: ConfigValue
    reason: EvaluationReason
    used_default: bool = False
    value_id: str | None = None


# Coerces an evaluated config value into the type the caller asked for. The requested type comes
# from `default`, not from how the config was declared in the dashboard: a caller that passes a
# bool gets a bool or their default back, never a string that happens to read as one.
def parse_config_value(state: ConfigState, default: ConfigValue) -> ParseResult:
    raw = state.value
    if not raw:
        return ParseResult(value=default, reason="value-missing", used_default=True)

    # Checked before int, which bool subclasses.
    if isinstance(default, bool):
        parsed_bool = _parse_boolean(raw)
        if parsed_bool is None:
            return ParseResult(value=default, reason="invalid-boolean", used_default=True)
        return _matched(parsed_bool, state)

    if isinstance(default, str):
        return _matched(raw, state)

    if isinstance(default, int):
        parsed_int = _parse_integer(raw)
        if parsed_int is None:
            return ParseResult(value=default, reason="invalid-number", used_default=True)
        return _matched(parsed_int, state)

    if isinstance(default, float):
        parsed_float = _parse_float(raw)
        if parsed_float is None:
            return ParseResult(value=default, reason="invalid-number", used_default=True)
        return _matched(parsed_float, state)

    # A dict or a list: the config holds JSON.
    try:
        return _matched(json.loads(raw), state)
    except ValueError:
        return ParseResult(value=default, reason="invalid-json", used_default=True)


def _matched(value: ConfigValue, state: ConfigState) -> ParseResult:
    return ParseResult(value=value, reason="found-match", value_id=state.value_id)


def _parse_boolean(value: str) -> bool | None:
    lowered = value.lower()
    if lowered not in ("true", "false"):
        return None
    return lowered == "true"


def _parse_integer(value: str) -> int | None:
    if not _DECIMAL_CHARACTERS.issuperset(value):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    # A whole number the server happened to write with a decimal point, such as "26.0".
    parsed = _parse_float(value)
    if parsed is None or not parsed.is_integer():
        return None
    return int(parsed)


def _parse_float(value: str) -> float | None:
    if not _DECIMAL_CHARACTERS.issuperset(value):
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None
