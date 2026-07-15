"""CRM lead bridge (M13): UTM click deltas become lead events on a webhook.

CRM_MODE=fake (tests/CI, the default) appends events to the in-process
_LEAD_OUTBOX seam. Live mode POSTs each event as JSON to CRM_WEBHOOK_URL
with a Bearer CRM_WEBHOOK_TOKEN — a provider-agnostic contract so any
CRM/ERP (or middleware in front of one) can consume leads; the concrete
adapter plugs in behind this seam once the operator names the system.
"""

import os

import httpx


class LeadDeliveryError(Exception):
    """Transient delivery failure — the watermark does NOT advance, so the
    same delta is retried on the next sync pass (rule 8)."""


# Fake seam: tests inspect delivered events here.
_LEAD_OUTBOX: list[dict] = []


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        # Name the env var, never a value (rule 4).
        raise LeadDeliveryError(f"missing credential: env var {name} is not set")
    return value


def deliver(event: dict) -> None:
    mode = os.environ.get("CRM_MODE", "fake")
    if mode == "fake":
        _LEAD_OUTBOX.append(dict(event))
        return
    if mode != "live":
        # Explicit or nothing — a typo'd mode must not silently dry-run.
        raise LeadDeliveryError("CRM_MODE must be 'fake' or 'live'")

    url = _require_env("CRM_WEBHOOK_URL")
    token = _require_env("CRM_WEBHOOK_TOKEN")
    try:
        response = httpx.post(
            url,
            json=event,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        # Never echo the URL or token (rule 4).
        raise LeadDeliveryError(f"crm webhook failed: {type(exc).__name__}") from exc
