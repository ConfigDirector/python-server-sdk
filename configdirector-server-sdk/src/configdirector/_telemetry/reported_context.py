from __future__ import annotations

from .._context_kind import effective_kind
from ..types import Context

__all__ = ["reported_context_of"]


def reported_context_of(context: Context | None) -> tuple[str, str] | None:
    if context is None or not context.id or context.anonymous:
        return None
    return effective_kind(context), context.id
