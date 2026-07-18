"""
M4 acceptance tests — Content Generation (brief → RAG draft).

Routes under test:
  POST /content/drafts
  GET  /content/drafts/{id}
  POST /content/drafts/{id}/approve
  PUT  /content/drafts/{id}
  POST /content/drafts/{id}/reject
  GET  /content/apprentice-log

All tests named test_m4_<criterion> and FAIL until implementation provides
the /content/* routes and the A0 apprentice-log persistence.

env EMBED_MODE=fake and COMPLETE_MODE=fake are set at module level so the
implementation uses deterministic fake embedder / fake completer — no network
calls, no model-gateway required in CI.
"""

from __future__ import annotations

import os

# Must be set BEFORE any import of rpim_core_api.* so the implementation
# uses deterministic fake mode (established pattern from test_m2_brain.py).
os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# A distinctive fact sentence: short enough to be a single chunk (≤ 700 chars),
# specific enough that any appearance in draft text or context_refs proves RAG
# context reached the content generator.
_DISTINCTIVE_FACT = (
    "واقعیت منحصربه‌فرد: نرخ تبدیل محصول الفا در سال نود و نه درصد بود."
)

# Fragment of the distinctive fact used in assertions (shorter to avoid
# false negatives from whitespace / encoding differences).
_FACT_FRAGMENT = "نرخ تبدیل محصول الفا"

_BRIEF = {
    "goal": "افزایش آگاهی از برند",
    "audience": "مدیران میان‌رده",
    "channel": "اینستاگرام",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}

_TONE = "لحن آزمایشی"

# ---------------------------------------------------------------------------
# Helpers (same pattern as test_m2_brain.py / test_m1_onboarding.py)
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
    """Register, PUT brand profile with _TONE, upload brain source with
    _DISTINCTIVE_FACT. Returns access_token.

    Precondition required by M4 acceptance criteria: the implementation
    must retrieve context from the brain source and embed both the tone and
    a fragment of that context in the fake-generated draft text.
    """
    token = _register(client, email, password, tenant_name)["access_token"]

    # PUT brand profile — tone is embedded by the fake completer into draft text.
    client.put(
        "/brand-profile",
        json={
            "tone": _TONE,
            "personas": [],
            "lexicon": {},
            "allowed_claims": [],
            "forbidden_claims": [],
            "red_lines": [],
        },
        headers=_auth(token),
    )

    # Upload brain source containing the distinctive fact — fake embed makes
    # it the top-ranked context chunk when the brief is used as the query.
    client.post(
        "/brain/sources",
        json={"title": "منبع آزمایشی", "kind": "upload", "text": _DISTINCTIVE_FACT},
        headers=_auth(token),
    )

    return token


# ---------------------------------------------------------------------------
# 1. POST /content/drafts — auth guard, 201 shape, RAG context reaches draft
# ---------------------------------------------------------------------------


def test_m4_draft_create_requires_auth(client: TestClient):
    """POST /content/drafts without Bearer token → 401."""
    resp = client.post("/content/drafts", json={"brief": _BRIEF})
    assert resp.status_code == 401, (
        f"expected 401 for unauthenticated POST /content/drafts, got {resp.status_code}"
    )


def test_m4_draft_create_returns_201(client: TestClient):
    """POST /content/drafts with valid auth and brief → 201."""
    token = _setup_tenant(client, "m4-create@test.com", "password123", "M4CreateBrand")
    resp = client.post("/content/drafts", json={"brief": _BRIEF}, headers=_auth(token))
    assert resp.status_code == 201, (
        f"expected 201 from POST /content/drafts, got {resp.status_code}: {resp.text}"
    )


def test_m4_draft_create_response_shape(client: TestClient):
    """201 response must contain draft_id (non-empty str), text (non-empty str),
    context_refs (list), flag_unsourced (bool), status=='draft'."""
    token = _setup_tenant(client, "m4-shape@test.com", "password123", "M4ShapeBrand")
    resp = client.post("/content/drafts", json={"brief": _BRIEF}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert "draft_id" in body, f"'draft_id' missing from response: {body}"
    assert body["draft_id"], "'draft_id' must be non-empty"

    assert "text" in body, f"'text' missing from response: {body}"
    assert body["text"], "'text' must be non-empty"

    assert "context_refs" in body, f"'context_refs' missing from response: {body}"
    assert isinstance(body["context_refs"], list), (
        f"'context_refs' must be a list, got {type(body['context_refs'])}"
    )

    assert "flag_unsourced" in body, f"'flag_unsourced' missing from response: {body}"
    assert isinstance(body["flag_unsourced"], bool), (
        f"'flag_unsourced' must be bool, got {type(body['flag_unsourced'])}"
    )

    assert body.get("status") == "draft", (
        f"'status' must be 'draft', got: {body.get('status')}"
    )


def test_m4_draft_create_rag_context_reaches_output(client: TestClient):
    """In COMPLETE_MODE=fake the distinctive-fact fragment must appear in
    text OR in context_refs — proving retrieved context reaches the draft."""
    token = _setup_tenant(client, "m4-rag@test.com", "password123", "M4RAGBrand")
    resp = client.post("/content/drafts", json={"brief": _BRIEF}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    body = resp.json()

    text: str = body.get("text", "")
    context_refs: list = body.get("context_refs", [])

    in_text = _FACT_FRAGMENT in text
    in_refs = any(_FACT_FRAGMENT in str(ref) for ref in context_refs)

    assert in_text or in_refs, (
        f"COMPLETE_MODE=fake: distinctive fact fragment must appear in text or context_refs.\n"
        f"fragment={_FACT_FRAGMENT!r}\n"
        f"text={text!r}\n"
        f"context_refs={context_refs!r}"
    )


# ---------------------------------------------------------------------------
# 2. GET /content/drafts/{id} — owner gets 200; other tenant gets 404
# ---------------------------------------------------------------------------


def test_m4_draft_get_returns_200_for_owner(client: TestClient):
    """GET /content/drafts/{id} by the owning tenant → 200."""
    token = _setup_tenant(client, "m4-get@test.com", "password123", "M4GetBrand")
    create_resp = client.post(
        "/content/drafts", json={"brief": _BRIEF}, headers=_auth(token)
    )
    assert create_resp.status_code == 201, create_resp.text
    draft_id = create_resp.json()["draft_id"]

    resp = client.get(f"/content/drafts/{draft_id}", headers=_auth(token))
    assert resp.status_code == 200, (
        f"owner GET /content/drafts/{draft_id} should be 200, got {resp.status_code}: {resp.text}"
    )


def test_m4_draft_get_returns_404_for_other_tenant(client: TestClient):
    """GET /content/drafts/{id} by a different tenant → 404 (cross-tenant isolation)."""
    token_a = _setup_tenant(
        client, "m4-isol-a@test.com", "password123", "M4IsolABrand"
    )
    create_resp = client.post(
        "/content/drafts", json={"brief": _BRIEF}, headers=_auth(token_a)
    )
    assert create_resp.status_code == 201, create_resp.text
    draft_id = create_resp.json()["draft_id"]

    token_b = _register(
        client, "m4-isol-b@test.com", "password123", "M4IsolBBrand"
    )["access_token"]
    resp = client.get(f"/content/drafts/{draft_id}", headers=_auth(token_b))
    assert resp.status_code == 404, (
        f"Tenant B accessing Tenant A's draft must get 404, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 3. POST /content/drafts/{id}/approve — 200 + A0 apprentice log
# ---------------------------------------------------------------------------


def test_m4_draft_approve_returns_200_with_approved_status(client: TestClient):
    """POST /content/drafts/{id}/approve → 200 {"status": "approved"}."""
    token = _setup_tenant(client, "m4-approve@test.com", "password123", "M4ApproveBrand")
    create_resp = client.post(
        "/content/drafts", json={"brief": _BRIEF}, headers=_auth(token)
    )
    assert create_resp.status_code == 201, create_resp.text
    draft_id = create_resp.json()["draft_id"]

    resp = client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))
    assert resp.status_code == 200, (
        f"approve should return 200, got {resp.status_code}: {resp.text}"
    )
    assert resp.json().get("status") == "approved", (
        f"status must be 'approved', got: {resp.json()}"
    )


def test_m4_approve_records_apprentice_log_entry(client: TestClient):
    """After approve, GET /content/apprentice-log returns 200 {"entries": [...]}
    containing an entry with kind=='approved', schema_version>=1, and payload
    that includes both the brief goal and the output text."""
    token = _setup_tenant(client, "m4-log-app@test.com", "password123", "M4LogAppBrand")
    create_resp = client.post(
        "/content/drafts", json={"brief": _BRIEF}, headers=_auth(token)
    )
    assert create_resp.status_code == 201, create_resp.text
    create_body = create_resp.json()
    draft_id = create_body["draft_id"]
    draft_text = create_body["text"]

    client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token))

    log_resp = client.get("/content/apprentice-log", headers=_auth(token))
    assert log_resp.status_code == 200, (
        f"apprentice-log should return 200, got {log_resp.status_code}: {log_resp.text}"
    )
    log_body = log_resp.json()
    assert "entries" in log_body, f"'entries' key missing from apprentice-log: {log_body}"
    entries = log_body["entries"]
    assert isinstance(entries, list), f"'entries' must be a list, got {type(entries)}"

    approved = [e for e in entries if e.get("kind") == "approved"]
    assert len(approved) >= 1, (
        f"apprentice-log must have at least one kind=='approved' entry; entries: {entries}"
    )

    entry = approved[0]
    assert entry.get("schema_version", 0) >= 1, (
        f"schema_version must be >= 1 in approved entry; got: {entry}"
    )

    payload = entry.get("payload", {})

    # payload must embed the brief (goal is a reliable unique marker)
    assert payload.get("brief", {}).get("goal") == _BRIEF["goal"], (
        f"approved-entry payload must contain the brief's goal.\n"
        f"goal={_BRIEF['goal']!r}\npayload={payload}"
    )
    # payload must embed the generated output text (direct field comparison —
    # string-serialized containment breaks on escaped newlines/ZWNJ)
    assert payload.get("output") == draft_text, (
        f"approved-entry payload must contain the output draft text.\n"
        f"draft_text={draft_text!r}\npayload={payload}"
    )


# ---------------------------------------------------------------------------
# 4. PUT /content/drafts/{id} — human edit; apprentice log captures both texts
# ---------------------------------------------------------------------------


def test_m4_draft_edit_returns_200_with_edited_status(client: TestClient):
    """PUT /content/drafts/{id} {"edited_text": ...} → 200 {"status": "edited"}."""
    token = _setup_tenant(client, "m4-edit@test.com", "password123", "M4EditBrand")
    create_resp = client.post(
        "/content/drafts", json={"brief": _BRIEF}, headers=_auth(token)
    )
    assert create_resp.status_code == 201, create_resp.text
    draft_id = create_resp.json()["draft_id"]

    resp = client.put(
        f"/content/drafts/{draft_id}",
        json={"edited_text": "متن ویرایش‌شده انسانی"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, (
        f"PUT /content/drafts/{draft_id} should return 200, got {resp.status_code}: {resp.text}"
    )
    assert resp.json().get("status") == "edited", (
        f"status must be 'edited', got: {resp.json()}"
    )


def test_m4_edit_records_apprentice_log_with_both_texts(client: TestClient):
    """After edit, apprentice-log has kind=='edited' entry whose payload contains
    BOTH the original draft text AND the human-edited text (blueprint M9 signal)."""
    token = _setup_tenant(
        client, "m4-edit-log@test.com", "password123", "M4EditLogBrand"
    )
    create_resp = client.post(
        "/content/drafts", json={"brief": _BRIEF}, headers=_auth(token)
    )
    assert create_resp.status_code == 201, create_resp.text
    create_body = create_resp.json()
    draft_id = create_body["draft_id"]
    original_text = create_body["text"]

    edited_text = "متن ویرایش‌شده انسانی برای آزمایش لاگ"
    client.put(
        f"/content/drafts/{draft_id}",
        json={"edited_text": edited_text},
        headers=_auth(token),
    )

    log_resp = client.get("/content/apprentice-log", headers=_auth(token))
    assert log_resp.status_code == 200, log_resp.text
    entries = log_resp.json().get("entries", [])

    edited = [e for e in entries if e.get("kind") == "edited"]
    assert len(edited) >= 1, (
        f"apprentice-log must have at least one kind=='edited' entry; entries: {entries}"
    )

    payload = edited[0].get("payload", {})

    assert payload.get("draft") == original_text, (
        f"edited-entry payload must contain the original draft text.\n"
        f"original_text={original_text!r}\npayload={payload}"
    )
    assert payload.get("edited") == edited_text, (
        f"edited-entry payload must contain the human-edited text.\n"
        f"edited_text={edited_text!r}\npayload={payload}"
    )


# ---------------------------------------------------------------------------
# 5. POST /content/drafts/{id}/reject — structured rejection signal in A0 log
# ---------------------------------------------------------------------------


def test_m4_draft_reject_returns_200_with_rejected_status(client: TestClient):
    """POST /content/drafts/{id}/reject with valid reason_code → 200 {"status": "rejected"}."""
    token = _setup_tenant(
        client, "m4-reject@test.com", "password123", "M4RejectBrand"
    )
    create_resp = client.post(
        "/content/drafts", json={"brief": _BRIEF}, headers=_auth(token)
    )
    assert create_resp.status_code == 201, create_resp.text
    draft_id = create_resp.json()["draft_id"]

    resp = client.post(
        f"/content/drafts/{draft_id}/reject",
        json={"reason_code": "tone", "note": "لحن مناسب نیست"},
        headers=_auth(token),
    )
    assert resp.status_code == 200, (
        f"reject should return 200, got {resp.status_code}: {resp.text}"
    )
    assert resp.json().get("status") == "rejected", (
        f"status must be 'rejected', got: {resp.json()}"
    )


def test_m4_reject_records_apprentice_log_with_reason_code(client: TestClient):
    """After reject, apprentice-log has kind=='rejected' entry whose payload
    contains the structured reason_code."""
    token = _setup_tenant(
        client, "m4-rej-log@test.com", "password123", "M4RejLogBrand"
    )
    create_resp = client.post(
        "/content/drafts", json={"brief": _BRIEF}, headers=_auth(token)
    )
    assert create_resp.status_code == 201, create_resp.text
    draft_id = create_resp.json()["draft_id"]

    client.post(
        f"/content/drafts/{draft_id}/reject",
        json={"reason_code": "fact", "note": None},
        headers=_auth(token),
    )

    log_resp = client.get("/content/apprentice-log", headers=_auth(token))
    assert log_resp.status_code == 200, log_resp.text
    entries = log_resp.json().get("entries", [])

    rejected = [e for e in entries if e.get("kind") == "rejected"]
    assert len(rejected) >= 1, (
        f"apprentice-log must have at least one kind=='rejected' entry; entries: {entries}"
    )

    payload = rejected[0].get("payload", {})
    assert "fact" in str(payload), (
        f"rejected-entry payload must contain reason_code 'fact'; got: {payload}"
    )


# ---------------------------------------------------------------------------
# 6. Invalid reason_code → 422
# ---------------------------------------------------------------------------


def test_m4_reject_invalid_reason_code_returns_422(client: TestClient):
    """POST /content/drafts/{id}/reject with an unknown reason_code → 422."""
    token = _setup_tenant(
        client, "m4-invalid@test.com", "password123", "M4InvalidBrand"
    )
    create_resp = client.post(
        "/content/drafts", json={"brief": _BRIEF}, headers=_auth(token)
    )
    assert create_resp.status_code == 201, create_resp.text
    draft_id = create_resp.json()["draft_id"]

    resp = client.post(
        f"/content/drafts/{draft_id}/reject",
        json={"reason_code": "completely_invalid_code", "note": None},
        headers=_auth(token),
    )
    assert resp.status_code == 422, (
        f"invalid reason_code must return 422, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 7. Cross-tenant isolation (CLAUDE.md rule 6)
#    New tables for content drafts + apprentice-log ship with this test.
# ---------------------------------------------------------------------------


def test_m4_content_cross_tenant_isolation(client: TestClient):
    """Tenant A creates and approves a draft containing a marker.
    Tenant B's GET /content/drafts/{A's id} → 404.
    Tenant B's GET /content/apprentice-log must not contain A's marker.

    Proves that content_drafts and apprentice_log tables are scoped by
    tenant_id and never leak data across tenant boundaries (CLAUDE.md rule 6).
    """
    MARKER = "عنصر_انحصاری_مستاجر_الف_M4_ISOLATION_UNIQUE"

    # --- Tenant A: set up with marker as tone and brain source ---
    token_a = _register(
        client, "m4-xta@test.com", "password123", "M4CrossTenantA"
    )["access_token"]
    client.put(
        "/brand-profile",
        json={
            "tone": MARKER,
            "personas": [],
            "lexicon": {},
            "allowed_claims": [],
            "forbidden_claims": [],
            "red_lines": [],
        },
        headers=_auth(token_a),
    )
    client.post(
        "/brain/sources",
        json={"title": "منبع الف", "kind": "upload", "text": MARKER},
        headers=_auth(token_a),
    )

    # A creates and approves a draft (A0 log entry created)
    create_a = client.post(
        "/content/drafts", json={"brief": _BRIEF}, headers=_auth(token_a)
    )
    assert create_a.status_code == 201, f"Tenant A draft create failed: {create_a.text}"
    draft_id_a = create_a.json()["draft_id"]

    client.post(f"/content/drafts/{draft_id_a}/approve", headers=_auth(token_a))

    # --- Tenant B: register only (no brain source, no profile needed) ---
    token_b = _register(
        client, "m4-xtb@test.com", "password123", "M4CrossTenantB"
    )["access_token"]

    # B must get 404 when trying to access A's draft
    get_resp = client.get(f"/content/drafts/{draft_id_a}", headers=_auth(token_b))
    assert get_resp.status_code == 404, (
        f"Tenant B accessing Tenant A's draft must get 404, "
        f"got {get_resp.status_code}: {get_resp.text}"
    )

    # B's apprentice-log must not contain A's marker (isolation of log table)
    log_resp = client.get("/content/apprentice-log", headers=_auth(token_b))
    assert log_resp.status_code == 200, (
        f"GET /content/apprentice-log for Tenant B should return 200, "
        f"got {log_resp.status_code}: {log_resp.text}"
    )
    assert MARKER not in log_resp.text, (
        f"Tenant B's apprentice-log must not contain Tenant A's marker.\n"
        f"marker={MARKER!r}\nlog_response={log_resp.text!r}"
    )


# ---------------------------------------------------------------------------
# 8. Cross-leg outages surface as clean 503s, never raw 500s
# ---------------------------------------------------------------------------


def test_m4_draft_embed_failure_returns_503_not_500(client: TestClient, monkeypatch):
    """A dead/cold embedding path (bge-m3 still loading after a redeploy) must
    be a clean 503 whose detail names the embedding service — the dashboard
    maps it to Persian. This exact path failed the pilot's first draft."""
    import httpx  # noqa: PLC0415

    import rpim_core_api.brain.service as brain_service  # noqa: PLC0415

    def dead_embed(texts, tenant_id=None):
        raise httpx.ReadTimeout("cold bge-m3 load")

    # M20 moved retrieval behind the BrandBrain facade — the embed seam
    # lives there now; the 503 contract is unchanged.
    monkeypatch.setattr(brain_service, "embed_texts", dead_embed)

    token = _setup_tenant(
        client, "draft-embed-down@example.com", "Password123!", "DraftEmbedDown"
    )
    resp = client.post("/content/drafts", json={"brief": _BRIEF}, headers=_auth(token))
    assert resp.status_code == 503, (
        f"embed failure must be 503, got {resp.status_code}: {resp.text}"
    )
    assert "embedding" in resp.json()["detail"].lower(), (
        f"detail must name the embedding service: {resp.json()}"
    )


def test_m4_draft_gateway_failure_returns_503_not_500(client: TestClient, monkeypatch):
    """A dead model gateway (T2 chain down, provider quota burned) must be a
    clean 503 naming the gateway — the dashboard maps it to Persian."""
    import httpx  # noqa: PLC0415

    import rpim_core_api.routers.content as content_router  # noqa: PLC0415

    def dead_complete(prompt, system=None, tenant_id=None, task="t1", request_id=None):
        raise httpx.ConnectError("gateway down")

    monkeypatch.setattr(content_router, "complete", dead_complete)

    token = _setup_tenant(
        client, "draft-gw-down@example.com", "Password123!", "DraftGwDown"
    )
    resp = client.post("/content/drafts", json={"brief": _BRIEF}, headers=_auth(token))
    assert resp.status_code == 503, (
        f"gateway failure must be 503, got {resp.status_code}: {resp.text}"
    )
    assert "gateway" in resp.json()["detail"].lower(), (
        f"detail must name the model gateway: {resp.json()}"
    )


def test_m4_draft_prompt_demands_final_output_only(client: TestClient, monkeypatch):
    """Pilot A0 reject signals: drafts opened with meta-preambles («پست
    تلگرام و بله برای معرفی…») and option menus. The M4 prompt contract must
    demand the final post text only (ADR 0031 carried risk)."""
    import rpim_core_api.routers.content as content_router  # noqa: PLC0415

    captured: dict = {}

    def spy_complete(prompt, system=None, tenant_id=None, task="t1", request_id=None):
        captured["system"] = system
        captured["prompt"] = prompt
        return "متن نهایی پست"

    monkeypatch.setattr(content_router, "complete", spy_complete)

    token = _setup_tenant(
        client, "prompt-contract@example.com", "Password123!", "PromptContract"
    )
    resp = client.post("/content/drafts", json={"brief": _BRIEF}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    for needle in ("بدون مقدمه", "چند گزینه", "بازگویی بریف"):
        assert needle in captured["system"], (
            f"system prompt must carry the final-output-only contract ({needle}): "
            f"{captured['system']}"
        )
    assert "متن نهایی پست" in captured["prompt"], (
        f"prompt's last line must demand the final post text: {captured['prompt']}"
    )
