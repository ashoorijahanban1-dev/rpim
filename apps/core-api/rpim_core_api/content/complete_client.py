import os


def complete(
    prompt: str,
    system: str | None = None,
    tenant_id: str | None = None,
    task: str = "t1",
    request_id: str | None = None,
) -> str:
    """All completions go through the gateway (CLAUDE.md). COMPLETE_MODE=fake
    keeps tests/CI offline with a deterministic draft that embeds the system
    prompt and retrieved context — so RAG-reaches-output is provable."""
    mode = os.environ.get("COMPLETE_MODE", "remote")
    if mode == "fake":
        return f"[fake-draft] {system or ''}\n---\n{prompt[:2000]}"

    import httpx

    gateway = os.environ.get("GATEWAY_URL", "")
    if not gateway:
        raise RuntimeError("GATEWAY_URL is not set (env only)")
    response = httpx.post(
        f"{gateway.rstrip('/')}/complete",
        json={
            "task": task,
            "prompt": prompt,
            "system": system,
            "tenant_id": tenant_id,
            "request_id": request_id,
        },
        headers={"X-Internal-Token": os.environ.get("INTERNAL_TOKEN", "")},
        timeout=180,
    )
    response.raise_for_status()
    return response.json()["text"]
