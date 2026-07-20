"""
M22 slice A acceptance tests — tenant-keyed metrics snapshot.

Contract (design §1 0017 + review finding «rule-6: shared-site analytics
must not bleed across brands»):
  UTM tenant key
    - _build_utm stamps utm_id = "t-" + tenant_id[:12] on every job; the
      landing URL carries it; recompilation REPLACES it (idempotent).
  POST /metrics/snapshot   (X-Internal-Token — beat-driven)
    - For each tenant, reads clicks keyed by ITS OWN utm_id
      (METRICS_MODE=fake → the _FAKE_UTM_CLICKS seam; umami mode filters
      the shared site by utm_id; missing env NAMES the var).
    - Upserts campaign_channel_metrics on the UNIQUE
      (tenant, campaign, channel, source, day) key — replays update, never
      duplicate (rule 8). day is app-TZ (ADR 0032).
    - posts_sent = the tenant's SENT publish jobs for that campaign —
      the CTR denominator lives in the row.
  Isolation (rule 6): two tenants sharing a campaign_code must each record
  ONLY their own counts — the exact bleed the review caught.
  Migration 0017 (chain 0016 → 0017): campaign_channel_metrics +
  tenant_learnings (with content_hash for the distiller's no-op replays).

All tests named test_m22_<criterion>.
"""

from __future__ import annotations

import os
import re
import secrets as _secrets
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from rpim_core_api.measurement import attribution
from rpim_core_api.measurement.utm import build_landing_url

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("PUBLISH_MODE", "fake")
os.environ.setdefault("METRICS_MODE", "fake")
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))

_REPO_ROOT = Path(__file__).resolve().parents[3]


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


def _internal() -> dict:
    return {"X-Internal-Token": _INTERNAL_TOKEN}


def _sent_job(client: TestClient, token: str, campaign: str) -> str:
    from rpim_core_api.publisher import channels  # noqa: PLC0415

    brief = {
        "goal": "هدف",
        "audience": "مخاطب",
        "channel": "بله",
        "format": "پست",
        "hook": None,
        "cta": None,
    }
    draft_id = client.post(
        "/content/drafts", json={"brief": brief}, headers=_auth(token)
    ).json()["draft_id"]
    client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    resp = client.post(
        "/publish/jobs",
        json={
            "draft_id": draft_id,
            "channel": "bale",
            "chat_id": "@x",
            "campaign_code": campaign,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["job_id"]
    dispatch = client.post("/publish/dispatch", headers=_internal())
    assert dispatch.status_code == 200 and dispatch.json()["sent"] >= 1, dispatch.text
    channels._OUTBOX.clear()
    return job_id


def _rows(tenant_id: str) -> list:
    from sqlalchemy import select  # noqa: PLC0415

    from rpim_core_api.models import CampaignChannelMetric  # noqa: PLC0415

    with _session() as session:
        return [
            {
                "campaign": r.campaign_code,
                "channel": r.channel,
                "source": r.source,
                "day": r.day,
                "clicks": r.clicks,
                "posts_sent": r.posts_sent,
            }
            for r in session.scalars(
                select(CampaignChannelMetric).where(
                    CampaignChannelMetric.tenant_id == tenant_id
                )
            ).all()
        ]


# ===========================================================================
# 1. The tenant key rides every job and landing link
# ===========================================================================


def test_m22_utm_carries_tenant_key(client: TestClient):
    token, tenant_id = _register(client, "m22-key@example.com", "M22Key")
    brief = {
        "goal": "هدف",
        "audience": "مخاطب",
        "channel": "بله",
        "format": "پست",
        "hook": None,
        "cta": None,
    }
    draft_id = client.post(
        "/content/drafts", json={"brief": brief}, headers=_auth(token)
    ).json()["draft_id"]
    client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    resp = client.post(
        "/publish/jobs",
        json={
            "draft_id": draft_id,
            "channel": "bale",
            "chat_id": "@x",
            "campaign_code": "camp_key",
            "landing_url": "https://brand.ir/p",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    expected = f"t-{tenant_id[:12]}"
    assert body["utm"].get("utm_id") == expected, (
        f"every job must carry the tenant attribution key: {body['utm']}"
    )
    qs = parse_qs(urlsplit(body["landing_url"]).query)
    assert qs.get("utm_id") == [expected], f"landing link must carry utm_id: {body}"


def test_m22_utm_id_replaced_never_duplicated():
    utm = {
        "utm_source": "bale",
        "utm_medium": "social",
        "utm_campaign": "c1",
        "utm_id": "t-fresh",
    }
    result = build_landing_url("https://x.ir/p?utm_id=t-stale&ref=a", utm)
    qs = parse_qs(urlsplit(result).query)
    assert qs.get("utm_id") == ["t-fresh"], f"stale utm_id must be replaced: {result}"
    assert qs.get("ref") == ["a"], "non-utm params must survive"


# ===========================================================================
# 2. Snapshot — trust boundary, isolation, idempotency, denominator
# ===========================================================================


def test_m22_snapshot_requires_internal_token(client: TestClient):
    assert client.post("/metrics/snapshot").status_code == 403
    assert (
        client.post("/metrics/snapshot", headers={"X-Internal-Token": "wrong"}).status_code
        == 403
    )


def test_m22_snapshot_isolates_shared_campaign_codes(client: TestClient, monkeypatch):
    """THE review scenario: two brands both run campaign 'spring-sale' on the
    shared analytics site — each must ingest only its OWN clicks (rule 6)."""
    monkeypatch.setenv("METRICS_MODE", "fake")
    token_a, tenant_a = _register(client, "m22-iso-a@example.com", "M22IsoA")
    token_b, tenant_b = _register(client, "m22-iso-b@example.com", "M22IsoB")
    _sent_job(client, token_a, "spring-sale")
    _sent_job(client, token_b, "spring-sale")

    attribution._FAKE_UTM_CLICKS.clear()
    attribution._FAKE_UTM_CLICKS[f"t-{tenant_a[:12]}"] = {"spring-sale": 7}
    attribution._FAKE_UTM_CLICKS[f"t-{tenant_b[:12]}"] = {"spring-sale": 3}

    resp = client.post("/metrics/snapshot", headers=_internal())
    assert resp.status_code == 200, resp.text

    rows_a, rows_b = _rows(tenant_a), _rows(tenant_b)
    assert len(rows_a) == 1 and rows_a[0]["clicks"] == 7, rows_a
    assert len(rows_b) == 1 and rows_b[0]["clicks"] == 3, (
        f"tenant B must never absorb A's counts (rule 6): {rows_b}"
    )
    assert rows_a[0]["source"] == "umami" and rows_a[0]["channel"] == "web", rows_a


def test_m22_snapshot_upserts_never_duplicates(client: TestClient, monkeypatch):
    from rpim_shared.tz import now_app  # noqa: PLC0415

    monkeypatch.setenv("METRICS_MODE", "fake")
    token, tenant_id = _register(client, "m22-idem@example.com", "M22Idem")
    _sent_job(client, token, "camp_idem")
    key = f"t-{tenant_id[:12]}"

    attribution._FAKE_UTM_CLICKS.clear()
    attribution._FAKE_UTM_CLICKS[key] = {"camp_idem": 4}
    assert client.post("/metrics/snapshot", headers=_internal()).status_code == 200
    attribution._FAKE_UTM_CLICKS[key] = {"camp_idem": 9}
    assert client.post("/metrics/snapshot", headers=_internal()).status_code == 200

    rows = _rows(tenant_id)
    assert len(rows) == 1, f"same-day replay must UPSERT (rule 8): {rows}"
    assert rows[0]["clicks"] == 9, rows
    assert rows[0]["day"] == now_app().strftime("%Y-%m-%d"), "day rides the app-TZ lever"


def test_m22_snapshot_records_posts_sent_denominator(client: TestClient, monkeypatch):
    monkeypatch.setenv("METRICS_MODE", "fake")
    token, tenant_id = _register(client, "m22-den@example.com", "M22Den")
    _sent_job(client, token, "camp_den")
    _sent_job(client, token, "camp_den")

    attribution._FAKE_UTM_CLICKS.clear()
    attribution._FAKE_UTM_CLICKS[f"t-{tenant_id[:12]}"] = {"camp_den": 5}
    assert client.post("/metrics/snapshot", headers=_internal()).status_code == 200
    rows = _rows(tenant_id)
    assert rows and rows[0]["posts_sent"] == 2, (
        f"the CTR denominator must live in the row: {rows}"
    )


def test_m22_live_umami_missing_env_names_the_var(monkeypatch):
    monkeypatch.setenv("METRICS_MODE", "umami")
    monkeypatch.delenv("UMAMI_URL", raising=False)
    try:
        attribution.fetch_tenant_clicks("t-abc", "2026-07-20")
        raise AssertionError("umami mode without env must fail loudly")
    except RuntimeError as exc:
        assert "UMAMI_URL" in str(exc), f"error must NAME the env var (rule 4): {exc}"


# ===========================================================================
# 3. Migration 0017 — both M22 tables, rollback included
# ===========================================================================


def test_m22_migration_0017_exists():
    path = (
        _REPO_ROOT
        / "apps"
        / "core-api"
        / "migrations"
        / "versions"
        / "0017_metrics_and_learnings.py"
    )
    assert path.exists(), "migration 0017 must exist"
    src = path.read_text("utf-8")
    assert re.search(r'revision\s*=\s*"0017"', src)
    assert re.search(r'down_revision\s*=\s*"0016"', src)
    assert "campaign_channel_metrics" in src and "tenant_learnings" in src
    assert "content_hash" in src, "distiller no-op key must ship with the table"
    assert "drop_table" in src, "rollback must be real"
