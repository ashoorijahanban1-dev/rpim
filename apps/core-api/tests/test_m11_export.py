"""
M11 acceptance tests — One-click full data export.

Blueprint §13.1 MVP Definition of Done: the tenant owns every byte of their
data (brand profile, onboarding answers, brain, drafts, A0 apprentice log,
publish jobs).  A single GET /export returns everything in a single JSON
package ready for one-click download.

All tests named test_export_<criterion>.
File named test_m11_export.py so it sorts last in collection.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path

# Env vars must be set BEFORE any rpim_core_api import — same pattern as M7/M9.
os.environ["PUBLISH_MODE"] = "fake"
os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("LEDGER_MODE", "fake")
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", secrets.token_hex(32))

from fastapi.testclient import TestClient  # noqa: E402

# ---------------------------------------------------------------------------
# Repo root — derived from test file location; NEVER hardcoded.
#   parents[0] = apps/core-api/tests/
#   parents[1] = apps/core-api/
#   parents[2] = apps/
#   parents[3] = <repo root>
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]
_FA_JSON_PATH = _REPO_ROOT / "apps" / "dashboard" / "locales" / "fa.json"
_EXPORT_PAGE_PATH = _REPO_ROOT / "apps" / "dashboard" / "app" / "export" / "page.tsx"

# Persian Unicode block U+0600–U+06FF (same regex used by every other dashboard test).
_PERSIAN_RE = re.compile(r"[؀-ۿ]")

_REQUIRED_TOP_LEVEL_KEYS = {
    "export_version",
    "generated_at",
    "tenant",
    "brand_profile",
    "onboarding",
    "brain",
    "drafts",
    "apprentice_events",
    "publish_jobs",
}
_REQUIRED_EXPORT_LOCALE_KEYS = {"title", "download", "downloading", "done", "error"}

# ---------------------------------------------------------------------------
# Brief fixture used by content/draft helpers.
# ---------------------------------------------------------------------------
_BRIEF = {
    "goal": "افزایش فروش",
    "audience": "مشتریان",
    "channel": "telegram",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}


# ---------------------------------------------------------------------------
# Helpers — mirrors M7/M9 pattern exactly.
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
    """Register and return access_token."""
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
    campaign_code: str = "camp_export_001",
) -> dict:
    resp = client.post(
        "/publish/jobs",
        json={
            "draft_id": draft_id,
            "channel": channel,
            "chat_id": chat_id,
            "campaign_code": campaign_code,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, f"job create failed: {resp.text}"
    return resp.json()


def _dispatch(client: TestClient) -> dict:
    resp = client.post(
        "/publish/dispatch",
        headers={"X-Internal-Token": _INTERNAL_TOKEN},
    )
    assert resp.status_code == 200, f"dispatch failed: {resp.text}"
    return resp.json()


# ===========================================================================
# 1. Auth guard — 401 without Bearer token
# ===========================================================================


def test_export_requires_auth(client: TestClient):
    """GET /export without Bearer token → 401."""
    resp = client.get("/export")
    assert resp.status_code == 401, (
        f"expected 401 for unauthenticated GET /export, got {resp.status_code}: {resp.text}"
    )


# ===========================================================================
# 2. 200 response shape — top-level keys and scalar fields
# ===========================================================================


def test_export_200_returns_all_top_level_keys(client: TestClient):
    """GET /export (authenticated) → 200 with ALL required top-level keys present."""
    token = _setup_tenant(client, "m11-keys@test.com", "pw123456", "M11Keys")
    resp = client.get("/export", headers=_auth(token))
    assert resp.status_code == 200, (
        f"expected 200 for authenticated GET /export, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    missing = _REQUIRED_TOP_LEVEL_KEYS - set(body.keys())
    assert not missing, (
        f"GET /export response missing required top-level keys: {missing}\n"
        f"present keys: {sorted(body.keys())}"
    )


def test_export_version_is_one(client: TestClient):
    """GET /export → export_version == 1 (contract version pinned in spec)."""
    token = _setup_tenant(client, "m11-ver@test.com", "pw123456", "M11Ver")
    resp = client.get("/export", headers=_auth(token))
    assert resp.status_code == 200, f"GET /export must return 200: {resp.text}"
    body = resp.json()
    assert body.get("export_version") == 1, (
        f"export_version must be exactly 1 (int), got: {body.get('export_version')!r}"
    )


def test_export_generated_at_is_iso_datetime(client: TestClient):
    """GET /export → generated_at is a non-empty ISO 8601 datetime string."""
    token = _setup_tenant(client, "m11-ts@test.com", "pw123456", "M11Ts")
    resp = client.get("/export", headers=_auth(token))
    assert resp.status_code == 200, f"GET /export must return 200: {resp.text}"
    body = resp.json()
    gen_at = body.get("generated_at")
    assert isinstance(gen_at, str) and gen_at, (
        f"generated_at must be a non-empty string, got: {gen_at!r}"
    )
    try:
        datetime.fromisoformat(gen_at)
    except (ValueError, TypeError) as exc:
        raise AssertionError(
            f"generated_at must be a valid ISO 8601 datetime string, got: {gen_at!r}"
        ) from exc


def test_export_tenant_shape(client: TestClient):
    """GET /export → tenant object has id, name, created_at; name matches registration."""
    reg = _register(client, "m11-shape@test.com", "pw123456", "M11Shape")
    token = reg["access_token"]
    resp = client.get("/export", headers=_auth(token))
    assert resp.status_code == 200, f"GET /export must return 200: {resp.text}"
    body = resp.json()
    tenant = body.get("tenant")
    assert isinstance(tenant, dict), f"tenant must be a dict, got: {tenant!r}"
    for key in ("id", "name", "created_at"):
        assert key in tenant, f"tenant object missing key '{key}': {tenant}"
    assert tenant["id"] == reg["tenant_id"], (
        f"tenant.id must match the registered tenant_id: "
        f"expected {reg['tenant_id']!r}, got {tenant['id']!r}"
    )
    assert tenant["name"] == "M11Shape", (
        f"tenant.name must match registered tenant_name, got: {tenant['name']!r}"
    )


# ===========================================================================
# 3. Content-Disposition — one-click download semantics
# ===========================================================================


def test_export_content_disposition_attachment(client: TestClient):
    """GET /export → Content-Disposition header contains 'attachment' and 'rpim-export'."""
    token = _setup_tenant(client, "m11-cd@test.com", "pw123456", "M11CD")
    resp = client.get("/export", headers=_auth(token))
    assert resp.status_code == 200, f"GET /export must return 200: {resp.text}"
    cd = resp.headers.get("content-disposition", "")
    assert "attachment" in cd, (
        f"Content-Disposition must contain 'attachment' for one-click download: {cd!r}"
    )
    assert "rpim-export" in cd, (
        f"Content-Disposition must contain 'rpim-export' in filename: {cd!r}"
    )


# ===========================================================================
# 4. Empty tenant — all keys present, nulls for profile/onboarding, empty lists
# ===========================================================================


def test_export_empty_tenant_all_keys_present(client: TestClient):
    """Fresh tenant (no data) → 200 with all required top-level keys (none missing)."""
    token = _setup_tenant(client, "m11-emk@test.com", "pw123456", "M11EmptyKeys")
    resp = client.get("/export", headers=_auth(token))
    assert resp.status_code == 200, (
        f"GET /export must return 200 for a fresh tenant: {resp.text}"
    )
    body = resp.json()
    missing = _REQUIRED_TOP_LEVEL_KEYS - set(body.keys())
    assert not missing, (
        f"Empty-tenant export missing top-level keys: {missing}\nbody: {body}"
    )


def test_export_empty_tenant_nulls_for_profile_and_onboarding(client: TestClient):
    """Fresh tenant → brand_profile is null AND onboarding is null."""
    token = _setup_tenant(client, "m11-emnull@test.com", "pw123456", "M11EmNull")
    resp = client.get("/export", headers=_auth(token))
    assert resp.status_code == 200, f"GET /export must return 200: {resp.text}"
    body = resp.json()
    assert body.get("brand_profile") is None, (
        f"brand_profile must be null for a fresh tenant, got: {body.get('brand_profile')!r}"
    )
    assert body.get("onboarding") is None, (
        f"onboarding must be null for a fresh tenant, got: {body.get('onboarding')!r}"
    )


def test_export_empty_tenant_lists_are_empty(client: TestClient):
    """Fresh tenant → drafts==[], apprentice_events==[], publish_jobs==[],
    brain.sources==[], brain.chunks_count==0."""
    token = _setup_tenant(client, "m11-emlists@test.com", "pw123456", "M11EmLists")
    resp = client.get("/export", headers=_auth(token))
    assert resp.status_code == 200, f"GET /export must return 200: {resp.text}"
    body = resp.json()
    assert body.get("drafts") == [], (
        f"drafts must be [] for fresh tenant, got: {body.get('drafts')!r}"
    )
    assert body.get("apprentice_events") == [], (
        f"apprentice_events must be [] for fresh tenant, got: {body.get('apprentice_events')!r}"
    )
    assert body.get("publish_jobs") == [], (
        f"publish_jobs must be [] for fresh tenant, got: {body.get('publish_jobs')!r}"
    )
    brain = body.get("brain", {})
    assert isinstance(brain, dict), f"brain must be a dict, got: {brain!r}"
    assert brain.get("sources") == [], (
        f"brain.sources must be [] for fresh tenant, got: {brain.get('sources')!r}"
    )
    assert brain.get("chunks_count") == 0, (
        f"brain.chunks_count must be 0 for fresh tenant, got: {brain.get('chunks_count')!r}"
    )


# ===========================================================================
# 5. Round-trip completeness end-to-end
# ===========================================================================


def test_export_e2e_roundtrip(client: TestClient):
    """Full data round-trip:
    register → PUT onboarding answers → upload brain source (unique marker text) →
    approve draft1 → edit draft2 → reject draft3 (reason_code) →
    create publish job → dispatch (PUBLISH_MODE=fake) → GET /export →
    assert: brain marker in chunks; all 3 drafts with correct statuses;
    apprentice_events has kinds {approved, edited, rejected}; dispatched job
    has campaign_code and status='sent'; export_version == 1.
    """
    BRAIN_MARKER = f"EXPORT_E2E_BRAIN_MARKER_UNIQUE_{secrets.token_hex(8)}"
    CAMPAIGN_CODE = f"camp_e2e_{secrets.token_hex(6)}"

    token = _setup_tenant(client, "m11-e2e@test.com", "pw123456", "M11E2E")

    # -- Partial onboarding answers --
    oa = client.put(
        "/onboarding/interview/answers",
        json={"answers": {"tone": "رسمی"}},
        headers=_auth(token),
    )
    assert oa.status_code == 200, f"onboarding PUT answers failed: {oa.text}"

    # -- Brain source with unique marker text --
    brain_resp = client.post(
        "/brain/sources",
        json={"title": "منبع تست صادرات", "kind": "upload", "text": BRAIN_MARKER * 5},
        headers=_auth(token),
    )
    assert brain_resp.status_code == 201, f"brain source create failed: {brain_resp.text}"

    # -- Draft 1: approve → A0 signal 'approved' --
    draft_id_1 = _create_draft(client, token)
    _approve_draft(client, token, draft_id_1)

    # -- Draft 2: edit → A0 signal 'edited' --
    draft_id_2 = _create_draft(client, token)
    edit_resp = client.put(
        f"/content/drafts/{draft_id_2}",
        json={"edited_text": "نسخه ویرایش‌شده برای تست صادرات"},
        headers=_auth(token),
    )
    assert edit_resp.status_code == 200, f"edit draft failed: {edit_resp.text}"

    # -- Draft 3: reject → A0 signal 'rejected' --
    draft_id_3 = _create_draft(client, token)
    reject_resp = client.post(
        f"/content/drafts/{draft_id_3}/reject",
        json={"reason_code": "tone"},
        headers=_auth(token),
    )
    assert reject_resp.status_code == 200, f"reject draft failed: {reject_resp.text}"

    # -- Publish job on the approved draft → dispatch (fake) --
    _create_job(client, token, draft_id_1, campaign_code=CAMPAIGN_CODE)
    _dispatch(client)

    # == GET /export ==
    exp_resp = client.get("/export", headers=_auth(token))
    assert exp_resp.status_code == 200, (
        f"GET /export must return 200 after full e2e setup: {exp_resp.text}"
    )
    body = exp_resp.json()

    # ---- export_version == 1 ----
    assert body.get("export_version") == 1, (
        f"export_version must be 1 in e2e response, got: {body.get('export_version')!r}"
    )

    # ---- brain: unique marker must appear in at least one chunk text ----
    brain = body.get("brain", {})
    assert isinstance(brain, dict), f"brain must be a dict: {brain!r}"
    sources = brain.get("sources", [])
    assert len(sources) >= 1, (
        f"brain.sources must have >=1 entry after upload, got: {sources}"
    )
    # Required fields on each source
    for src in sources:
        for field in ("id", "title", "kind", "status", "created_at", "chunks"):
            assert field in src, f"brain source missing field '{field}': {src}"
        assert isinstance(src["chunks"], list), (
            f"source.chunks must be a list, got: {src['chunks']!r}"
        )
        for chunk in src["chunks"]:
            for cf in ("seq", "text"):
                assert cf in chunk, f"chunk missing field '{cf}': {chunk}"
    # Embeddings must NOT be exported (derived data)
    for src in sources:
        for chunk in src.get("chunks", []):
            assert "embedding" not in chunk, (
                f"chunk must NOT export 'embedding' (derived data): {chunk}"
            )
    # Marker must be present in chunk texts
    all_chunk_texts = [
        chunk["text"]
        for src in sources
        for chunk in src.get("chunks", [])
    ]
    assert any(BRAIN_MARKER in ct for ct in all_chunk_texts), (
        f"brain marker '{BRAIN_MARKER}' must appear in at least one chunk.text.\n"
        f"chunk texts (first 3): {all_chunk_texts[:3]!r}"
    )
    assert isinstance(brain.get("chunks_count"), int) and brain["chunks_count"] >= 1, (
        f"brain.chunks_count must be int >= 1 after upload, got: {brain.get('chunks_count')!r}"
    )

    # ---- drafts: all 3 present with expected statuses and required fields ----
    drafts = body.get("drafts", [])
    assert len(drafts) >= 3, (
        f"drafts must contain at least 3 entries (approved, edited, rejected), got: {len(drafts)}"
    )
    by_id = {d["draft_id"]: d for d in drafts}
    for expected_id, expected_status in [
        (draft_id_1, "approved"),
        (draft_id_2, "edited"),
        (draft_id_3, "rejected"),
    ]:
        assert expected_id in by_id, (
            f"draft {expected_id!r} (status={expected_status!r}) missing from export.drafts"
        )
        actual = by_id[expected_id]
        assert actual["status"] == expected_status, (
            f"draft {expected_id!r} must have status={expected_status!r}, "
            f"got: {actual['status']!r}"
        )
    # Required fields on each draft
    for d in drafts:
        for field in ("draft_id", "brief", "text", "edited_text", "status",
                      "flag_unsourced", "qa", "context_refs", "created_at"):
            assert field in d, f"draft missing required field '{field}': {d}"

    # ---- apprentice_events: all 3 A0 signal kinds present ----
    events = body.get("apprentice_events", [])
    event_kinds = {e["kind"] for e in events}
    for expected_kind in ("approved", "edited", "rejected"):
        assert expected_kind in event_kinds, (
            f"apprentice_events must contain kind={expected_kind!r}; "
            f"found kinds: {event_kinds}"
        )
    for e in events:
        for field in ("kind", "schema_version", "payload", "created_at"):
            assert field in e, f"apprentice_event missing required field '{field}': {e}"

    # ---- publish_jobs: dispatched job has campaign_code and status='sent' ----
    pjobs = body.get("publish_jobs", [])
    assert len(pjobs) >= 1, f"publish_jobs must have at least 1 entry: {pjobs}"
    for pj in pjobs:
        for field in ("job_id", "draft_id", "channel", "chat_id", "campaign_code",
                      "utm", "landing_url", "status", "attempts", "scheduled_at",
                      "sent_at", "created_at"):
            assert field in pj, f"publish_job missing required field '{field}': {pj}"
    matching = [pj for pj in pjobs if pj["campaign_code"] == CAMPAIGN_CODE]
    assert len(matching) >= 1, (
        f"publish_jobs must include entry with campaign_code={CAMPAIGN_CODE!r}: {pjobs}"
    )
    assert matching[0]["status"] == "sent", (
        f"dispatched job must have status='sent', got: {matching[0]['status']!r}"
    )

    # ---- onboarding: answers exported and not null ----
    onboarding = body.get("onboarding")
    assert onboarding is not None, (
        f"onboarding must not be null after PUT answers, got: {onboarding!r}"
    )
    assert "answers" in onboarding and "status" in onboarding, (
        f"onboarding must have 'answers' and 'status' keys: {onboarding}"
    )
    assert onboarding["answers"].get("tone") == "رسمی", (
        f"onboarding.answers must contain the submitted answer for 'tone': {onboarding}"
    )


# ===========================================================================
# 6. Cross-tenant isolation (constitution rule 6)
# ===========================================================================


def test_export_cross_tenant_isolation(client: TestClient):
    """Tenant B's export must NOT contain any of Tenant A's unique data markers.

    Constitution rule 6: every query scoped by tenant_id; every new table
    ships with a test proving cross-tenant isolation.
    Tenant B's tenant.id must be their own (not Tenant A's).
    """
    BRAIN_MARKER_A = f"ISOLATION_MARKER_BRAIN_A_{secrets.token_hex(12)}"
    CAMPAIGN_A = f"ISOLATION_CAMP_A_{secrets.token_hex(8)}"

    reg_a = _register(client, "m11-iso-a@test.com", "pw123456", "M11IsoA")
    reg_b = _register(client, "m11-iso-b@test.com", "pw123456", "M11IsoB")
    token_a = reg_a["access_token"]
    token_b = reg_b["access_token"]
    tenant_id_a = reg_a["tenant_id"]
    tenant_id_b = reg_b["tenant_id"]

    # Tenant A: brain source + approved draft + publish job → dispatch
    client.post(
        "/brain/sources",
        json={"title": "منبع A", "kind": "upload", "text": BRAIN_MARKER_A * 5},
        headers=_auth(token_a),
    )
    draft_id_a = _create_approved_draft(client, token_a)
    _create_job(client, token_a, draft_id_a, campaign_code=CAMPAIGN_A)
    _dispatch(client)

    # Tenant B: their own data so the export is non-trivially populated
    draft_id_b = _create_approved_draft(client, token_b)
    _create_job(client, token_b, draft_id_b, campaign_code="camp_b_only")
    _dispatch(client)

    # Tenant B's export must not contain Tenant A's markers anywhere
    resp_b = client.get("/export", headers=_auth(token_b))
    assert resp_b.status_code == 200, (
        f"Tenant B GET /export must return 200: {resp_b.status_code}: {resp_b.text}"
    )
    raw_b = resp_b.text
    assert BRAIN_MARKER_A not in raw_b, (
        f"Tenant B's export must not contain Tenant A's brain marker.\n"
        f"marker={BRAIN_MARKER_A!r}\n"
        f"response text (first 500 chars)={raw_b[:500]!r}"
    )
    assert CAMPAIGN_A not in raw_b, (
        f"Tenant B's export must not contain Tenant A's campaign code.\n"
        f"marker={CAMPAIGN_A!r}\n"
        f"response text (first 500 chars)={raw_b[:500]!r}"
    )
    assert tenant_id_a not in raw_b, (
        f"Tenant B's export must not expose Tenant A's tenant_id.\n"
        f"tenant_id_a={tenant_id_a!r}\n"
        f"response text (first 500 chars)={raw_b[:500]!r}"
    )
    # Tenant B's export tenant.id must be their own
    body_b = resp_b.json()
    assert body_b.get("tenant", {}).get("id") == tenant_id_b, (
        f"Tenant B's export tenant.id must be {tenant_id_b!r}, "
        f"got: {body_b.get('tenant', {}).get('id')!r}"
    )


# ===========================================================================
# 7. Dashboard static tests — locale file
# ===========================================================================


def test_export_locale_fa_has_export_object():
    """locales/fa.json must have a top-level 'export' JSON object."""
    assert _FA_JSON_PATH.exists(), f"fa.json not found at {_FA_JSON_PATH}"
    data = json.loads(_FA_JSON_PATH.read_text(encoding="utf-8"))
    assert "export" in data, (
        f"fa.json must have a top-level 'export' key; "
        f"found keys: {sorted(data.keys())}"
    )
    assert isinstance(data["export"], dict), (
        f"fa.json['export'] must be a JSON object, got: {type(data['export'])!r}"
    )


def test_export_locale_fa_export_has_required_keys():
    """fa.json['export'] must have exactly the keys: title, download, downloading, done, error."""
    assert _FA_JSON_PATH.exists(), f"fa.json not found at {_FA_JSON_PATH}"
    data = json.loads(_FA_JSON_PATH.read_text(encoding="utf-8"))
    export_obj = data.get("export", {})
    missing = _REQUIRED_EXPORT_LOCALE_KEYS - set(export_obj.keys())
    assert not missing, (
        f"fa.json['export'] missing required keys: {missing}\n"
        f"present keys: {sorted(export_obj.keys())}"
    )


def test_export_locale_fa_export_values_are_persian():
    """Every value in fa.json['export'] must be a non-empty string containing
    Persian characters (regex [؀-ۿ] must match each value).
    Fails if the 'export' object does not exist or any required key is absent."""
    assert _FA_JSON_PATH.exists(), f"fa.json not found at {_FA_JSON_PATH}"
    data = json.loads(_FA_JSON_PATH.read_text(encoding="utf-8"))
    assert "export" in data, (
        f"fa.json must have top-level 'export' key before checking Persian values; "
        f"found keys: {sorted(data.keys())}"
    )
    export_obj = data["export"]
    for key in sorted(_REQUIRED_EXPORT_LOCALE_KEYS):
        assert key in export_obj, (
            f"fa.json['export'] missing key {key!r} — cannot check Persian value; "
            f"present keys: {sorted(export_obj.keys())}"
        )
        value = export_obj[key]
        assert isinstance(value, str) and value.strip(), (
            f"fa.json['export'][{key!r}] must be a non-empty string, got: {value!r}"
        )
        assert _PERSIAN_RE.search(value), (
            f"fa.json['export'][{key!r}] must contain Persian characters "
            f"(regex [؀-ۿ] must match), got: {value!r}"
        )


# ===========================================================================
# 8. Dashboard static tests — export page component
# ===========================================================================


def test_export_dashboard_page_exists():
    """apps/dashboard/app/export/page.tsx must exist (one-click download button page)."""
    assert _EXPORT_PAGE_PATH.exists(), (
        f"Export page not found at {_EXPORT_PAGE_PATH}.\n"
        f"Expected path: apps/dashboard/app/export/page.tsx"
    )


def test_export_dashboard_page_no_hardcoded_persian():
    """apps/dashboard/app/export/page.tsx must contain NO hardcoded Persian text.
    All user-facing strings must come from the fa locale (regex [؀-ۿ] must NOT match)."""
    assert _EXPORT_PAGE_PATH.exists(), (
        f"Export page not found — implement first: {_EXPORT_PAGE_PATH}"
    )
    content = _EXPORT_PAGE_PATH.read_text(encoding="utf-8")
    match = _PERSIAN_RE.search(content)
    assert match is None, (
        f"page.tsx must not contain hardcoded Persian text; "
        f"found {match.group()!r} at position {match.start()}. "  # type: ignore[union-attr]
        f"Move all Persian strings to locales/fa.json under fa.export.*"
    )


def test_export_dashboard_page_references_fa_export():
    """apps/dashboard/app/export/page.tsx must reference 'fa.export' (locale namespace)."""
    assert _EXPORT_PAGE_PATH.exists(), (
        f"Export page not found — implement first: {_EXPORT_PAGE_PATH}"
    )
    content = _EXPORT_PAGE_PATH.read_text(encoding="utf-8")
    assert "fa.export" in content, (
        "page.tsx must reference 'fa.export' to load the locale namespace; "
        "string 'fa.export' not found in the file."
    )


def test_export_dashboard_page_calls_export_endpoint():
    """apps/dashboard/app/export/page.tsx must reference the '/export' API endpoint."""
    assert _EXPORT_PAGE_PATH.exists(), (
        f"Export page not found — implement first: {_EXPORT_PAGE_PATH}"
    )
    content = _EXPORT_PAGE_PATH.read_text(encoding="utf-8")
    assert '"/export"' in content or "'/export'" in content or "`/export`" in content, (
        "page.tsx must call the '/export' API endpoint; "
        "none of '\"/export\"', \"'/export'\", '`/export`' found in the file."
    )
