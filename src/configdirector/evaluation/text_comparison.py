from __future__ import annotations

import re

__all__ = ["compare_text"]


def compare_text(value: str, operator: str, target_values: list[str]) -> bool:
    first = target_values[0] if target_values else None

    match operator.lower():
        case "=" | "equals":
            return first is not None and value == first
        case "!=" | "does not equal":
            return first is not None and value != first
        case "is one of":
            return value in target_values
        case "is not one of":
            return value not in target_values
        case "starts with any of":
            return any(value.startswith(target) for target in target_values)
        case "does not start with any of":
            return not any(value.startswith(target) for target in target_values)
        case "ends with any of":
            return any(value.endswith(target) for target in target_values)
        case "does not end with any of":
            return not any(value.endswith(target) for target in target_values)
        case "matches regex":
            return first is not None and _matches_regex(first, value)
        case "does not match regex":
            return first is not None and not _matches_regex(first, value)
        case _:
            return False


def _matches_regex(pattern: str, value: str) -> bool:
    try:
        return re.search(pattern, value) is not None
    except re.error:
        return False
