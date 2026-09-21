from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from configdirector._telemetry.compact_json import to_compact_json


class TestToCompactJson:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, "null"),
            (True, "true"),
            (False, "false"),
            (26, "26"),
            (26.0, "26"),  # JSON.stringify writes a whole number without a fractional part
            (1.5, "1.5"),
            (float("nan"), "null"),  # JSON cannot spell NaN, and JSON.stringify writes null
            (float("inf"), "null"),
            ("text", '"text"'),
            ('quote " and \\ and \n', '"quote \\" and \\\\ and \\n"'),
            ("café", '"café"'),  # not escaped to é, which would change the digest
            ([], "[]"),
            ({}, "{}"),
            ([1, "two", True, None], '[1,"two",true,null]'),
            ({"a": 1, "b": 2}, '{"a":1,"b":2}'),  # no space after ":" or ","
            ({"nested": {"list": [1.0, {"deep": False}]}}, '{"nested":{"list":[1,{"deep":false}]}}'),
        ],
    )
    def test_serializes_like_json_stringify(self, value: Any, expected: str) -> None:
        assert to_compact_json(value) == expected

    def test_preserves_key_order_rather_than_sorting(self) -> None:
        assert to_compact_json({"b": 1, "a": 2}) == '{"b":1,"a":2}'

    def test_rejects_a_value_json_cannot_represent(self) -> None:
        with pytest.raises(TypeError):
            to_compact_json({"when": datetime(2026, 1, 1, tzinfo=timezone.utc)})
