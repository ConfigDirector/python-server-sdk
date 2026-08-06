from __future__ import annotations

import re
from collections.abc import Callable

__all__ = ["compare_semver"]

# node-semver's `coerce` regex: find the first run of digits that could start a version, then
# up to two more dot-separated components. Each component is capped at 16 digits.
# "1.2" coerces to 1.2.0, "v1.2.3" to 1.2.3, "1.2.3.4" to 1.2.3, and "0.1.645-a" to 0.1.645.
_COERCE = re.compile(r"(^|[^\d])(\d{1,16})(?:\.(\d{1,16}))?(?:\.(\d{1,16}))?(?:$|[^\d])")

_Version = tuple[int, int, int]


def compare_semver(value: str, operator: str, target_values: list[str]) -> bool:
    lowercase_operator = operator.lower()
    if not value.strip():
        return lowercase_operator == "is not one of"

    parsed_value = _coerce(value)
    targets = [_coerce(target) for target in target_values]
    first = targets[0] if targets else None

    match lowercase_operator:
        case "=":
            return _equals(parsed_value, first)
        case "<":
            return _ordered(parsed_value, first, lambda a, b: a < b)
        case "<=":
            return _ordered(parsed_value, first, lambda a, b: a <= b)
        case ">":
            return _ordered(parsed_value, first, lambda a, b: a > b)
        case ">=":
            return _ordered(parsed_value, first, lambda a, b: a >= b)
        case "is one of":
            return any(_equals(parsed_value, target) for target in targets)
        case "is not one of":
            return not any(_equals(parsed_value, target) for target in targets)
        case _:
            return False


def _coerce(value: str) -> _Version | None:
    match = _COERCE.search(value)
    if match is None:
        return None
    return (int(match.group(2)), int(match.group(3) or 0), int(match.group(4) or 0))


def _equals(value: _Version | None, target: _Version | None) -> bool:
    return value is not None and target is not None and value == target


def _ordered(
    value: _Version | None,
    target: _Version | None,
    compare: Callable[[_Version, _Version], bool],
) -> bool:
    # An operand that could not be coerced never satisfies an ordering comparison.
    if value is None or target is None:
        return False
    return compare(value, target)
