"""
M10 / DoD acceptance tests — One-click full data export.

Acceptance criteria (DoD §13.1: «one-click full data export»):
  - GET (or POST) an export endpoint on core-api that returns ALL of a
    tenant's data:
      * brand profile
      * brain documents / chunks metadata
      * content items (drafts)
      * publish jobs
      * QA results (embedded in drafts.qa)
      * apprentice A0 log references (ApprenticeEvent rows)
    … in one archive or JSON response, scoped by tenant_id.
  - Cross-tenant isolation: Tenant B's export must contain NONE of
    Tenant A's data (rule 6).

Missing piece encoded here:
  There is no /export endpoint in core-api.  The /reports/monthly endpoint
  only returns aggregate statistics for a given month, not a full data dump.

FAILS TODAY: GET /export returns 404.

All tests named test_m10_<criterion>.
"""

from __future__ import annotations

import os
import secrets

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("PUBLISH_MODE", "fake")

_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", secrets.token_hex(32))

from fastapi.testclient import TestClient  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EXPORT_URL = "/export"

_BRIEF = {
    "goal": "افزایش آگاهی از برند",
    "audience": "مدیران میان‌رده",
    "channel": "telegram",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}

# A unique marker string embedded in Tenant A's data to detect cross-tenant leaks.
_TENANT_A_MARKER = "ISOLATION_MARKER_EXPORT_M10_TENANT_A_UNIQUE_XYZ"


# ---------------------------------------------------------------------------
# Helpers
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


def _internal_header() -> dict:
    return {"X-Internal-Token": _INTERNAL_TOKEN}


def _setup_tenant(client: TestClient, email: str, password: str, name: str) -> str:
    return _register(client, email, password, name)["access_token"]


def _create_draft(client: TestClient, token: str, goal: str | None = None) -> dict:
    brief = {**_BRIEF}
    if goal is not None:
        brief["goal"] = goal
    resp = client.post("/content/drafts", json={"brief": brief}, headers=_auth(token))
    assert resp.status_code == 201, f"draft create failed: {resp.text}"
    return resp.json()


def _create_approved_draft(
    client: TestClient, token: str, goal: str | None = None
) -> str:
    draft = _create_draft(client, token, goal=goal)
    draft_id = draft["draft_id"]
    app = client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    assert app.status_code == 200, f"approve failed: {app.text}"
    return draft_id


def _create_job(
    client: TestClient, token: str, draft_id: str, campaign_code: str = "camp_export"
) -> str:
    resp = client.post(
        "/publish/jobs",
        json={
            "draft_id": draft_id,
            "channel": "telegram",
            "chat_id": "77770",
            "campaign_code": campaign_code,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"job create failed: {resp.text}"
    return resp.json()["job_id"]


# ===========================================================================
# 1. Export endpoint exists and requires auth.
#    FAILS today: GET /export returns 404.
# ===========================================================================


def test_m10_export_endpoint_requires_auth(client: TestClient) -> None:
    """GET /export without Bearer token → 401.

    FAILS today: the endpoint does not exist (returns 404, not 401).
    """
    resp = client.get(_EXPORT_URL)
    assert resp.status_code == 401, (
        f"GET /export without token must return 401; "
        f"got {resp.status_code} — implement the export endpoint for M10."
    )


# ===========================================================================
# 2. Export returns a 200 with all required top-level keys.
#    FAILS today: endpoint does not exist.
# ===========================================================================


def test_m10_export_response_shape(client: TestClient) -> None:
    """GET /export → 200 with all required top-level data sections.

    Required sections in response body:
      - brand_profile
      - brain_documents  (sources and/or chunks metadata)
      - content_drafts
      - publish_jobs
      - apprentice_events

    FAILS today: endpoint does not exist.
    """
    token = _setup_tenant(client, "m10-exp-shape@test.com", "pw123456", "M10ExpShape")

    resp = client.get(_EXPORT_URL, headers=_auth(token))
    assert resp.status_code == 200, (
        f"GET /export must return 200 for authenticated tenant; "
        f"got {resp.status_code}: {resp.text}"
    )
    body = resp.json()

    required_keys = {
        "brand_profile",
        "brain_documents",
        "content_drafts",
        "publish_jobs",
        "apprentice_events",
    }
    for key in required_keys:
        assert key in body, (
            f"Export response must contain '{key}' section; got keys: {list(body.keys())}"
        )


# ===========================================================================
# 3. Export includes content drafts created by the tenant.
#    FAILS today: endpoint does not exist.
# ===========================================================================


def test_m10_export_includes_tenant_drafts(client: TestClient) -> None:
    """GET /export must include the tenant's content drafts with QA results.

    FAILS today: endpoint does not exist.
    """
    token = _setup_tenant(client, "m10-exp-drafts@test.com", "pw123456", "M10ExpDrafts")
    draft = _create_draft(client, token)
    draft_id = draft["draft_id"]

    resp = client.get(_EXPORT_URL, headers=_auth(token))
    assert resp.status_code == 200, (
        f"GET /export must return 200; got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "content_drafts" in body, f"'content_drafts' missing from export: {list(body.keys())}"

    draft_ids = [d.get("draft_id") or d.get("id") for d in body["content_drafts"]]
    assert draft_id in draft_ids, (
        f"Export must include draft {draft_id!r}; found draft_ids: {draft_ids}"
    )


# ===========================================================================
# 4. Export includes publish jobs.
#    FAILS today: endpoint does not exist.
# ===========================================================================


def test_m10_export_includes_publish_jobs(client: TestClient) -> None:
    """GET /export must include the tenant's publish jobs.

    FAILS today: endpoint does not exist.
    """
    token = _setup_tenant(client, "m10-exp-jobs@test.com", "pw123456", "M10ExpJobs")
    draft_id = _create_approved_draft(client, token)
    job_id = _create_job(client, token, draft_id, campaign_code="export_campaign_01")

    resp = client.get(_EXPORT_URL, headers=_auth(token))
    assert resp.status_code == 200, f"GET /export must return 200; got {resp.status_code}"
    body = resp.json()
    assert "publish_jobs" in body, f"'publish_jobs' missing from export: {list(body.keys())}"

    job_ids = [j.get("job_id") or j.get("id") for j in body["publish_jobs"]]
    assert job_id in job_ids, (
        f"Export must include job {job_id!r}; found job_ids: {job_ids}"
    )


# ===========================================================================
# 5. Cross-tenant isolation: Tenant B's export must not contain Tenant A's data.
#    FAILS today: endpoint does not exist.
#    Constitution rule 6: every new table/feature ships with an isolation test.
# ===========================================================================


def test_m10_export_cross_tenant_isolation(client: TestClient) -> None:
    """Tenant B's GET /export must NOT contain any of Tenant A's data.

    Tenant A creates a draft with a unique marker in the brief goal.
    Tenant B's export body must not contain the marker anywhere.
    Proves the export query is scoped by tenant_id (rule 6).

    FAILS today: export endpoint does not exist.
    """
    token_a = _setup_tenant(client, "m10-exp-iso-a@test.com", "pw123456", "M10ExpIsoA")
    token_b = _setup_tenant(client, "m10-exp-iso-b@test.com", "pw123456", "M10ExpIsoB")

    # Tenant A creates data with isolation marker
    _create_draft(client, token_a, goal=_TENANT_A_MARKER)
    _create_approved_draft(client, token_a, goal=f"job_for_{_TENANT_A_MARKER}")

    # Tenant B creates their own data
    _create_draft(client, token_b)

    # Tenant B's export must not leak Tenant A's marker
    resp_b = client.get(_EXPORT_URL, headers=_auth(token_b))
    assert resp_b.status_code == 200, (
        f"Tenant B GET /export must return 200; got {resp_b.status_code}: {resp_b.text}"
    )
    assert _TENANT_A_MARKER not in resp_b.text, (
        f"Tenant B's export must NOT contain Tenant A's isolation marker.\n"
        f"marker={_TENANT_A_MARKER!r}\n"
        f"This proves cross-tenant isolation (rule 6)."
    )


# ===========================================================================
# 6. Tenant A's export must NOT appear in Tenant B's data (inverse check).
#    Complementary to test 5: also assert that Tenant A's own export DOES
#    contain the marker (export is complete for the owning tenant).
#    FAILS today: endpoint does not exist.
# ===========================================================================


def test_m10_export_owner_sees_own_data(client: TestClient) -> None:
    """Tenant A's own GET /export must include their data (completeness check).

    Tenant A creates a draft with the isolation marker; Tenant A's export
    must include it.  Guards against an over-scoped query that returns nothing.

    FAILS today: endpoint does not exist.
    """
    marker = "M10_EXPORT_OWNER_CHECK_MARKER_UNIQUE"
    token_a = _setup_tenant(
        client, "m10-exp-own-a@test.com", "pw123456", "M10ExpOwnA"
    )

    _create_draft(client, token_a, goal=marker)

    resp_a = client.get(_EXPORT_URL, headers=_auth(token_a))
    assert resp_a.status_code == 200, (
        f"Tenant A GET /export must return 200; got {resp_a.status_code}: {resp_a.text}"
    )
    assert marker in resp_a.text, (
        f"Tenant A's export must contain their own data marker {marker!r}; "
        f"the export is incomplete."
    )


# ===========================================================================
# 7. Export includes apprentice A0 event references.
#    FAILS today: endpoint does not exist (and apprentice events may be sparse).
# ===========================================================================


def test_m10_export_includes_apprentice_events(client: TestClient) -> None:
    """GET /export response must include 'apprentice_events' key (may be empty list).

    Constitution rule 8: A0 logging must be versioned per-tenant and
    exportable.  The export endpoint must surface the ApprenticeEvent table
    for the requesting tenant.

    FAILS today: endpoint does not exist.
    """
    token = _setup_tenant(
        client, "m10-exp-a0@test.com", "pw123456", "M10ExpA0"
    )

    resp = client.get(_EXPORT_URL, headers=_auth(token))
    assert resp.status_code == 200, (
        f"GET /export must return 200; got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "apprentice_events" in body, (
        f"Export must include 'apprentice_events' key (rule 8 / DoD §13.1); "
        f"got keys: {list(body.keys())}"
    )
    # The value must be a list (may be empty for a fresh tenant)
    assert isinstance(body["apprentice_events"], list), (
        f"'apprentice_events' must be a list, got: {type(body['apprentice_events'])}"
    )


# ===========================================================================
# 8. Export includes brand profile (may be default/empty for fresh tenant).
#    FAILS today: endpoint does not exist.
# ===========================================================================


def test_m10_export_includes_brand_profile(client: TestClient) -> None:
    """GET /export includes brand_profile section for the tenant.

    FAILS today: endpoint does not exist.
    """
    token = _setup_tenant(
        client, "m10-exp-brand@test.com", "pw123456", "M10ExpBrand"
    )

    resp = client.get(_EXPORT_URL, headers=_auth(token))
    assert resp.status_code == 200, (
        f"GET /export must return 200; got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "brand_profile" in body, (
        f"Export must include 'brand_profile' section; got keys: {list(body.keys())}"
    )
    # brand_profile may be null/empty for a fresh tenant; must not be MISSING
    bp = body["brand_profile"]
    assert bp is None or isinstance(bp, dict), (
        f"'brand_profile' must be null or a dict, got: {type(bp)}"
    )
