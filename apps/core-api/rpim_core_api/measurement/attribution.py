"""Tenant-keyed click attribution (M22 slice A, ADR 0041).

campaign_code is a free tenant-chosen string on a SHARED analytics site, so
counts keyed by campaign alone would bleed across brands (the review's
rule-6 finding). Every job therefore stamps utm_id = "t-" + tenant_id[:12],
and this module reads clicks FILTERED by that key: METRICS_MODE=fake serves
tests/CI via the _FAKE_UTM_CLICKS seam; umami mode queries the shared site
with a utm_id filter. Missing env NAMES the var (rule 4)."""

import os
from datetime import datetime, timedelta

import httpx

from rpim_shared.tz import app_timezone

# Fake seam: {utm_id: {campaign_code: clicks}} for "today".
_FAKE_UTM_CLICKS: dict[str, dict[str, int]] = {}


def tenant_key(tenant_id: str) -> str:
    return f"t-{tenant_id[:12]}"


def _day_window_ms(day: str) -> tuple[int, int]:
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=app_timezone())
    end = start + timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def fetch_tenant_clicks(utm_id: str, day: str) -> dict[str, int]:
    """Clicks per campaign_code for ONE tenant's utm_id on `day` (app-TZ)."""
    mode = os.environ.get("METRICS_MODE", "fake")
    if mode == "fake":
        return dict(_FAKE_UTM_CLICKS.get(utm_id, {}))
    if mode != "umami":
        raise RuntimeError("METRICS_MODE must be 'fake' or 'umami'")

    url = os.environ.get("UMAMI_URL", "")
    site = os.environ.get("UMAMI_SITE_ID", "")
    key = os.environ.get("UMAMI_API_KEY", "")
    for name, value in (
        ("UMAMI_URL", url),
        ("UMAMI_SITE_ID", site),
        ("UMAMI_API_KEY", key),
    ):
        if not value:
            # Name the env var, never a value (rule 4).
            raise RuntimeError(f"METRICS_MODE=umami requires env var {name}")

    start_ms, end_ms = _day_window_ms(day)
    response = httpx.get(
        f"{url.rstrip('/')}/api/websites/{site}/metrics",
        params={
            "type": "query",
            "startAt": start_ms,
            "endAt": end_ms,
            # Shared-site containment: only THIS tenant's stamped traffic.
            "query": f"utm_id={utm_id}",
        },
        headers={"Authorization": f"Bearer {key}"},
        timeout=20,
    )
    response.raise_for_status()
    counts: dict[str, int] = {}
    for row in response.json():
        name = str(row.get("x", ""))
        if name.startswith("utm_campaign="):
            counts[name.removeprefix("utm_campaign=")] = int(row.get("y", 0))
    return counts
