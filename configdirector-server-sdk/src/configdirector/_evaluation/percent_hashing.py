from __future__ import annotations

from .._context_kind import DEFAULT_KIND
from ._rapidhash import rapidhash

__all__ = ["PERCENTAGE_WITHOUT_IDENTIFIER", "assign_percentage"]

_SEED = 0x397832987

PERCENTAGE_WITHOUT_IDENTIFIER = 0.0


def assign_percentage(config_id: str, context_identifier: str, context_kind: str) -> float:
    value = _hash_input(config_id, context_identifier, context_kind)
    return float(rapidhash(value.encode("utf-8"), _SEED) % 1_000) / 10.0


def _hash_input(config_id: str, context_identifier: str, context_kind: str) -> str:
    user_kind_input = f"{context_identifier}-{config_id}"
    if context_kind == DEFAULT_KIND:
        return user_kind_input
    return f"{user_kind_input}:{context_kind}"
