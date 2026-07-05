import hashlib
import math
import random


def fake_embed(text: str, dim: int = 1024) -> list[float]:
    """Deterministic pseudo-embedding for tests/CI and the gateway's fake
    backend: same text → identical L2-normalized vector. NOT semantic —
    production uses bge-m3 behind the model gateway (T3)."""
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    vector = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]
