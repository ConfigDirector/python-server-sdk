from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import Any

from ._evaluation import Config, TargetingRules, Variation
from ._validation import validate_config_key
from .errors import ConfigDirectorTypeError, ConfigDirectorValidationError
from .types import ConfigType, ConfigValue

__all__ = ["unconditional_config"]


def unconditional_config(key: str, value: ConfigValue, *, config_id: str, value_id: str | None) -> Config:
    config_type, text = _encode(key, value)
    return Config(
        id=config_id,
        key=key,
        type=config_type,
        target=TargetingRules(default_value=text, default_value_id=value_id),
        variations=[Variation(value=text)],
    )


def _encode(key: str, value: ConfigValue) -> tuple[ConfigType, str]:
    validate_config_key(key)
    if value is None:
        raise ConfigDirectorTypeError(f"Invalid value for {key!r}: None is not a value.")
    if isinstance(value, bool):
        return "boolean", "true" if value else "false"
    if isinstance(value, int):
        return "integer", _integer_text(key, value)
    if isinstance(value, float):
        return "float", _plain_decimal(key, value)
    if isinstance(value, str):
        return "string", value
    if isinstance(value, (dict, list)):
        return "json", _json_text(key, value)
    raise ConfigDirectorTypeError(
        f"Invalid value for {key!r} of type {type(value).__name__!r}. A value must be a bool, an int, "
        f"a float, a str, a dict with str keys, or a list."
    )


def _integer_text(key: str, value: int) -> str:
    try:
        return str(value)
    except ValueError as error:
        raise ConfigDirectorValidationError(
            f"Invalid value for {key!r}: the integer has too many digits to be written out ({error})."
        ) from error


def _plain_decimal(key: str, value: float) -> str:
    if not math.isfinite(value):
        raise ConfigDirectorValidationError(f"Invalid value for {key!r}: {value!r} is not a finite number.")
    return format(Decimal(repr(value)).normalize(), "f")


def _json_text(key: str, value: dict[str, Any] | list[Any]) -> str:
    _validate_json_contents(key, value, "")
    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except ValueError as error:
        raise ConfigDirectorValidationError(f"Invalid value for {key!r}: {error}.") from error


def _validate_json_contents(key: str, value: object, path: str) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfigDirectorValidationError(
                f"Invalid value for {key!r}{_at_json_path(path)}: {value!r} is not a finite number."
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_contents(key, item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for member_key, member in value.items():
            if not isinstance(member_key, str):
                raise ConfigDirectorTypeError(
                    f"Invalid value for {key!r}{_at_json_path(path)}: the key {member_key!r} is not a str."
                )
            _validate_json_contents(key, member, f"{path}.{member_key}" if path else member_key)
        return
    raise ConfigDirectorTypeError(
        f"Invalid value for {key!r}{_at_json_path(path)}: a value of type {type(value).__name__!r} cannot be "
        f"encoded as JSON. JSON contents can hold bools, ints, finite floats, strs, None, lists, and dicts "
        f"with str keys."
    )


def _at_json_path(path: str) -> str:
    return f" at {path!r}" if path else ""
