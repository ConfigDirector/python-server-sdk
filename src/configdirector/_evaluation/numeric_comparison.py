from __future__ import annotations

import math
from typing import Any

__all__ = ["compare_numeric"]

# The only characters a plain decimal literal can contain. Checking membership is a single pass,
# with none of the backtracking a pattern with adjacent digit repeats would allow.
_DECIMAL_CHARACTERS = frozenset("0123456789+-.eE")


def compare_numeric(value: Any, operator: str, target_values: list[str]) -> bool:
    lowercase_operator = operator.lower()

    parsed = _parse_finite(value)
    if parsed is None:
        return lowercase_operator in ("!=", "does not equal")

    if not target_values:
        return False
    target = _parse_finite(target_values[0])
    if target is None:
        return False

    match lowercase_operator:
        case "=" | "equals":
            return parsed == target
        case "!=" | "does not equal":
            return parsed != target
        case "<":
            return parsed < target
        case "<=":
            return parsed <= target
        case ">":
            return parsed > target
        case ">=":
            return parsed >= target
        case _:
            return False


def _parse_finite(value: Any) -> float | None:
    # Booleans are not numbers here, even though Python counts them as ints.
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if not isinstance(value, str) or not value:
        return None

    # float() would accept surrounding whitespace, digit separators such as 1_000, and the words
    # "inf" and "nan". Restricting the characters first rules those out; float() then validates
    # the grammar, rejecting the likes of "1.2.3" and "1e". Both steps are a single pass.
    if not _DECIMAL_CHARACTERS.issuperset(value):
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None
