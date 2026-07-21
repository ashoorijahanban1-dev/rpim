"""Provider-neutral analytics adapters (M22 slice B, ADR 0042).

Narrow interface: every provider is `fetch_day(property_ref, day) →
[{campaign, clicks, sessions}]` for ONE provider-local day. The ingestion
loop owns cursors, upserts and tenant scoping — adapters only fetch and
VALIDATE shape (a malformed payload raises instead of poisoning rows).

GA4 is the first adapter: fake mode reads the _FAKE_GA4 seam (tests/CI);
live mode is env-guarded by NAME (rule 4) and its transport lands in the
next slice with credential provisioning. Umami is the second entry (M22
slice D): property_ref is the tenant's utm_id key, transport rides the
existing attribution module (fake seam and env guards included).
"""

import os

from rpim_core_api.measurement import attribution


class AnalyticsProviderError(Exception):
    """Fetch/shape failure for one provider-day — the caller stops that
    tenant at its cursor and moves on; the beat never crash-loops."""


# Fake seam: {property_id: {day: [rows]}}; any non-list day value simulates
# a malformed provider payload.
_FAKE_GA4: dict[str, dict[str, object]] = {}


def _validated(rows: object) -> list[dict]:
    if not isinstance(rows, list):
        raise AnalyticsProviderError("malformed provider payload: expected a row list")
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict) or "campaign" not in row:
            raise AnalyticsProviderError("malformed provider payload: bad row shape")
        campaign = str(row["campaign"]).strip()
        if not campaign:
            raise AnalyticsProviderError("malformed provider payload: blank campaign")
        out.append(
            {
                "campaign": campaign[:120],
                "clicks": int(row.get("clicks", 0)),
                "sessions": int(row.get("sessions", 0)),
            }
        )
    return out


def _ga4_fetch_day(property_id: str, day: str) -> list[dict]:
    mode = os.environ.get("GA4_MODE", "fake")
    if mode == "fake":
        return _validated(_FAKE_GA4.get(property_id, {}).get(day, []))
    if mode != "live":
        raise AnalyticsProviderError("GA4_MODE must be 'fake' or 'live'")
    credentials = os.environ.get("GA4_CREDENTIALS_FILE", "")
    if not credentials:
        # Name the env var, never a value (rule 4).
        raise AnalyticsProviderError(
            "GA4_MODE=live requires env var GA4_CREDENTIALS_FILE"
        )
    # Live transport (Data API runReport filtered by sessionCampaignId ==
    # the tenant's utm_id) lands with credential provisioning — until then
    # the cursor stays put and resumes exactly (rule 8), never guesses.
    raise AnalyticsProviderError("ga4 live transport lands in the next slice")


def _umami_fetch_day(utm_id: str, day: str) -> list[dict]:
    """property_ref for umami is the tenant's utm_id (shared-site
    containment, ADR 0041). Umami's query metric has no session split, so
    sessions is 0 — the metric row keeps clicks as its signal."""
    try:
        counts = attribution.fetch_tenant_clicks(utm_id, day)
        if not isinstance(counts, dict):
            raise TypeError("expected a {campaign: clicks} mapping")
        rows = [
            {"campaign": campaign, "clicks": clicks, "sessions": 0}
            for campaign, clicks in counts.items()
        ]
        return _validated(rows)
    except AnalyticsProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 — any transport/shape failure
        # becomes the ONE caller-visible error; class name only, no values.
        raise AnalyticsProviderError(
            f"umami fetch failed: {exc.__class__.__name__}"
        ) from exc


ANALYTICS_PROVIDERS = {
    "ga4": _ga4_fetch_day,
    "umami": _umami_fetch_day,
}
