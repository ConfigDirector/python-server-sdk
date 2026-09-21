from __future__ import annotations

import pytest

from configdirector._telemetry.value_id import VALUE_ID_LENGTH, generate_value_id

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


class TestGenerateValueId:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            # Taken from the JavaScript SDK's suite: every SDK has to agree on these, or the same
            # config value would be counted as two different ones in the dashboard.
            ("hello", "1MoOW7eqAPjhZeoELVwO9G"),
            ("world", "2Cg0gndCS8p6nDE5aa6LcI"),
            ("42", "3VWjGpOwynZPh07ivDC56c"),
            ("", "6ve2WrOl3mnciB6WIL2fIa"),
        ],
    )
    def test_matches_the_other_sdks(self, value: str, expected: str) -> None:
        assert generate_value_id(value) == expected

    @pytest.mark.parametrize("value", ["", "x", "a much longer value " * 100, "unicode ☂ café"])
    def test_is_always_the_same_length(self, value: str) -> None:
        assert len(generate_value_id(value)) == VALUE_ID_LENGTH

    def test_uses_only_base62_characters(self) -> None:
        assert set(generate_value_id("hello")) <= set(BASE62)

    def test_is_deterministic(self) -> None:
        assert generate_value_id("my-value") == generate_value_id("my-value")

    def test_different_values_produce_different_ids(self) -> None:
        assert generate_value_id("value-a") != generate_value_id("value-b")

    def test_hashes_the_utf8_encoding(self) -> None:
        # A digest taken over some other encoding would not match the other SDKs.
        assert generate_value_id("café") != generate_value_id("cafe")
