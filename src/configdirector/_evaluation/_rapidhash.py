"""A pure-Python port of rapidhash v3.0 ("fast" variant).

Percentage rollouts bucket users by hashing, so every ConfigDirector SDK must produce the exact
same 64-bit value for the same input or the same user would land in different buckets depending
on which SDK evaluated the config.

Do not "clean up" the arithmetic here. Every mask and shift is load-bearing.
"""

from __future__ import annotations

__all__ = ["rapidhash"]

_MASK64 = 0xFFFFFFFFFFFFFFFF

_SECRET = (
    0x2D358DCCAA6C78A5,
    0x8BB84B93962EACC9,
    0x4B33A62ED433D4A3,
    0x4D5A2DA51DE1AA47,
    0xA0761D6478BD642F,
    0xE7037ED1A0B428DB,
    0x90ED1765281C388C,
    0xAAAAAAAAAAAAAAAA,
)


def _mix(a: int, b: int) -> int:
    m = a * b
    return (m & _MASK64) ^ (m >> 64)


def _read64(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 8], "little")


def _read32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def _read_small(data: bytes, length: int) -> int:
    v = data[0]
    return data[length - 1] | (((v << 5) & 0xFF) << 40) | ((v >> 3) << 48)


def _epilogue(a: int, b: int, i: int) -> int:
    m0 = a * b
    m1 = ((m0 & _MASK64) ^ _SECRET[7]) * (((m0 >> 64) ^ _SECRET[1] ^ i) & _MASK64)
    return (m1 & _MASK64) ^ (m1 >> 64)


def rapidhash(data: bytes, seed: int = 0) -> int:
    length = len(data)
    seed ^= _mix(seed ^ _SECRET[2], _SECRET[1])
    i = length

    if length <= 16:
        bi = length
        if length >= 4:
            seed ^= length
            if length >= 8:
                a = _read64(data, 0)
                b = _read64(data, length - 8)
            else:
                a = _read32(data, 0)
                b = _read32(data, length - 4)
        elif length > 0:
            a = _read_small(data, length)
            b = data[length >> 1]
        else:
            a = 0
            b = 0
    else:
        p = 0
        if i > 112:
            see1 = see2 = see3 = see4 = see5 = see6 = seed
            while True:
                seed = _mix(_read64(data, p) ^ _SECRET[0], _read64(data, p + 8) ^ seed)
                see1 = _mix(_read64(data, p + 16) ^ _SECRET[1], _read64(data, p + 24) ^ see1)
                see2 = _mix(_read64(data, p + 32) ^ _SECRET[2], _read64(data, p + 40) ^ see2)
                see3 = _mix(_read64(data, p + 48) ^ _SECRET[3], _read64(data, p + 56) ^ see3)
                see4 = _mix(_read64(data, p + 64) ^ _SECRET[4], _read64(data, p + 72) ^ see4)
                see5 = _mix(_read64(data, p + 80) ^ _SECRET[5], _read64(data, p + 88) ^ see5)
                see6 = _mix(_read64(data, p + 96) ^ _SECRET[6], _read64(data, p + 104) ^ see6)
                p += 112
                i -= 112
                if i <= 112:
                    break
            seed ^= see1
            see2 ^= see3
            see4 ^= see5
            seed ^= see6
            see2 ^= see4
            seed ^= see2

        bi = i
        if i > 16:
            seed = _mix(_read64(data, p) ^ _SECRET[2], _read64(data, p + 8) ^ seed)
            if i > 32:
                seed = _mix(_read64(data, p + 16) ^ _SECRET[2], _read64(data, p + 24) ^ seed)
                if i > 48:
                    seed = _mix(_read64(data, p + 32) ^ _SECRET[1], _read64(data, p + 40) ^ seed)
                    if i > 64:
                        seed = _mix(_read64(data, p + 48) ^ _SECRET[1], _read64(data, p + 56) ^ seed)
                        if i > 80:
                            seed = _mix(_read64(data, p + 64) ^ _SECRET[2], _read64(data, p + 72) ^ seed)
                            if i > 96:
                                seed = _mix(_read64(data, p + 80) ^ _SECRET[1], _read64(data, p + 88) ^ seed)

        a = _read64(data, p + i - 16) ^ bi
        b = _read64(data, p + i - 8)

    a ^= _SECRET[1]
    b ^= seed
    return _epilogue(a, b, bi)
