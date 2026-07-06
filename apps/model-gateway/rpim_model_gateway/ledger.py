"""Per-tenant usage/cost ledger (CLAUDE.md: every model call records tokens
and cost). Redis list per tenant; in-memory fallback keeps tests and degraded
mode alive. Read side powers GET /ledger/{tenant_id}."""

import json
import os
import sys
import time

_MEMORY: list[dict] = []  # fallback when Redis is unavailable (tests/degraded)


def record(
    tenant_id: str | None,
    task: str,
    model: str,
    units: int,
    provider: str | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
) -> None:
    entry = {
        "ts": int(time.time()),
        "tenant_id": tenant_id or "unknown",
        "task": task,
        "provider": provider,
        "model": model,
        "units": units,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost_usd, 8),
    }
    url = os.environ.get("REDIS_URL", "")
    if url:
        try:
            import redis

            redis.Redis.from_url(url).lpush(
                f"rpim:ledger:{entry['tenant_id']}", json.dumps(entry)
            )
            return
        except Exception as exc:  # noqa: BLE001 — ledger must never break the call path
            print(f"ledger: redis unavailable ({exc}); falling back to memory", file=sys.stderr)
    _MEMORY.append(entry)


def entries_for(tenant_id: str, limit: int = 200) -> list[dict]:
    url = os.environ.get("REDIS_URL", "")
    if url:
        try:
            import redis

            raw = redis.Redis.from_url(url).lrange(f"rpim:ledger:{tenant_id}", 0, limit - 1)
            return [json.loads(x) for x in raw]
        except Exception as exc:  # noqa: BLE001
            print(f"ledger: redis unavailable ({exc}); reading memory", file=sys.stderr)
    return [e for e in _MEMORY if e["tenant_id"] == tenant_id][-limit:]
