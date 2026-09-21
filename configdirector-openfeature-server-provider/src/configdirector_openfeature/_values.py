from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

__all__ = ["to_plain"]


def to_plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): to_plain(entry) for key, entry in value.items()}
    if isinstance(value, (str, bytes)):
        return value
    if isinstance(value, Sequence):
        return [to_plain(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value
