import os

# One request per ≤32 texts: a 300-chunk PDF in a single call blew the 15s
# cross-leg timeout in production (CPU embedding of the whole catalog).
# Batches keep each call far under the timeout while a dead path still
# fails fast on the first batch.
BATCH_SIZE = 32
TIMEOUT_S = 30


def embed_texts(texts: list[str], tenant_id: str | None = None) -> list[list[float]]:
    """All model calls go through the gateway (CLAUDE.md): EMBED_MODE=remote
    posts to {GATEWAY_URL}/embed with the cross-leg INTERNAL_TOKEN.
    EMBED_MODE=fake keeps tests/CI network-free with the shared fake."""
    mode = os.environ.get("EMBED_MODE", "remote")
    if mode == "fake":
        from rpim_shared import fake_embed

        return [fake_embed(t) for t in texts]

    import httpx

    gateway = os.environ.get("GATEWAY_URL", "")
    if not gateway:
        raise RuntimeError("GATEWAY_URL is not set (env only)")
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        response = httpx.post(
            f"{gateway.rstrip('/')}/embed",
            json={"texts": batch, "tenant_id": tenant_id},
            headers={"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")},
            timeout=TIMEOUT_S,
        )
        response.raise_for_status()
        vectors.extend(response.json()["vectors"])
    return vectors
