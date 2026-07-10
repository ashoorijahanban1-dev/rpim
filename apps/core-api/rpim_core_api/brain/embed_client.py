import os


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
    response = httpx.post(
        f"{gateway.rstrip('/')}/embed",
        json={"texts": texts, "tenant_id": tenant_id},
        headers={"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")},
        timeout=15,  # fail fast — a dead cross-leg path must not hang requests for a minute
    )
    response.raise_for_status()
    return response.json()["vectors"]
