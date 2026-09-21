"""Vectors pinning the rapidhash port against the reference implementation.

The inputs deliberately cover every branch of the algorithm: each short-input length, the 16- and
17-byte boundary, the 112-byte block loop and its remainder cases, and multi-byte UTF-8.
"""

from __future__ import annotations

import pytest

from configdirector._evaluation._rapidhash import rapidhash

SEED = 0x397832987

VECTORS = [
    ("", 5377612543505373799),
    ("a", 7674800498429868151),
    ("ab", 12048270741005468339),
    ("abc", 8205525400821834274),
    ("abcd", 2559843570930408943),
    ("abcde", 17182111687207956362),
    ("abcdefg", 13135472276134024436),
    ("abcdefgh", 10825195283420988801),
    ("abcdefghi", 9324307379318471710),
    ("0123456789abcdef", 8410398172536096822),
    ("0123456789abcdefg", 8975841632926530338),
    ("10-11111111-1111-4111-8111-111111111111", 7715065197445012089),
    ("x" * 48, 1185046273860983588),
    ("y" * 112, 5679430438346846087),
    ("z" * 113, 14103938338420400619),
    ("w" * 240, 15088383192705595115),
    ("héllo wörld ✓", 7481766294562949397),
]


@pytest.mark.parametrize(("message", "expected"), VECTORS, ids=lambda v: str(v)[:24])
def test_matches_the_reference_implementation(message: str, expected: int) -> None:
    assert rapidhash(message.encode("utf-8"), SEED) == expected


def test_always_produces_a_64_bit_value() -> None:
    for message, _ in VECTORS:
        assert 0 <= rapidhash(message.encode("utf-8"), SEED) <= 0xFFFFFFFFFFFFFFFF


def test_the_seed_changes_the_result() -> None:
    assert rapidhash(b"abc", SEED) != rapidhash(b"abc", SEED + 1)
    assert rapidhash(b"abc", 0) != rapidhash(b"abc", SEED)
