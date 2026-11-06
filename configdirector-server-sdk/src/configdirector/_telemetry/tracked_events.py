from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from ..types import Context, TrackedEventDetails
from .compact_json import to_compact_json
from .reported_context import reported_context_of

__all__ = [
    "TRACKED_EVENTS_PER_BATCH",
    "TRACKED_EVENT_WARNING_MESSAGES",
    "TrackedEventAdmission",
    "TrackedEventAdmitted",
    "TrackedEventDropped",
    "TrackedEventEntry",
    "TrackedEventWarning",
    "admit_tracked_event",
    "number_as_json",
]

TRACKED_EVENTS_PER_BATCH = 1_000
_NAME_MAXIMUM_CHARACTERS = 150
_DETAILS_MAXIMUM_TOP_LEVEL_KEYS = 20
_DETAILS_MAXIMUM_JSON_BYTES = 1_024

TrackedEventWarning = Literal[
    "name-outside-the-character-limit",
    "value-not-a-finite-number",
    "details-not-reportable",
    "batch-already-full",
]

TRACKED_EVENT_WARNING_MESSAGES: dict[TrackedEventWarning, str] = {
    "name-outside-the-character-limit": (
        "A tracked event was not reported because its name does not have "
        f"1 to {_NAME_MAXIMUM_CHARACTERS} characters."
    ),
    "value-not-a-finite-number": (
        "A tracked event was reported without its value because the value is not a finite number."
    ),
    "details-not-reportable": (
        "A tracked event was reported without its details because they are not an object, have more "
        f"than {_DETAILS_MAXIMUM_TOP_LEVEL_KEYS} top-level keys, are larger than "
        f"{_DETAILS_MAXIMUM_JSON_BYTES} bytes as JSON, or cannot be written as JSON."
    ),
    "batch-already-full": (
        f"A tracked event was not reported because {TRACKED_EVENTS_PER_BATCH} tracked events are already "
        "waiting for the next telemetry batch."
    ),
}


@dataclass(frozen=True, slots=True)
class TrackedEventEntry:
    name: str
    happened_at: datetime
    context_kind: str | None = None
    context_identifier: str | None = None
    value: int | float | Decimal | None = None
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class TrackedEventAdmitted:
    entry: TrackedEventEntry
    context: Context | None
    warnings: tuple[TrackedEventWarning, ...]


@dataclass(frozen=True, slots=True)
class TrackedEventDropped:
    warnings: tuple[TrackedEventWarning, ...]


TrackedEventAdmission = TrackedEventAdmitted | TrackedEventDropped


def admit_tracked_event(
    *,
    name: str,
    context: Context | None,
    value: int | float | Decimal | None,
    details: TrackedEventDetails | None,
    happened_at: datetime,
) -> TrackedEventAdmission:
    if not _is_within_the_character_limit(name):
        return TrackedEventDropped(warnings=("name-outside-the-character-limit",))

    context_kind, context_identifier = reported_context_of(context) or (None, None)
    reportable_value, value_warnings = _reportable_value_of(value)
    reportable_details, details_warnings = _reportable_details_of(details)
    return TrackedEventAdmitted(
        entry=TrackedEventEntry(
            name=name,
            happened_at=happened_at,
            context_kind=context_kind,
            context_identifier=context_identifier,
            value=reportable_value,
            details=reportable_details,
        ),
        context=context,
        warnings=(*value_warnings, *details_warnings),
    )


def _is_within_the_character_limit(name: object) -> bool:
    return isinstance(name, str) and 1 <= len(name) <= _NAME_MAXIMUM_CHARACTERS


def _reportable_value_of(
    value: int | float | Decimal | None,
) -> tuple[int | float | Decimal | None, tuple[TrackedEventWarning, ...]]:
    if value is None:
        return None, ()
    try:
        is_reportable = number_as_json(value) is not None
    except ValueError:
        is_reportable = False
    return (value, ()) if is_reportable else (None, ("value-not-a-finite-number",))


def _reportable_details_of(
    details: TrackedEventDetails | None,
) -> tuple[dict[str, Any] | None, tuple[TrackedEventWarning, ...]]:
    if details is None:
        return None, ()
    copy = _json_copy_within_the_limits(details)
    return (copy, ()) if copy is not None else (None, ("details-not-reportable",))


def _json_copy_within_the_limits(details: object) -> dict[str, Any] | None:
    if not isinstance(details, Mapping):
        return None
    try:
        written_details = to_compact_json(_with_plain_containers(details))
        if len(written_details.encode("utf-8")) > _DETAILS_MAXIMUM_JSON_BYTES:
            return None
        copy: dict[str, Any] = json.loads(written_details)
    except Exception:
        return None
    return copy if len(copy) <= _DETAILS_MAXIMUM_TOP_LEVEL_KEYS else None


def _with_plain_containers(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _with_plain_containers(member) for key, member in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_with_plain_containers(item) for item in value]
    return value


def number_as_json(value: object) -> str | None:
    match value:
        case bool():
            return None
        case Decimal():
            return str(value) if value.is_finite() else None
        case int():
            return json.dumps(value)
        case float():
            return json.dumps(value) if math.isfinite(value) else None
        case _:
            return None
