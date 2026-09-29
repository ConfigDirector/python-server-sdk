"""Minimal RFC 6901 JSON Pointer resolution, used to read nested context traits."""

from __future__ import annotations

import re
from typing import Any

__all__ = ["find_by_pointer"]

_MISSING = object()
_ARRAY_INDEX = re.compile(r"0|[1-9][0-9]*")
_INVALID_ESCAPE = re.compile(r"~(?![01])")


def find_by_pointer(pointer: str, document: Any) -> Any:
    if not pointer.startswith("/"):
        return None

    current = document
    for raw_token in pointer[1:].split("/"):
        if _INVALID_ESCAPE.search(raw_token):
            return None
        token = raw_token.replace("~1", "/").replace("~0", "~")
        current = _step(current, token)
        if current is _MISSING:
            return None
    return current


def _step(current: Any, token: str) -> Any:
    if isinstance(current, dict):
        return current.get(token, _MISSING)
    if isinstance(current, list):
        if not _ARRAY_INDEX.fullmatch(token):
            return _MISSING
        index = int(token)
        if index >= len(current):
            return _MISSING
        return current[index]
    return _MISSING
