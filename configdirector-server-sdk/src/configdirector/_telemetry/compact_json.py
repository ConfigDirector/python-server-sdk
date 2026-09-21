from __future__ import annotations

import json
import math
from typing import Any

from .._evaluation._json_value import to_json_string

__all__ = ["to_compact_json"]


# Serializes to JSON byte-for-byte the way the other ConfigDirector SDKs do. A value too large
# to report inline is identified by the digest of its JSON form, so the same document has to
# serialize identically everywhere or one value would be counted as two. Plain json.dumps would
# not: it puts a space after every ":" and ",", escapes non-ASCII characters, and writes a whole
# float as "1.0" where every other SDK writes "1". Each of those changes the digest, so numbers
# go through to_json_string — the same rendering the evaluator uses — and the rest is spelled
# out here. Raises TypeError on anything JSON cannot represent; callers decide what to do.
def to_compact_json(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # JSON has no way to spell NaN or infinity, and JSON.stringify writes null for both.
        return to_json_string(value) if math.isfinite(value) else "null"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return f"[{','.join(to_compact_json(item) for item in value)}]"
    if isinstance(value, dict):
        members = (
            f"{json.dumps(str(key), ensure_ascii=False)}:{to_compact_json(member)}"
            for key, member in value.items()
        )
        return f"{{{','.join(members)}}}"

    raise TypeError(f"Object of type '{type(value).__name__}' is not JSON serializable")
