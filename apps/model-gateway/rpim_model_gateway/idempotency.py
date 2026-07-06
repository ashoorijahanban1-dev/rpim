"""Response cache for cross-leg idempotency (rule 8): a retried /complete
carrying the same request_id returns the stored response — no second provider
call, no duplicate ledger charge. Redis with TTL; bounded in-memory fallback."""

import json
import os
import sys
from collections import OrderedDict

TTL_SECONDS = 3600
_MEMORY: OrderedDict[str, dict] = OrderedDict()
_MEMORY_MAX = 512


def get(request_id: str) -> dict | None:
    url = os.environ.get("REDIS_URL", "")
    if url:
        try:
            import redis

            raw = redis.Redis.from_url(url).get(f"rpim:idem:{request_id}")
            return json.loads(raw) if raw else None
        except Exception as exc:  # noqa: BLE001 — cache must never break the call path
            print(f"idempotency: redis unavailable ({exc}); using memory", file=sys.stderr)
    return _MEMORY.get(request_id)


def put(request_id: str, payload: dict) -> None:
    url = os.environ.get("REDIS_URL", "")
    if url:
        try:
            import redis

            redis.Redis.from_url(url).setex(
                f"rpim:idem:{request_id}", TTL_SECONDS, json.dumps(payload)
            )
            return
        except Exception as exc:  # noqa: BLE001
            print(f"idempotency: redis unavailable ({exc}); using memory", file=sys.stderr)
    _MEMORY[request_id] = payload
    while len(_MEMORY) > _MEMORY_MAX:
        _MEMORY.popitem(last=False)
