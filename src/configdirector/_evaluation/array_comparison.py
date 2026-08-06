from __future__ import annotations

from typing import Any

from ._json_value import to_json_string

__all__ = ["compare_array"]


def compare_array(value: Any, operator: str, target_values: list[str]) -> bool:
    lowercase_operator = operator.lower()
    if not isinstance(value, list):
        return lowercase_operator == "does not contain any of"

    # Nested arrays, objects, and nulls have no text form, so they are dropped rather than
    # matching an empty target value.
    elements = [to_json_string(item) for item in value if isinstance(item, (str, int, float, bool))]

    match lowercase_operator:
        case "contains any of":
            return any(element in target_values for element in elements)
        case "does not contain any of":
            return not any(element in target_values for element in elements)
        case _:
            return False
