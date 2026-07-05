"""Per-tenant usage ledger — M2 minimal form (Redis list; in-memory fallback
for tests). M3's gateway milestone upgrades this to the full cost ledger with
tokens+cost per call. Every model call MUST be recorded (CLAUDE.md)."""

import json
import os
import sys
import time

_MEMORY: list[dict] = []  # test/inspection fallback when Redis is unavailable


def record(tenant_id: str | None, task: str, model: str, units: int) -> None:
    entry = {
        "ts": int(time.time()),
        "tenant_id": tenant_id or "unknown",
        "task": task,
        "model": model,
        "units": units,
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
