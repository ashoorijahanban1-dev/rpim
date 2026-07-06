"""Per-tenant cost entries from the us-leg gateway ledger.

LEDGER_MODE=fake (tests/CI) returns a deterministic entry; remote mode calls
the gateway over the tunnel with the internal token. The ledger is a running
total — month-slicing lands when the gateway stamps entries with timestamps.
"""

import os

import httpx


def fetch_entries(tenant_id: str) -> list[dict]:
    mode = os.environ.get("LEDGER_MODE", "fake")
    if mode == "fake":
        return [{"provider": "fake", "tokens": 125, "cost_usd": 0.0125}]

    gateway = os.environ.get("GATEWAY_URL", "")
    if not gateway:
        # Name the env var, never a value (rule 4).
        raise RuntimeError("LEDGER_MODE=remote requires env var GATEWAY_URL")
    internal = os.environ.get("INTERNAL_TOKEN", "")
    response = httpx.get(
        f"{gateway.rstrip('/')}/ledger/{tenant_id}",
        headers={"X-Internal-Token": internal},
        timeout=15,
    )
    response.raise_for_status()
    return response.json().get("entries", [])
