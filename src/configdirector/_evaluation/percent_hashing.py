from __future__ import annotations

from ._rapidhash import rapidhash

__all__ = ["assign_percentage"]

_SEED = 0x397832987


def assign_percentage(config_id: str, context_identifier: str) -> float:
    value = f"{context_identifier}-{config_id}"
    return float(rapidhash(value.encode("utf-8"), _SEED) % 1_000) / 10.0
