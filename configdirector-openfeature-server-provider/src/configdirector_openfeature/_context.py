from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from configdirector import Context
from openfeature.evaluation_context import EvaluationContext

from ._values import to_plain

__all__ = ["to_context"]


def to_context(evaluation_context: EvaluationContext | None) -> Context | None:
    if evaluation_context is None:
        return None

    attributes = evaluation_context.attributes
    traits = attributes.get("traits")
    anonymous = attributes.get("anonymous")

    return Context(
        id=_identifier(evaluation_context),
        name=_text(attributes.get("name")),
        traits=to_plain(traits) if isinstance(traits, Mapping) and traits else None,
        anonymous=anonymous if isinstance(anonymous, bool) else False,
    )


def _identifier(evaluation_context: EvaluationContext) -> str | None:
    if evaluation_context.targeting_key is not None:
        return evaluation_context.targeting_key
    return _text(evaluation_context.attributes.get("id"))


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, Mapping):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(to_plain(value))
