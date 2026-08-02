"""GA4 Data API live transport (M22 slice F, ADR 0049).

ZERO new dependencies: the OAuth2 service-account flow is a PyJWT RS256
assertion (cryptography already ships for the vault) and the report is
one httpx POST to the official Data API (rule 5). This module raises
ORDINARY exceptions — the provider layer wraps them as
AnalyticsProviderError with the class name only, so no token, property
id or credential value can ever leak into an error message (rule 4).

Metric mapping (documented, deliberate): GA4 has no inbound "clicks"
metric — campaign-attributed `sessions` ARE the click-throughs that
landed, so clicks := sessions and the stored sessions field carries
`engagedSessions` as the quality signal.
"""

import json
import time

import httpx
import jwt

_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
_API_BASE = "https://analyticsdata.googleapis.com/v1beta"
_TIMEOUT = 20.0
# One token per ~55 min, not one per backfill day; 300s safety margin.
_TOKEN_CACHE: dict = {}

# GA4's non-campaign buckets — direct traffic must never become a
# campaign_channel_metrics row.
_NON_CAMPAIGNS = {"(not set)", "(direct)", "(organic)", ""}


def _access_token(credentials_path: str) -> str:
    now = time.time()
    if _TOKEN_CACHE.get("token") and now < _TOKEN_CACHE.get("expires_at", 0.0):
        return _TOKEN_CACHE["token"]

    with open(credentials_path, encoding="utf-8") as handle:
        creds = json.load(handle)
    assertion = jwt.encode(
        {
            "iss": creds["client_email"],
            "scope": _SCOPE,
            "aud": creds["token_uri"],
            "iat": int(now),
            "exp": int(now) + 3600,
        },
        creds["private_key"],
        algorithm="RS256",
    )
    resp = httpx.post(
        creds["token_uri"],
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    token = str(payload["access_token"])
    lifetime = min(int(payload.get("expires_in", 3600)), 3600)
    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = now + lifetime - 300
    return token


def fetch_day(credentials_path: str, property_id: str, day: str) -> list[dict]:
    """One provider-local day of campaign rows for ONE GA4 property.

    Tenant scoping is the property itself: each brand connects ITS OWN
    property via the channels hub (ADR 0049 — see the rejected utm_id
    filter alternative)."""
    token = _access_token(credentials_path)
    resp = httpx.post(
        f"{_API_BASE}/properties/{property_id}:runReport",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "dateRanges": [{"startDate": day, "endDate": day}],
            "dimensions": [{"name": "sessionCampaignName"}],
            "metrics": [{"name": "sessions"}, {"name": "engagedSessions"}],
            "limit": "1000",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    rows: list[dict] = []
    for row in resp.json().get("rows", []):
        campaign = str(row["dimensionValues"][0]["value"]).strip()
        if campaign in _NON_CAMPAIGNS:
            continue
        metric_values = row["metricValues"]
        rows.append(
            {
                "campaign": campaign,
                "clicks": int(float(metric_values[0]["value"])),
                "sessions": int(float(metric_values[1]["value"])),
            }
        )
    return rows
