"""Rendering config values to strings the way the other ConfigDirector SDKs do.

Config values arrive as JSON and are handed back to the client as strings, so a boolean must
render as ``true`` rather than Python's ``True``, and a whole number as ``26`` rather than
``26.0``. Getting this wrong would make the same config resolve to different text depending on
which SDK read it.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = ["to_json_string"]


def to_json_string(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        # JSON numbers have no int/float distinction, so 26.0 must render as "26".
        if value.is_integer() and abs(value) < 1e21:
            return str(int(value))
    return str(value)
