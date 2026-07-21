"""
M22 slice B acceptance tests — provider-neutral analytics ingestion,
GA4 as the first adapter (pull-with-cursor, ADR 0042).

Contract:
  Connection (analytics-only, never publishable)
    - PUT /channels/ga4 (owner) with config {property_id} — NO secret: the
      platform service account is a leg-level env NAME; per-tenant material
      is the non-secret property_id. status=connected iff property_id set.
    - GET /channels listing keeps showing ONLY the four publish channels
      (m16 contract untouched); ga4 is an analytics slot, not a publisher.

  POST /metrics/ingest   (X-Internal-Token — beat-driven)
    - Only tenants WITH a ga4 connection ingest; each pulls DAYS from its
      cursor+1 up to YESTERDAY on the app clock (PT lever, ADR 0032);
      a fresh tenant backfills at most INGEST_BACKFILL_DAYS.
    - Per-day upsert into campaign_channel_metrics (source="ga4") on the
      existing UNIQUE (tenant,campaign,channel,source,day) key; the cursor
      advances ONLY after a day fully lands → crash/malformed-day resume
      re-starts exactly at the failed day (rule 8), never re-writes and
      never skips.
    - Full-window replay: identical row counts, cursor monotonic.
    - A malformed provider payload stops THAT tenant at its cursor; other
      tenants ingest unaffected; the beat never crash-loops.
    - Zero cross-tenant leakage: rows land only under the connection's
      tenant; property data never crosses tenants (rule 6).
    - Observability without PII: the response carries COUNTS only.

  Provider interface: ANALYTICS_PROVIDERS registry; ga4 fake adapter reads
  the _FAKE_GA4 seam; GA4_MODE=live without GA4_CREDENTIALS_FILE fails
  NAMING the var (rule 4) — live transport is the next slice.

  Migration 0020 (chain 0017 → 0020; 0018 stays reserved for M23 per the
  ADR 0038 numbering precedent): analytics_cursors + full downgrade.

All tests named test_m22b_<criterion>.
"""

from __future__ import annotations

import os
import re
import secrets as _secrets
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rpim_core_api.measurement import analytics_providers as providers

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("PUBLISH_MODE", "fake")
os.environ.setdefault("GA4_MODE", "fake")
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _day(offset: int) -> str:
    from rpim_shared.tz import now_app  # noqa: PLC0415

    return (now_app() - timedelta(days=offset)).strftime("%Y-%m-%d")


@pytest.fixture(autouse=True)
def _seams(monkeypatch):
    monkeypatch.setenv("GA4_MODE", "fake")
    monkeypatch.setenv("INGEST_BACKFILL_DAYS", "7")
    providers._FAKE_GA4.clear()
    yield
    providers._FAKE_GA4.clear()


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


def _connect_ga4(client: TestClient, token: str, property_id: str) -> None:
    resp = client.put(
        "/channels/ga4",
        json={"config": {"property_id": property_id}},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "connected", resp.json()


def _ga4_rows(tenant_id: str) -> list[dict]:
    from sqlalchemy import select  # noqa: PLC0415

    from rpim_core_api.models import CampaignChannelMetric  # noqa: PLC0415

    with _session() as session:
        return [
            {
                "campaign": r.campaign_code,
                "day": r.day,
                "clicks": r.clicks,
                "sessions": r.sessions,
            }
            for r in session.scalars(
                select(CampaignChannelMetric).where(
                    CampaignChannelMetric.tenant_id == tenant_id,
                    CampaignChannelMetric.source == "ga4",
                )
            ).all()
        ]


def _cursor(tenant_id: str) -> str | None:
    from sqlalchemy import select  # noqa: PLC0415

    from rpim_core_api.models import AnalyticsCursor  # noqa: PLC0415

    with _session() as session:
        row = session.scalar(
            select(AnalyticsCursor).where(
                AnalyticsCursor.tenant_id == tenant_id,
                AnalyticsCursor.provider == "ga4",
            )
        )
        return row.cursor if row else None


# ===========================================================================
# 1. The analytics connection slot
# ===========================================================================


def test_m22b_ga4_connects_with_property_id_no_secret(client: TestClient):
    token, _tenant = _register(client, "m22b-conn@example.com", "M22bConn")
    _connect_ga4(client, token, "prop-123")
    # The publish listing contract is untouched: four channels, no ga4 card.
    channels = client.get("/channels", headers=_auth(token)).json()["channels"]
    assert {c["channel"] for c in channels} == {"telegram", "bale", "eitaa", "wordpress"}


def test_m22b_ga4_connection_is_owner_only(client: TestClient):
    owner, _ = _register(client, "m22b-own@example.com", "M22bOwn")
    invite = client.post(
        "/auth/invites",
        json={"email": "m22b-ed@example.com", "role": "editor"},
        headers=_auth(owner),
    ).json()["token"]
    editor = client.post(
        "/auth/invites/accept", json={"token": invite, "password": "Password123!"}
    ).json()["access_token"]
    resp = client.put(
        "/channels/ga4", json={"config": {"property_id": "p"}}, headers=_auth(editor)
    )
    assert resp.status_code == 403


# ===========================================================================
# 2. Ingestion — isolation, cursor resume, replay, malformed payloads
# ===========================================================================


def test_m22b_ingest_requires_internal_token(client: TestClient):
    assert client.post("/metrics/ingest").status_code == 403


def test_m22b_ingest_isolates_tenants_and_skips_unconnected(client: TestClient):
    token_a, tenant_a = _register(client, "m22b-a@example.com", "M22bA")
    token_b, tenant_b = _register(client, "m22b-b@example.com", "M22bB")
    _token_c, tenant_c = _register(client, "m22b-c@example.com", "M22bC")
    _connect_ga4(client, token_a, "prop-A")
    _connect_ga4(client, token_b, "prop-B")

    providers._FAKE_GA4["prop-A"] = {
        _day(1): [{"campaign": "spring-sale", "clicks": 11, "sessions": 20}]
    }
    providers._FAKE_GA4["prop-B"] = {
        _day(1): [{"campaign": "spring-sale", "clicks": 4, "sessions": 6}]
    }

    resp = client.post("/metrics/ingest", headers=_internal())
    assert resp.status_code == 200, resp.text

    rows_a, rows_b = _ga4_rows(tenant_a), _ga4_rows(tenant_b)
    assert len(rows_a) == 1 and rows_a[0]["clicks"] == 11, rows_a
    assert len(rows_b) == 1 and rows_b[0]["clicks"] == 4, (
        f"property data must never cross tenants (rule 6): {rows_b}"
    )
    assert _ga4_rows(tenant_c) == [], "no connection → no ingestion"
    body = resp.json()
    assert set(body) >= {"tenants", "connected", "days", "rows", "failed"}, body
    assert "spring-sale" not in str(body), "observability carries COUNTS only"


def test_m22b_cursor_resumes_exactly_after_malformed_day(client: TestClient):
    token, tenant_id = _register(client, "m22b-res@example.com", "M22bRes")
    _connect_ga4(client, token, "prop-R")
    providers._FAKE_GA4["prop-R"] = {
        _day(2): [{"campaign": "c1", "clicks": 1, "sessions": 2}],
        _day(1): "MALFORMED",  # adapter must reject, not swallow
    }

    first = client.post("/metrics/ingest", headers=_internal())
    assert first.status_code == 200 and first.json()["failed"] == 1, first.text
    assert _cursor(tenant_id) == _day(2), "cursor stops at the last GOOD day"
    assert len(_ga4_rows(tenant_id)) == 1

    providers._FAKE_GA4["prop-R"][_day(1)] = [
        {"campaign": "c1", "clicks": 9, "sessions": 12}
    ]
    second = client.post("/metrics/ingest", headers=_internal())
    assert second.status_code == 200 and second.json()["failed"] == 0, second.text
    rows = sorted(_ga4_rows(tenant_id), key=lambda r: r["day"])
    assert [r["day"] for r in rows] == [_day(2), _day(1)], (
        f"resume must re-start EXACTLY at the failed day: {rows}"
    )
    assert _cursor(tenant_id) == _day(1), "cursor lands on yesterday (app clock)"


def test_m22b_full_replay_is_idempotent_and_cursor_monotonic(client: TestClient):
    token, tenant_id = _register(client, "m22b-idem@example.com", "M22bIdem")
    _connect_ga4(client, token, "prop-I")
    providers._FAKE_GA4["prop-I"] = {
        _day(1): [{"campaign": "c1", "clicks": 3, "sessions": 5}]
    }
    assert client.post("/metrics/ingest", headers=_internal()).status_code == 200
    rows_before = _ga4_rows(tenant_id)
    cursor_before = _cursor(tenant_id)

    assert client.post("/metrics/ingest", headers=_internal()).status_code == 200
    assert _ga4_rows(tenant_id) == rows_before, "replay must not duplicate (rule 8)"
    assert _cursor(tenant_id) == cursor_before, "cursor never moves backward"


def test_m22b_malformed_tenant_never_blocks_others(client: TestClient):
    token_x, tenant_x = _register(client, "m22b-x@example.com", "M22bX")
    token_y, tenant_y = _register(client, "m22b-y@example.com", "M22bY")
    _connect_ga4(client, token_x, "prop-X")
    _connect_ga4(client, token_y, "prop-Y")
    providers._FAKE_GA4["prop-X"] = {_day(1): "MALFORMED"}
    providers._FAKE_GA4["prop-Y"] = {
        _day(1): [{"campaign": "ok", "clicks": 2, "sessions": 2}]
    }
    resp = client.post("/metrics/ingest", headers=_internal())
    assert resp.status_code == 200, "the beat must never crash-loop (rule 8)"
    assert resp.json()["failed"] >= 1
    assert _ga4_rows(tenant_x) == []
    assert len(_ga4_rows(tenant_y)) == 1, "one bad tenant must not block others"


def test_m22b_backfill_window_caps_first_run(client: TestClient, monkeypatch):
    monkeypatch.setenv("INGEST_BACKFILL_DAYS", "3")
    token, tenant_id = _register(client, "m22b-cap@example.com", "M22bCap")
    _connect_ga4(client, token, "prop-W")
    providers._FAKE_GA4["prop-W"] = {
        _day(offset): [{"campaign": "c", "clicks": 1, "sessions": 1}]
        for offset in range(1, 6)  # five days of history available
    }
    assert client.post("/metrics/ingest", headers=_internal()).status_code == 200
    rows = _ga4_rows(tenant_id)
    assert len(rows) == 3, f"first run backfills at most the window: {rows}"
    assert {r["day"] for r in rows} == {_day(1), _day(2), _day(3)}, (
        "the window ends at YESTERDAY on the app clock (PT boundary)"
    )


# ===========================================================================
# 3. Provider interface + env guards (rule 4)
# ===========================================================================


def test_m22b_provider_registry_has_ga4():
    assert "ga4" in providers.ANALYTICS_PROVIDERS


def test_m22b_ga4_live_missing_credentials_names_the_var(monkeypatch):
    monkeypatch.setenv("GA4_MODE", "live")
    monkeypatch.delenv("GA4_CREDENTIALS_FILE", raising=False)
    with pytest.raises(providers.AnalyticsProviderError) as excinfo:
        providers.ANALYTICS_PROVIDERS["ga4"]("prop-1", "2026-07-20")
    assert "GA4_CREDENTIALS_FILE" in str(excinfo.value)


def test_m22b_env_example_names_ingest_vars():
    text = (_REPO_ROOT / ".env.iran.example").read_text("utf-8")
    for var in ("GA4_MODE", "GA4_CREDENTIALS_FILE", "INGEST_BACKFILL_DAYS"):
        assert re.search(rf"^{var}=", text, re.MULTILINE), (
            f".env.iran.example must name {var} (rule 4)"
        )


# ===========================================================================
# 4. Migration 0020 — cursors, with rollback
# ===========================================================================


def test_m22b_migration_0020_exists():
    path = (
        _REPO_ROOT
        / "apps"
        / "core-api"
        / "migrations"
        / "versions"
        / "0020_analytics_cursors.py"
    )
    assert path.exists(), "migration 0020 must exist"
    src = path.read_text("utf-8")
    assert re.search(r'revision\s*=\s*"0020"', src)
    assert re.search(r'down_revision\s*=\s*"0017"', src)
    assert "analytics_cursors" in src and "drop_table" in src
