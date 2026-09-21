from __future__ import annotations

import hashlib

__all__ = ["VALUE_ID_LENGTH", "generate_value_id"]

# How many bytes of the digest make up a value ID.
_DIGEST_BYTES = 16

# ceil(128 / log2(62)): the number of base62 digits _DIGEST_BYTES can produce.
VALUE_ID_LENGTH = 22

_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def generate_value_id(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).digest()[:_DIGEST_BYTES]
    return _to_base62(int.from_bytes(digest, "big"))


# Hand-rolled rather than taken from a base62 package: the encoding ConfigDirector uses is
# fixed-width and zero-padded, where the packages on PyPI encode leading zero bytes as their own
# digit. Borrowing one would quietly produce identifiers no other SDK agrees with, for what is
# otherwise two lines of integer arithmetic.
def _to_base62(number: int) -> str:
    digits: list[str] = []
    while number > 0:
        number, remainder = divmod(number, 62)
        digits.append(_BASE62[remainder])
    return "".join(reversed(digits)).rjust(VALUE_ID_LENGTH, "0")
