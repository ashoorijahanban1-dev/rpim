"""
M6 acceptance tests — Approval-queue list (GET /content/drafts).

Route under test:
  GET /content/drafts

These tests FAIL until the implementation adds GET /content/drafts.
Currently a GET request to /content/drafts returns 405 (Method Not Allowed)
because only POST /content/drafts exists in the content router.

env EMBED_MODE=fake and COMPLETE_MODE=fake are set at module level so draft
creation uses deterministic fake embedder / fake completer — no network calls,
no model-gateway required in CI.

All tests named test_m6_<criterion>.
"""

from __future__ import annotations

import os

# Must be set BEFORE any import of rpim_core_api.* — same pattern as M4/M5.
os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")

from fastapi.testclient import TestClient  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BRIEF = {
    "goal": "افزایش آگاهی از برند",
    "audience": "مدیران میان‌رده",
    "channel": "اینستاگرام",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register(client: TestClient, email: str, password: str, tenant_name: str) -> dict:
    """Register a new tenant/user and return the full response body."""
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "tenant_name": tenant_name},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    return resp.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _setup_tenant(
    client: TestClient, email: str, password: str, tenant_name: str
) -> str:
    """Register a new tenant and return the access_token."""
    return _register(client, email, password, tenant_name)["access_token"]


def _create_draft(client: TestClient, token: str, brief: dict | None = None) -> dict:
    """POST /content/drafts and return the 201 response body."""
    payload = brief if brief is not None else _BRIEF
    resp = client.post(
        "/content/drafts",
        json={"brief": payload},
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"draft create failed: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# 1. Auth guard
# ---------------------------------------------------------------------------


def test_m6_list_requires_auth(client: TestClient):
    """GET /content/drafts without Bearer token → 401."""
    resp = client.get("/content/drafts")
    assert resp.status_code == 401, (
        f"expected 401 for unauthenticated GET /content/drafts, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# 2. Response shape
# ---------------------------------------------------------------------------


def test_m6_list_response_shape(client: TestClient):
    """GET /content/drafts → 200 with {"drafts": [...]} where each item contains
    draft_id, text, status, flag_unsourced, created_at, brief (dict), qa (null or dict).
    """
    token = _setup_tenant(client, "m6-shape@test.com", "password123", "M6ShapeBrand")
    _create_draft(client, token)

    resp = client.get("/content/drafts", headers=_auth(token))
    assert resp.status_code == 200, (
        f"expected 200 from GET /content/drafts, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "drafts" in body, f"'drafts' key missing from response: {body}"
    assert isinstance(body["drafts"], list), (
        f"'drafts' must be a list, got {type(body['drafts'])}"
    )
    assert len(body["drafts"]) >= 1, f"expected at least one draft in list: {body}"

    item = body["drafts"][0]
    for field in ("draft_id", "text", "status", "flag_unsourced", "created_at", "brief", "qa"):
        assert field in item, f"'{field}' missing from draft list item: {item}"

    assert isinstance(item["draft_id"], str) and item["draft_id"], (
        f"'draft_id' must be a non-empty string: {item['draft_id']!r}"
    )
    assert isinstance(item["text"], str) and item["text"], (
        f"'text' must be a non-empty string: {item['text']!r}"
    )
    assert isinstance(item["status"], str), (
        f"'status' must be a string, got {type(item['status'])}"
    )
    assert isinstance(item["flag_unsourced"], bool), (
        f"'flag_unsourced' must be bool, got {type(item['flag_unsourced'])}"
    )
    assert isinstance(item["created_at"], str) and item["created_at"], (
        f"'created_at' must be a non-empty ISO string: {item['created_at']!r}"
    )
    assert isinstance(item["brief"], dict), (
        f"'brief' must be a dict, got {type(item['brief'])}"
    )
    # qa is null (no QA run yet) or a dict
    assert item["qa"] is None or isinstance(item["qa"], dict), (
        f"'qa' must be null or a dict, got: {type(item['qa'])}"
    )


# ---------------------------------------------------------------------------
# 3. Newest-first ordering
# ---------------------------------------------------------------------------


def test_m6_list_newest_first(client: TestClient):
    """Create two drafts; the second created must appear before the first in the list
    (newest-first ordering by created_at desc).
    """
    token = _setup_tenant(client, "m6-order@test.com", "password123", "M6OrderBrand")

    first = _create_draft(client, token)
    second = _create_draft(client, token)

    resp = client.get("/content/drafts", headers=_auth(token))
    assert resp.status_code == 200, (
        f"expected 200 from GET /content/drafts, got {resp.status_code}: {resp.text}"
    )
    drafts = resp.json()["drafts"]
    ids = [d["draft_id"] for d in drafts]

    assert second["draft_id"] in ids, (
        f"second draft (id={second['draft_id']!r}) not found in list: {ids}"
    )
    assert first["draft_id"] in ids, (
        f"first draft (id={first['draft_id']!r}) not found in list: {ids}"
    )

    second_pos = ids.index(second["draft_id"])
    first_pos = ids.index(first["draft_id"])

    assert second_pos < first_pos, (
        f"newest-first: second draft (pos={second_pos}) must appear before "
        f"first draft (pos={first_pos})"
    )


# ---------------------------------------------------------------------------
# 4. Status filter — ?status=draft shows only draft-status items
# ---------------------------------------------------------------------------


def test_m6_list_filter_status_draft(client: TestClient):
    """?status=draft returns only drafts with status=='draft'.

    Create two drafts; approve one; then ?status=draft shows only the
    remaining unapproved draft, not the approved one.
    """
    token = _setup_tenant(
        client, "m6-filt-draft@test.com", "password123", "M6FiltDraftBrand"
    )

    draft_a = _create_draft(client, token)
    draft_b = _create_draft(client, token)

    # Approve draft_a so it leaves the 'draft' status
    approve_resp = client.post(
        f"/content/drafts/{draft_a['draft_id']}/approve", headers=_auth(token)
    )
    assert approve_resp.status_code == 200, f"approve failed: {approve_resp.text}"

    resp = client.get(
        "/content/drafts", params={"status": "draft"}, headers=_auth(token)
    )
    assert resp.status_code == 200, (
        f"expected 200 from GET /content/drafts?status=draft, "
        f"got {resp.status_code}: {resp.text}"
    )
    drafts = resp.json()["drafts"]
    ids = [d["draft_id"] for d in drafts]

    assert draft_b["draft_id"] in ids, (
        f"draft_b (status=draft) must appear in ?status=draft filter; ids={ids}"
    )
    assert draft_a["draft_id"] not in ids, (
        f"draft_a (status=approved) must NOT appear in ?status=draft filter; ids={ids}"
    )
    # All returned items must have status=='draft'
    for d in drafts:
        assert d["status"] == "draft", (
            f"?status=draft must only return drafts with status='draft', "
            f"got item with status={d['status']!r}: {d}"
        )


# ---------------------------------------------------------------------------
# 5. Status filter — ?status=approved shows only approved items
# ---------------------------------------------------------------------------


def test_m6_list_filter_status_approved(client: TestClient):
    """?status=approved returns only the approved draft, not the still-draft one."""
    token = _setup_tenant(
        client, "m6-filt-appr@test.com", "password123", "M6FiltApprBrand"
    )

    draft_a = _create_draft(client, token)
    draft_b = _create_draft(client, token)

    # Approve draft_a only
    approve_resp = client.post(
        f"/content/drafts/{draft_a['draft_id']}/approve", headers=_auth(token)
    )
    assert approve_resp.status_code == 200, f"approve failed: {approve_resp.text}"

    resp = client.get(
        "/content/drafts", params={"status": "approved"}, headers=_auth(token)
    )
    assert resp.status_code == 200, (
        f"expected 200 from GET /content/drafts?status=approved, "
        f"got {resp.status_code}: {resp.text}"
    )
    drafts = resp.json()["drafts"]
    ids = [d["draft_id"] for d in drafts]

    assert draft_a["draft_id"] in ids, (
        f"draft_a (status=approved) must appear in ?status=approved filter; ids={ids}"
    )
    assert draft_b["draft_id"] not in ids, (
        f"draft_b (status=draft) must NOT appear in ?status=approved filter; ids={ids}"
    )
    # All returned items must have status=='approved'
    for d in drafts:
        assert d["status"] == "approved", (
            f"?status=approved must only return drafts with status='approved', "
            f"got item with status={d['status']!r}: {d}"
        )


# ---------------------------------------------------------------------------
# 6. Cross-tenant isolation (CLAUDE.md rule 6)
#    GET /content/drafts scopes by tenant_id; this test proves isolation.
# ---------------------------------------------------------------------------


def test_m6_list_cross_tenant_isolation(client: TestClient):
    """Tenant B's GET /content/drafts list must not contain Tenant A's drafts.

    A distinctive marker is embedded in Tenant A's brief goal. The full raw
    response body from Tenant B's list request is checked for the marker so
    any cross-tenant leak — in draft_id, text, brief, or any other field —
    is detected.

    Proves that the GET /content/drafts query is scoped by tenant_id
    (CLAUDE.md rule 6: tenant isolation is absolute).
    """
    MARKER = "عنصر_انحصاری_مستاجر_الف_M6_ISOLATION_UNIQUE"

    token_a = _setup_tenant(client, "m6-xta@test.com", "password123", "M6CrossTenantA")
    token_b = _setup_tenant(client, "m6-xtb@test.com", "password123", "M6CrossTenantB")

    # Tenant A creates a draft with the isolation marker in the brief goal
    brief_with_marker = {**_BRIEF, "goal": MARKER}
    resp_a = client.post(
        "/content/drafts",
        json={"brief": brief_with_marker},
        headers=_auth(token_a),
    )
    assert resp_a.status_code == 201, f"Tenant A draft create failed: {resp_a.text}"

    # Tenant B creates their own unrelated draft
    _create_draft(client, token_b)

    # Tenant B's list must not contain Tenant A's marker anywhere in the body
    resp_b = client.get("/content/drafts", headers=_auth(token_b))
    assert resp_b.status_code == 200, (
        f"Tenant B GET /content/drafts should return 200, "
        f"got {resp_b.status_code}: {resp_b.text}"
    )
    assert MARKER not in resp_b.text, (
        f"Tenant B's draft list must not contain Tenant A's marker.\n"
        f"marker={MARKER!r}\nresponse={resp_b.text!r}"
    )


# ---------------------------------------------------------------------------
# 7. Invalid status value → 422
# ---------------------------------------------------------------------------


def test_m6_list_invalid_status_returns_422(client: TestClient):
    """GET /content/drafts?status=<invalid_value> → 422.

    The status query parameter must be validated against the allowed enum
    values (draft|approved|edited|rejected). An unrecognised value must
    return 422 Unprocessable Entity, not 200 or 400.
    """
    token = _setup_tenant(client, "m6-422@test.com", "password123", "M6InvalidBrand")

    resp = client.get(
        "/content/drafts",
        params={"status": "completely_invalid_status_value"},
        headers=_auth(token),
    )
    assert resp.status_code == 422, (
        f"invalid status query param must return 422, "
        f"got {resp.status_code}: {resp.text}"
    )
