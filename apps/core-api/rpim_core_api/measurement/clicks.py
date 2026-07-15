"""Click counts per campaign — completes «پست → کلیک → لندینگ» (M9).

CLICKS_MODE=fake serves tests/CI through the _FAKE_CLICKS seam; umami mode
queries the self-hosted Umami API and keys counts by utm_campaign, which
build_landing_url stamped onto every landing link at job birth.
"""

import os
from datetime import datetime

import httpx

from rpim_shared.tz import app_timezone

# Fake seam: tests assign a dict here; fetch returns a copy in fake mode.
_FAKE_CLICKS: dict[str, int] = {}


def _month_window_ms(month: str) -> tuple[int, int]:
    year, mon = (int(part) for part in month.split("-"))
    start = datetime(year, mon, 1, tzinfo=app_timezone())
    end = datetime(
        year + (1 if mon == 12 else 0), 1 if mon == 12 else mon + 1, 1, tzinfo=app_timezone()
    )
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def fetch_clicks_by_campaign(month: str) -> dict[str, int]:
    mode = os.environ.get("CLICKS_MODE", "fake")
    if mode == "fake":
        return dict(_FAKE_CLICKS)

    base_url = os.environ.get("UMAMI_URL", "")
    if not base_url:
        # Name env vars, never values (rule 4).
        raise RuntimeError("CLICKS_MODE=umami requires env var UMAMI_URL")
    site_id = os.environ.get("UMAMI_SITE_ID", "")
    api_key = os.environ.get("UMAMI_API_KEY", "")
    if not site_id or not api_key:
        raise RuntimeError("CLICKS_MODE=umami requires env vars UMAMI_SITE_ID and UMAMI_API_KEY")

    start_ms, end_ms = _month_window_ms(month)
    response = httpx.get(
        f"{base_url.rstrip('/')}/api/websites/{site_id}/metrics",
        params={"type": "query", "startAt": start_ms, "endAt": end_ms},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15,
    )
    response.raise_for_status()
    counts: dict[str, int] = {}
    for row in response.json():
        name = str(row.get("x", ""))
        if name.startswith("utm_campaign="):
            counts[name.split("=", 1)[1]] = int(row.get("y", 0))
    return counts
