"""Minimal RFC 6901 JSON Pointer resolution, used to read nested context traits."""

from __future__ import annotations

from typing import Any

__all__ = ["find_by_pointer"]

_MISSING = object()


def find_by_pointer(pointer: str, document: Any) -> Any:
    if not pointer.startswith("/"):
        # Includes the empty pointer, which RFC 6901 defines as the whole document. Callers
        # treat an empty trait path as "no trait", so it never reaches here.
        return None

    current = document
    for raw_token in pointer[1:].split("/"):
        # Unescape in this order: ~1 before ~0, so that "~01" resolves to "~1" and not "/".
        token = raw_token.replace("~1", "/").replace("~0", "~")
        current = _step(current, token)
        if current is _MISSING:
            return None
    return current


def _step(current: Any, token: str) -> Any:
    if isinstance(current, dict):
        return current.get(token, _MISSING)
    if isinstance(current, (list, tuple)):
        try:
            index = int(token)
        except ValueError:
            return _MISSING
        # RFC 6901 array indexes are unsigned; Python's negative indexing must not leak in.
        if index < 0 or index >= len(current):
            return _MISSING
        return current[index]
    return _MISSING
