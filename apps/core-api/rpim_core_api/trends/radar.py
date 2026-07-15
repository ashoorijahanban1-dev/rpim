"""Trend Radar source (M14) — رادار ایده‌ی محتوا.

TRENDS_MODE=fake (default, tests/CI/pilot) produces a DETERMINISTIC simulated
batch seeded by the tenant id + its brand lexicon, so each brand gets a
stable, relevant-looking radar without network access. live mode is the
فاز ۲ slice (real Iranian-market source layers) — until it exists it fails
loudly naming its env var, never silently faking.
"""

import hashlib
import os


class TrendSourceError(Exception):
    """Trend source unavailable/misconfigured — refresh skips, radar keeps
    its previous batch (rule 8: a failed poll must not wipe state)."""


BATCH_SIZE = 8

# Persian marketing angles the simulator combines with brand lexicon terms.
_ANGLES = (
    "قیمت {kw}",
    "خرید {kw}",
    "مقایسه {kw}",
    "بهترین {kw} ۱۴۰۵",
    "آموزش {kw}",
    "تخفیف {kw}",
    "نقد و بررسی {kw}",
    "ترند {kw}",
)


def fetch_trends(tenant_id: str, lexicon: list[str]) -> list[dict]:
    """Return [{keyword, score}] — exactly BATCH_SIZE rows."""
    mode = os.environ.get("TRENDS_MODE", "fake")
    if mode == "fake":
        seeds = [term for term in lexicon if term.strip()] or [f"برند {tenant_id[:6]}"]
        batch: list[dict] = []
        for index, angle in enumerate(_ANGLES[:BATCH_SIZE]):
            term = seeds[index % len(seeds)]
            keyword = angle.format(kw=term)
            digest = hashlib.sha256(f"{tenant_id}:{keyword}".encode()).digest()
            batch.append({"keyword": keyword, "score": digest[0] * 100 // 255})
        return batch
    if mode != "live":
        raise TrendSourceError("TRENDS_MODE must be 'fake' or 'live'")
    source_url = os.environ.get("TRENDS_SOURCE_URL", "")
    if not source_url:
        # Name the env var, never a value (rule 4).
        raise TrendSourceError("missing config: env var TRENDS_SOURCE_URL is not set")
    raise TrendSourceError("live trend sources are the فاز ۲ slice — not wired yet")
