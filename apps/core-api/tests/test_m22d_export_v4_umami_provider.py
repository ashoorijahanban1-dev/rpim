"""
M22 slice D acceptance tests — export v4 + Umami on ANALYTICS_PROVIDERS.

Contract (ADR 0042 remaining scope + delivery-loop step 2):
  Export v4 (§13.1 one-click export — the tenant owns every byte):
    - /export gains campaign_channel_metrics, tenant_learnings and
      analytics_cursors sections; export_version bumps to 4.
    - The new sections are tenant-isolated like everything else (rule 6).
  Umami provider:
    - ANALYTICS_PROVIDERS gains "umami" with the SAME narrow signature as
      ga4: fetch_day(property_ref, day) → [{campaign, clicks, sessions}].
      property_ref for umami is the tenant's utm_id key ("t-" + id[:12]).
    - A malformed transport payload raises AnalyticsProviderError — never
      poisons rows (rule 8's malformed-day semantics from slice B).
    - /metrics/snapshot rides the registry (the slice-A direct call
      migrates), keeping its response contract and tenant keying intact.

All tests named test_m22d_<criterion>.
"""

from __future__ import annotations

import os
import secrets as _secrets

from fastapi.testclient import TestClient

from rpim_core_api.measurement import analytics_providers, attribution

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("PUBLISH_MODE", "fake")
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))


def _session():
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from rpim_core_api import db as db_module  # noqa: PLC0415

    return Session(db_module.engine)


def _register(client: TestClient, email: str, name: str) -> tuple[str, str]:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "tenant_name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"], resp.json()["tenant_id"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _seed_measurement_rows(tenant_id: str) -> None:
    from rpim_core_api.models import (  # noqa: PLC0415
        AnalyticsCursor,
        CampaignChannelMetric,
        TenantLearning,
    )

    with _session() as session:
        session.add(
            CampaignChannelMetric(
                tenant_id=tenant_id,
                campaign_code="spring-sale",
                channel="web",
                source="umami",
                day="2026-07-19",
                clicks=7,
                sessions=5,
                posts_sent=3,
            )
        )
        session.add(
            TenantLearning(
                tenant_id=tenant_id,
                version=1,
                directives=[{"key": "tone_adjust", "text_fa": "متن ثابت", "weight": 1}],
                evidence={"rejects": {"tone": 3}},
                content_hash="a" * 64,
            )
        )
        session.add(
            AnalyticsCursor(tenant_id=tenant_id, provider="ga4", cursor="2026-07-19")
        )
        session.commit()


# ===========================================================================
# 1. Export v4 — the tenant owns its measurement data too
# ===========================================================================


def test_m22d_export_v4_includes_measurement_sections(client: TestClient):
    token, tenant_id = _register(client, "m22d-exp@example.com", "M22dExp")
    _seed_measurement_rows(tenant_id)

    body = client.get("/export", headers=_auth(token)).json()
    assert body["export_version"] == 4, "slice D bumps the export contract"

    metrics = body["campaign_channel_metrics"]
    assert len(metrics) == 1 and metrics[0]["campaign_code"] == "spring-sale"
    assert metrics[0]["clicks"] == 7 and metrics[0]["posts_sent"] == 3
    assert metrics[0]["source"] == "umami" and metrics[0]["day"] == "2026-07-19"

    learnings = body["tenant_learnings"]
    assert len(learnings) == 1 and learnings[0]["version"] == 1
    assert learnings[0]["directives"][0]["key"] == "tone_adjust"
    assert learnings[0]["evidence"] == {"rejects": {"tone": 3}}
    assert learnings[0]["status"] == "active"

    cursors = body["analytics_cursors"]
    assert cursors == [
        {"provider": "ga4", "cursor": "2026-07-19", "updated_at": cursors[0]["updated_at"]}
    ] and cursors[0]["updated_at"], "cursor watermark exports with its stamp"


def test_m22d_export_new_sections_are_tenant_isolated(client: TestClient):
    _token_a, tenant_a = _register(client, "m22d-iso-a@example.com", "M22dIsoA")
    token_b, _tenant_b = _register(client, "m22d-iso-b@example.com", "M22dIsoB")
    _seed_measurement_rows(tenant_a)

    body = client.get("/export", headers=_auth(token_b)).json()
    assert body["campaign_channel_metrics"] == [], "rule 6: no cross-tenant bleed"
    assert body["tenant_learnings"] == []
    assert body["analytics_cursors"] == []


# ===========================================================================
# 2. Umami as a first-class ANALYTICS_PROVIDERS entry
# ===========================================================================


def test_m22d_umami_provider_same_narrow_signature(monkeypatch):
    monkeypatch.setenv("METRICS_MODE", "fake")
    attribution._FAKE_UTM_CLICKS.clear()
    attribution._FAKE_UTM_CLICKS["t-abc123def456"] = {"camp-x": 5, "camp-y": 2}

    assert "umami" in analytics_providers.ANALYTICS_PROVIDERS
    rows = analytics_providers.ANALYTICS_PROVIDERS["umami"](
        "t-abc123def456", "2026-07-19"
    )
    assert sorted(rows, key=lambda r: r["campaign"]) == [
        {"campaign": "camp-x", "clicks": 5, "sessions": 0},
        {"campaign": "camp-y", "clicks": 2, "sessions": 0},
    ], "umami adapts {campaign: clicks} onto the shared validated row shape"
    attribution._FAKE_UTM_CLICKS.clear()


def test_m22d_umami_malformed_payload_raises_provider_error(monkeypatch):
    import pytest  # noqa: PLC0415

    monkeypatch.setattr(
        attribution, "fetch_tenant_clicks", lambda *_: "not-a-mapping"
    )
    with pytest.raises(analytics_providers.AnalyticsProviderError):
        analytics_providers.ANALYTICS_PROVIDERS["umami"]("t-x", "2026-07-19")

    monkeypatch.setattr(
        attribution, "fetch_tenant_clicks", lambda *_: {"camp": "garbage"}
    )
    with pytest.raises(analytics_providers.AnalyticsProviderError):
        analytics_providers.ANALYTICS_PROVIDERS["umami"]("t-x", "2026-07-19")


def test_m22d_snapshot_rides_the_provider_registry(client: TestClient, monkeypatch):
    """The slice-A snapshot migrates onto the registry: patching the umami
    entry alone must redirect what /metrics/snapshot writes."""
    _token, tenant_id = _register(client, "m22d-snap@example.com", "M22dSnap")

    seen: list[tuple[str, str]] = []

    def fake_umami(property_ref: str, day: str) -> list[dict]:
        seen.append((property_ref, day))
        return [{"campaign": "via-registry", "clicks": 2, "sessions": 4}]

    monkeypatch.setitem(
        analytics_providers.ANALYTICS_PROVIDERS, "umami", fake_umami
    )
    resp = client.post(
        "/metrics/snapshot", headers={"X-Internal-Token": _INTERNAL_TOKEN}
    )
    assert resp.status_code == 200 and resp.json()["rows"] == 1, resp.text

    assert seen and seen[0][0] == attribution.tenant_key(tenant_id), (
        "snapshot must pass the tenant's utm_id as property_ref"
    )
    from sqlalchemy import select  # noqa: PLC0415

    from rpim_core_api.models import CampaignChannelMetric  # noqa: PLC0415

    with _session() as session:
        row = session.scalar(
            select(CampaignChannelMetric).where(
                CampaignChannelMetric.tenant_id == tenant_id
            )
        )
    assert row is not None and row.campaign_code == "via-registry"
    assert row.clicks == 2 and row.sessions == 4 and row.source == "umami"
