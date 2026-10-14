from __future__ import annotations

import string

from .types import Context

__all__ = ["DEFAULT_KIND", "effective_kind", "is_valid_kind", "kind_sample"]

DEFAULT_KIND = "user"

_KIND_CHARACTERS = frozenset(string.ascii_lowercase + string.digits + "-_")
_MAXIMUM_KIND_LENGTH = 64
_MAXIMUM_KIND_SAMPLE_LENGTH = 128


def effective_kind(context: Context | None) -> str:
    if context is None or context.kind is None:
        return DEFAULT_KIND
    return context.kind


def is_valid_kind(kind: object) -> bool:
    return (
        isinstance(kind, str)
        and 0 < len(kind) <= _MAXIMUM_KIND_LENGTH
        and all(character in _KIND_CHARACTERS for character in kind)
    )


def kind_sample(kind: object) -> str:
    text = kind if isinstance(kind, str) else _text_of(kind)
    return text[:_MAXIMUM_KIND_SAMPLE_LENGTH]


def _text_of(kind: object) -> str:
    try:
        return str(kind)
    except Exception:
        return type(kind).__name__
