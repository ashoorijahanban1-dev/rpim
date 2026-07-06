"""Rendering backends.

RENDER_MODE=fake (tests/CI, committed default) produces a deterministic
in-process PNG with the exact target dimensions — no browser, no network —
so cross-leg render jobs stay idempotent and CI needs no Chromium. The real
Chromium screenshot path is slice B.
"""

import hashlib
import struct
import zlib


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def fake_png(width: int, height: int, seed: str) -> bytes:
    """Valid width×height RGB PNG, solid color derived from the seed."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    row = b"\x00" + bytes(digest[i % 3] for i in range(3)) * width
    raw = row * height
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )
