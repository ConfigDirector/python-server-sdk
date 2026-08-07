from __future__ import annotations

from typing import Any

from ..types import Context, Metadata
from ._json_pointer import find_by_pointer
from ._json_value import to_json_string
from .array_comparison import compare_array
from .date_comparison import compare_date
from .numeric_comparison import compare_numeric
from .semver_comparison import compare_semver
from .text_comparison import compare_text
from .types import Condition, EvaluationContext

__all__ = ["evaluate_condition"]

# The context does not carry this attribute. It is compared as "" rather than skipped, so that a
# negative operator such as "does NOT equal" can still match.
_ABSENT = object()

# The condition names an attribute this SDK version does not know about. Unlike an absent value,
# it is not compared at all — there is no sensible thing to compare.
_UNKNOWN_ATTRIBUTE = object()

_EMPTY_CONTEXT = Context()
_EMPTY_METADATA = Metadata()


def evaluate_condition(condition: Condition, context: EvaluationContext | None = None) -> bool:
    value = _resolve(condition, context)
    if value is _UNKNOWN_ATTRIBUTE:
        return False

    targets = condition.target_values or []

    match condition.target_type:
        case "text":
            return compare_text(_render(value), condition.operator, targets)
        case "number":
            return compare_numeric(_unwrap(value), condition.operator, targets)
        case "datetime":
            return compare_date(_render(value), condition.operator, targets)
        case "semver":
            return compare_semver(_render(value), condition.operator, targets)
        case "array":
            return compare_array(_unwrap(value), condition.operator, targets)
        case _:
            return False


def _resolve(condition: Condition, context: EvaluationContext | None) -> Any:
    match condition.attribute:
        case "identifier":
            return _or_absent(_context_of(context).id)
        case "name":
            return _or_absent(_context_of(context).name)
        case "appName":
            return _or_absent(_metadata_of(context).app_name)
        case "appVersion":
            return _or_absent(_metadata_of(context).app_version)
        case "traits":
            if not condition.trait:
                return _ABSENT
            return _or_absent(find_by_pointer(condition.trait, _context_of(context).traits))
        case _:
            return _UNKNOWN_ATTRIBUTE


def _context_of(context: EvaluationContext | None) -> Context:
    if context is None or context.context is None:
        return _EMPTY_CONTEXT
    return context.context


def _metadata_of(context: EvaluationContext | None) -> Metadata:
    if context is None or context.metadata is None:
        return _EMPTY_METADATA
    return context.metadata


def _or_absent(value: Any) -> Any:
    return _ABSENT if value is None else value


def _unwrap(value: Any) -> Any:
    return None if value is _ABSENT else value


def _render(value: Any) -> str:
    if value is _ABSENT or value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return to_json_string(value)
    return ""  # arrays and objects
