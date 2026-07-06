"""
M9 acceptance tests — Measurement core slice A.

UTM landing links on publish jobs + monthly report endpoint +
cost aggregation from the gateway ledger.

Blueprint §6.4 M9: the «پست → کلیک → لندینگ» chain must become visible in a
report.  Slice A builds the UTM link plumbing and the report skeleton with
drafts/publish/cost aggregates.  Clicks/Umami arrive in slice B.

env LEDGER_MODE=fake is set at module level BEFORE any import of
rpim_core_api.measurement — same pattern as EMBED_MODE in prior milestones.
LEDGER_MODE=fake returns deterministic entries whose total cost_usd == 0.0125
exactly, allowing the report test to assert a known total.

All tests named test_m9_<criterion>.
"""

from __future__ import annotations

import os
import secrets
import urllib.parse
from datetime import UTC, datetime

import pytest

# Must be set BEFORE any import of rpim_core_api.measurement — same pattern as
# EMBED_MODE (see apps/core-api/rpim_core_api/brain/embed_client.py).
os.environ.setdefault("LEDGER_MODE", "fake")
os.environ["PUBLISH_MODE"] = "fake"
os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")

# setdefault: whichever test module is collected first wins; all share the
# same token within one process (mirrors M7 pattern).
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", secrets.token_hex(32))

from fastapi.testclient import TestClient  # noqa: E402

# ---------------------------------------------------------------------------
# These imports raise ModuleNotFoundError until rpim_core_api.measurement is
# implemented — the expected collection error for M9 pre-implementation.
# ---------------------------------------------------------------------------
from rpim_core_api.measurement import ledger_client  # noqa: E402  # type: ignore[import]
from rpim_core_api.measurement.utm import build_landing_url  # noqa: E402  # type: ignore[import]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Pinned fake-ledger total — the implementation must return entries summing to
# exactly this value so the report assertion is deterministic.
_FAKE_LEDGER_TOTAL: float = 0.0125

_BRIEF = {
    "goal": "افزایش فروش",
    "audience": "مشتریان وفادار",
    "channel": "telegram",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}

# ---------------------------------------------------------------------------
# Helpers (mirror M7 pattern exactly)
# ---------------------------------------------------------------------------


def _register(client: TestClient, email: str, password: str, tenant_name: str) -> dict:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "tenant_name": tenant_name},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    return resp.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _setup_tenant(client: TestClient, email: str, password: str, tenant_name: str) -> str:
    return _register(client, email, password, tenant_name)["access_token"]


def _create_draft(client: TestClient, token: str) -> str:
    resp = client.post(
        "/content/drafts",
        json={"brief": _BRIEF},
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"draft create failed: {resp.text}"
    return resp.json()["draft_id"]


def _approve_draft(client: TestClient, token: str, draft_id: str) -> None:
    resp = client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    assert resp.status_code == 200, f"approve failed: {resp.text}"


def _create_approved_draft(client: TestClient, token: str) -> str:
    draft_id = _create_draft(client, token)
    _approve_draft(client, token, draft_id)
    return draft_id


def _create_job(
    client: TestClient,
    token: str,
    draft_id: str,
    channel: str = "telegram",
    chat_id: str = "12345",
    campaign_code: str = "camp_test_001",
    scheduled_at: str | None = None,
    landing_url: str | None = None,
):
    payload: dict = {
        "draft_id": draft_id,
        "channel": channel,
        "chat_id": chat_id,
        "campaign_code": campaign_code,
    }
    if scheduled_at is not None:
        payload["scheduled_at"] = scheduled_at
    if landing_url is not None:
        payload["landing_url"] = landing_url
    return client.post("/publish/jobs", json=payload, headers=_auth(token))


def _internal_header() -> dict:
    return {"X-Internal-Token": _INTERNAL_TOKEN}


# ===========================================================================
# 1. Pure UTM builder — build_landing_url (no HTTP, no DB)
# ===========================================================================


def test_m9_utm_appends_params():
    """build_landing_url appends utm_source, utm_medium, utm_campaign as query params."""
    utm = {"utm_source": "telegram", "utm_medium": "social", "utm_campaign": "summer2026"}
    result = build_landing_url("https://brand.ir/landing", utm)
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(result).query)
    assert qs.get("utm_source") == ["telegram"], f"utm_source missing/wrong: {result!r}"
    assert qs.get("utm_medium") == ["social"], f"utm_medium missing/wrong: {result!r}"
    assert qs.get("utm_campaign") == ["summer2026"], f"utm_campaign missing/wrong: {result!r}"


def test_m9_utm_preserves_existing_params():
    """build_landing_url preserves pre-existing non-utm query params (ref=a must survive)."""
    utm = {"utm_source": "telegram", "utm_medium": "social", "utm_campaign": "test"}
    result = build_landing_url("https://x.ir/p?ref=a", utm)
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(result).query)
    assert qs.get("ref") == ["a"], (
        f"pre-existing 'ref=a' must be preserved in output: result={result!r}, qs={qs}"
    )


def test_m9_utm_replaces_existing_utm_params():
    """build_landing_url REPLACES pre-existing utm_* params — no duplicates allowed."""
    utm = {"utm_source": "telegram", "utm_medium": "social", "utm_campaign": "new_camp"}
    result = build_landing_url(
        "https://brand.ir/?utm_source=old&utm_campaign=old", utm
    )
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(result).query)
    assert qs.get("utm_source") == ["telegram"], (
        f"utm_source must be replaced, not duplicated: qs={qs}, url={result!r}"
    )
    assert qs.get("utm_campaign") == ["new_camp"], (
        f"utm_campaign must be replaced, not duplicated: qs={qs}, url={result!r}"
    )


def test_m9_utm_idempotent():
    """build_landing_url(build_landing_url(u, utm), utm) == build_landing_url(u, utm)."""
    utm = {"utm_source": "bale", "utm_medium": "social", "utm_campaign": "idem_test"}
    url = "https://brand.ir/page?ref=b"
    once = build_landing_url(url, utm)
    twice = build_landing_url(once, utm)
    assert once == twice, (
        f"build_landing_url must be idempotent: once={once!r} != twice={twice!r}"
    )


def test_m9_utm_encodes_persian_campaign():
    """build_landing_url percent-encodes Persian campaign codes; parse_qs round-trips back."""
    persian_code = "نوروز۱۴۰۵"
    utm = {"utm_source": "telegram", "utm_medium": "social", "utm_campaign": persian_code}
    result = build_landing_url("https://brand.ir/", utm)
    encoded = urllib.parse.quote(persian_code, safe="")
    assert encoded in result, (
        f"URL must contain percent-encoded Persian {encoded!r}: result={result!r}"
    )
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(result).query)
    assert qs.get("utm_campaign") == [persian_code], (
        f"parse_qs must round-trip back to original Persian: "
        f"expected {[persian_code]!r}, got {qs.get('utm_campaign')!r}"
    )


def test_m9_utm_raises_for_ftp_scheme():
    """build_landing_url raises ValueError for non-http(s) ftp:// scheme."""
    utm = {"utm_source": "telegram", "utm_medium": "social", "utm_campaign": "x"}
    with pytest.raises(ValueError):
        build_landing_url("ftp://evil.com/path", utm)


def test_m9_utm_raises_for_javascript_scheme():
    """build_landing_url raises ValueError for javascript: scheme (XSS guard)."""
    utm = {"utm_source": "telegram", "utm_medium": "social", "utm_campaign": "x"}
    with pytest.raises(ValueError):
        build_landing_url("javascript:alert(1)", utm)


def test_m9_utm_raises_for_empty_string():
    """build_landing_url raises ValueError for empty string base_url."""
    utm = {"utm_source": "telegram", "utm_medium": "social", "utm_campaign": "x"}
    with pytest.raises(ValueError):
        build_landing_url("", utm)


# ===========================================================================
# 2. Publish jobs carry the landing link
# ===========================================================================


def test_m9_create_job_with_landing_url(client: TestClient):
    """POST /publish/jobs with landing_url → 201; response landing_url has utm applied.

    utm_campaign must equal campaign_code and utm_source must equal channel.
    """
    token = _setup_tenant(client, "m9-land-url@test.com", "pw123456", "M9LandUrl")
    draft_id = _create_approved_draft(client, token)

    base_url = "https://brand.ir/landing"
    resp = _create_job(
        client,
        token,
        draft_id,
        channel="telegram",
        campaign_code="camp_m9_url",
        landing_url=base_url,
    )
    assert resp.status_code == 201, (
        f"expected 201 with landing_url, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "landing_url" in body, f"'landing_url' must be in response: {body}"
    returned_url = body["landing_url"]
    assert returned_url is not None, f"landing_url must not be null when provided: {body}"

    qs = urllib.parse.parse_qs(urllib.parse.urlparse(returned_url).query)
    assert qs.get("utm_campaign") == ["camp_m9_url"], (
        f"landing_url must contain utm_campaign==campaign_code: {returned_url!r}, qs={qs}"
    )
    assert qs.get("utm_source") == ["telegram"], (
        f"landing_url must contain utm_source==channel: {returned_url!r}, qs={qs}"
    )
    # Base path must be preserved
    assert urllib.parse.urlparse(returned_url).path == urllib.parse.urlparse(base_url).path, (
        f"base URL path must be preserved in landing_url: {returned_url!r}"
    )


def test_m9_create_job_without_landing_url(client: TestClient):
    """POST /publish/jobs without landing_url → 201 with landing_url==null (M7 intact)."""
    token = _setup_tenant(client, "m9-no-land@test.com", "pw123456", "M9NoLand")
    draft_id = _create_approved_draft(client, token)

    resp = _create_job(client, token, draft_id)
    assert resp.status_code == 201, (
        f"job without landing_url must still return 201, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body.get("landing_url") is None, (
        f"landing_url must be null when not provided: {body}"
    )


def test_m9_create_job_422_invalid_landing_url_scheme(client: TestClient):
    """POST /publish/jobs with non-http(s) landing_url → 422 (javascript: XSS guard)."""
    token = _setup_tenant(client, "m9-bad-url@test.com", "pw123456", "M9BadUrl")
    draft_id = _create_approved_draft(client, token)

    resp = _create_job(
        client,
        token,
        draft_id,
        landing_url="javascript:alert(1)",
    )
    assert resp.status_code == 422, (
        f"non-http(s) landing_url must return 422, got {resp.status_code}: {resp.text}"
    )


def test_m9_list_jobs_include_landing_url(client: TestClient):
    """GET /publish/jobs entries each include a 'landing_url' key (null or string)."""
    token = _setup_tenant(client, "m9-list-land@test.com", "pw123456", "M9ListLand")
    draft_id = _create_approved_draft(client, token)

    _create_job(
        client,
        token,
        draft_id,
        channel="telegram",
        landing_url="https://brand.ir/lp",
    )

    resp = client.get("/publish/jobs", headers=_auth(token))
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert len(jobs) >= 1, f"should have at least 1 job in list: {jobs}"
    for job in jobs:
        assert "landing_url" in job, (
            f"GET /publish/jobs entries must include 'landing_url' key: {job}"
        )


# ===========================================================================
# 3. Ledger client fake/remote seam
# ===========================================================================


def test_m9_ledger_fake_mode_returns_entries():
    """LEDGER_MODE=fake → fetch_entries returns non-empty list; each entry has
    provider (str), tokens (int), cost_usd (float)."""
    entries = ledger_client.fetch_entries("any-tenant-id")
    assert isinstance(entries, list) and len(entries) > 0, (
        f"fake mode must return non-empty list: {entries!r}"
    )
    for entry in entries:
        assert "provider" in entry, f"each entry must have 'provider': {entry}"
        assert isinstance(entry["provider"], str), f"provider must be str: {entry}"
        assert "tokens" in entry, f"each entry must have 'tokens': {entry}"
        assert isinstance(entry["tokens"], int), f"tokens must be int: {entry}"
        assert "cost_usd" in entry, f"each entry must have 'cost_usd': {entry}"
        assert isinstance(entry["cost_usd"], float), f"cost_usd must be float: {entry}"


def test_m9_ledger_fake_total_cost():
    """LEDGER_MODE=fake → total cost_usd across all entries == 0.0125 exactly."""
    entries = ledger_client.fetch_entries("any-tenant-id")
    total = sum(e["cost_usd"] for e in entries)
    assert total == _FAKE_LEDGER_TOTAL, (
        f"fake mode total_usd must == {_FAKE_LEDGER_TOTAL}, got {total}: {entries!r}"
    )


def test_m9_ledger_fake_providers():
    """LEDGER_MODE=fake → every entry has provider == 'fake'."""
    entries = ledger_client.fetch_entries("any-tenant-id")
    providers = [e["provider"] for e in entries]
    assert all(p == "fake" for p in providers), (
        f"all fake-mode entries must have provider=='fake': {providers}"
    )


def test_m9_ledger_remote_without_gateway_raises():
    """LEDGER_MODE=remote without GATEWAY_URL → RuntimeError naming 'GATEWAY_URL'.

    Remote mode is NOT tested against the network; only the env-var guard is
    tested (mirrors EMBED_MODE pattern in embed_client.py).
    """
    saved_mode = os.environ.get("LEDGER_MODE")
    saved_gw = os.environ.pop("GATEWAY_URL", None)
    os.environ["LEDGER_MODE"] = "remote"
    try:
        with pytest.raises(RuntimeError, match="GATEWAY_URL"):
            ledger_client.fetch_entries("any-tenant-id")
    finally:
        # Restore env so subsequent tests remain in fake mode
        if saved_mode is not None:
            os.environ["LEDGER_MODE"] = saved_mode
        else:
            os.environ.pop("LEDGER_MODE", None)
        if saved_gw is not None:
            os.environ["GATEWAY_URL"] = saved_gw


# ===========================================================================
# 4. GET /reports/monthly — auth guard and input validation
# ===========================================================================


def test_m9_monthly_report_requires_auth(client: TestClient):
    """GET /reports/monthly without Bearer token → 401."""
    resp = client.get("/reports/monthly", params={"month": "2026-07"})
    assert resp.status_code == 401, (
        f"expected 401 for unauthenticated GET /reports/monthly, "
        f"got {resp.status_code}: {resp.text}"
    )


def test_m9_monthly_report_422_invalid_month_out_of_range(client: TestClient):
    """GET /reports/monthly?month=2026-13 → 422 (month 13 does not exist)."""
    token = _setup_tenant(client, "m9-rpt422a@test.com", "pw123456", "M9Rpt422A")
    resp = client.get(
        "/reports/monthly",
        params={"month": "2026-13"},
        headers=_auth(token),
    )
    assert resp.status_code == 422, (
        f"month=2026-13 must return 422, got {resp.status_code}: {resp.text}"
    )


def test_m9_monthly_report_422_invalid_month_not_date(client: TestClient):
    """GET /reports/monthly?month=abc → 422 (not a YYYY-MM string)."""
    token = _setup_tenant(client, "m9-rpt422b@test.com", "pw123456", "M9Rpt422B")
    resp = client.get(
        "/reports/monthly",
        params={"month": "abc"},
        headers=_auth(token),
    )
    assert resp.status_code == 422, (
        f"month=abc must return 422, got {resp.status_code}: {resp.text}"
    )


def test_m9_monthly_report_422_missing_month(client: TestClient):
    """GET /reports/monthly without month param → 422 (required param absent)."""
    token = _setup_tenant(client, "m9-rpt422c@test.com", "pw123456", "M9Rpt422C")
    resp = client.get("/reports/monthly", headers=_auth(token))
    assert resp.status_code == 422, (
        f"missing month param must return 422, got {resp.status_code}: {resp.text}"
    )


# ===========================================================================
# 5. GET /reports/monthly — end-to-end scenario
# ===========================================================================


def test_m9_monthly_report_end_to_end(client: TestClient):
    """Full M9 measurement scenario: register → draft → approve → 2 jobs → dispatch → report.

    Asserts shape and content:
      - drafts.created >= 1, drafts.approved >= 1
      - publish.sent == 2
      - publish.by_channel["telegram"] == 1, ["bale"] == 1
      - campaigns contains {campaign_code: "camp_m9", jobs: 2, sent: 2}
      - costs.total_usd == 0.0125 (pinned fake ledger)
      - costs.by_provider == {"fake": 0.0125}
    """
    token = _setup_tenant(client, "m9-e2e@test.com", "pw123456", "M9E2E")
    draft_id = _create_approved_draft(client, token)

    # Job 1: telegram with landing_url
    r1 = _create_job(
        client,
        token,
        draft_id,
        channel="telegram",
        chat_id="10001",
        campaign_code="camp_m9",
        landing_url="https://brand.ir/landing",
    )
    assert r1.status_code == 201, f"job1 (telegram+landing_url) creation failed: {r1.text}"

    # Job 2: bale without landing_url
    r2 = _create_job(
        client,
        token,
        draft_id,
        channel="bale",
        chat_id="10002",
        campaign_code="camp_m9",
    )
    assert r2.status_code == 201, f"job2 (bale) creation failed: {r2.text}"

    # Dispatch — PUBLISH_MODE=fake so both jobs send immediately
    dispatch_resp = client.post("/publish/dispatch", headers=_internal_header())
    assert dispatch_resp.status_code == 200, (
        f"dispatch must return 200, got {dispatch_resp.status_code}: {dispatch_resp.text}"
    )
    dispatch_body = dispatch_resp.json()
    assert dispatch_body.get("sent", 0) >= 2, (
        f"dispatch must report sent >= 2, got: {dispatch_body}"
    )

    # Current month as YYYY-MM (SQLite stores UTC now())
    current_month = datetime.now(UTC).strftime("%Y-%m")

    rpt = client.get(
        "/reports/monthly",
        params={"month": current_month},
        headers=_auth(token),
    )
    assert rpt.status_code == 200, (
        f"GET /reports/monthly must return 200, got {rpt.status_code}: {rpt.text}"
    )
    body = rpt.json()

    # ---- Shape validation ----
    assert body.get("month") == current_month, (
        f"report 'month' must match requested month: got {body.get('month')!r}"
    )
    for top_key in ("drafts", "publish", "campaigns", "costs"):
        assert top_key in body, f"top-level key '{top_key}' missing from report: {body}"

    drafts = body["drafts"]
    for k in ("created", "approved", "edited", "rejected"):
        assert k in drafts and isinstance(drafts[k], int), (
            f"drafts.{k} must be an int: {drafts}"
        )

    publish = body["publish"]
    for k in ("queued", "sent", "by_channel"):
        assert k in publish, f"publish.{k} missing: {publish}"
    assert isinstance(publish["by_channel"], dict), (
        f"publish.by_channel must be dict: {publish}"
    )

    campaigns = body["campaigns"]
    assert isinstance(campaigns, list), f"campaigns must be a list: {campaigns}"
    for c in campaigns:
        for k in ("campaign_code", "jobs", "sent"):
            assert k in c, f"campaign entry missing '{k}': {c}"

    costs = body["costs"]
    assert "total_usd" in costs and "by_provider" in costs, (
        f"costs must have total_usd and by_provider: {costs}"
    )
    assert isinstance(costs["by_provider"], dict), (
        f"costs.by_provider must be dict: {costs}"
    )

    # ---- Content assertions ----
    assert drafts["created"] >= 1, f"drafts.created must be >= 1: {drafts}"
    assert drafts["approved"] >= 1, f"drafts.approved must be >= 1: {drafts}"

    assert publish["sent"] == 2, (
        f"publish.sent must == 2 after dispatching both jobs: {publish}"
    )
    by_channel = publish["by_channel"]
    assert by_channel.get("telegram") == 1, (
        f"by_channel['telegram'] must == 1: {by_channel}"
    )
    assert by_channel.get("bale") == 1, (
        f"by_channel['bale'] must == 1: {by_channel}"
    )

    camp_m9 = next((c for c in campaigns if c["campaign_code"] == "camp_m9"), None)
    assert camp_m9 is not None, (
        f"campaigns must include entry for 'camp_m9': {campaigns}"
    )
    assert camp_m9["jobs"] == 2, (
        f"camp_m9.jobs must == 2, got {camp_m9['jobs']}: {campaigns}"
    )
    assert camp_m9["sent"] == 2, (
        f"camp_m9.sent must == 2, got {camp_m9['sent']}: {campaigns}"
    )

    assert costs["total_usd"] == _FAKE_LEDGER_TOTAL, (
        f"costs.total_usd must == {_FAKE_LEDGER_TOTAL} (fake ledger), "
        f"got {costs['total_usd']}"
    )
    assert costs["by_provider"] == {"fake": _FAKE_LEDGER_TOTAL}, (
        f"costs.by_provider must == {{'fake': {_FAKE_LEDGER_TOTAL}}}: "
        f"{costs['by_provider']}"
    )


# ===========================================================================
# 6. GET /reports/monthly — cross-tenant isolation (constitution rule 6)
# ===========================================================================


def test_m9_monthly_report_cross_tenant_isolation(client: TestClient):
    """Tenant B's report must NOT contain Tenant A's campaign code anywhere.

    Constitution rule 6: tenant isolation is absolute; every new table ships
    with a test proving cross-tenant isolation.

    Tenant B's costs also come from their own ledger call (fake mode, same
    total expected but isolation is at the tenant_id scope).
    """
    MARKER = "ISOLATION_MARKER_M9_CAMPAIGN_UNIQUE_DO_NOT_LEAK"

    token_a = _setup_tenant(client, "m9-iso-a@test.com", "pw123456", "M9IsoA")
    token_b = _setup_tenant(client, "m9-iso-b@test.com", "pw123456", "M9IsoB")

    # Tenant A: create + dispatch a job with an unmistakable campaign marker
    draft_id_a = _create_approved_draft(client, token_a)
    ra = _create_job(
        client,
        token_a,
        draft_id_a,
        channel="telegram",
        campaign_code=MARKER,
    )
    assert ra.status_code == 201, f"Tenant A job creation failed: {ra.text}"
    client.post("/publish/dispatch", headers=_internal_header())

    # Tenant B: create + dispatch their own job (report is non-trivially populated)
    draft_id_b = _create_approved_draft(client, token_b)
    rb = _create_job(
        client,
        token_b,
        draft_id_b,
        channel="bale",
        campaign_code="camp_b_only",
    )
    assert rb.status_code == 201, f"Tenant B job creation failed: {rb.text}"
    client.post("/publish/dispatch", headers=_internal_header())

    current_month = datetime.now(UTC).strftime("%Y-%m")

    # Tenant B's report must not expose Tenant A's data at all
    resp_b = client.get(
        "/reports/monthly",
        params={"month": current_month},
        headers=_auth(token_b),
    )
    assert resp_b.status_code == 200, (
        f"Tenant B GET /reports/monthly must return 200: "
        f"got {resp_b.status_code}: {resp_b.text}"
    )
    assert MARKER not in resp_b.text, (
        f"Tenant B's report must not contain Tenant A's campaign marker.\n"
        f"marker={MARKER!r}\nresponse={resp_b.text!r}"
    )
    # Belt-and-suspenders: check campaigns list directly
    b_campaigns = resp_b.json().get("campaigns", [])
    for c in b_campaigns:
        assert c.get("campaign_code") != MARKER, (
            f"Tenant B's campaign list must not contain Tenant A's marker: {c}"
        )
