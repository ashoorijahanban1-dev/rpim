"""
M1 acceptance-criteria tests — Conversational Onboarding Interview.

Tests are named test_m1_onboarding_<criterion> and MUST FAIL until the
implementation provides:
  - GET  /onboarding/interview
  - PUT  /onboarding/interview/answers
  - POST /onboarding/interview/complete
  - GET  /brand-profile  (augmented with allowed_claims)

These tests are black-box: they only exercise the HTTP API; they do NOT import
ORM models or inspect the database directly.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers — reuse the register pattern from test_m1_identity_tenancy.py
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = {
    "tone",
    "personas",
    "lexicon",
    "allowed_claims",
    "forbidden_claims",
    "red_lines",
}

# All six fields satisfied; used for completion tests.
_ALL_ANSWERS: dict = {
    "tone": "صمیمی و حرفه‌ای",
    "personas": ["مدیر فروشگاه", "کارمند جوان"],
    "lexicon": {"راهکار": "solution", "برند": "brand"},
    "allowed_claims": ["بهترین کیفیت", "قیمت منصفانه"],
    "forbidden_claims": ["ضمانت سود بدون ریسک"],
    "red_lines": ["رقبا را مسخره نکن"],
}


def _register(client: TestClient, email: str, password: str, tenant_name: str) -> str:
    """Register a new tenant/user and return the access_token.

    Password must be ≥8 chars (RegisterIn enforces this).
    """
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "tenant_name": tenant_name},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. GET /onboarding/interview — auth guard & response shape
# ---------------------------------------------------------------------------


def test_m1_onboarding_get_requires_auth(client: TestClient):
    """GET /onboarding/interview without Bearer token → 401."""
    resp = client.get("/onboarding/interview")
    assert resp.status_code == 401, resp.text


def test_m1_onboarding_get_returns_draft_for_fresh_tenant(client: TestClient):
    """GET /onboarding/interview for a brand-new tenant → 200, status 'draft', empty answers."""
    token = _register(client, "fresh@example.com", "password123", "FreshBrand")
    resp = client.get("/onboarding/interview", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "draft", f"expected status 'draft', got: {body.get('status')}"
    assert "questions" in body, f"'questions' key missing from response: {body}"
    assert "answers" in body, f"'answers' key missing from response: {body}"
    assert body["answers"] == {}, f"fresh tenant must have empty answers, got: {body['answers']}"


def test_m1_onboarding_get_questions_structure(client: TestClient):
    """Every question object must have keys id, field, question, kind; kind ∈ text|list|pairs."""
    token = _register(client, "struct@example.com", "password123", "StructBrand")
    resp = client.get("/onboarding/interview", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    questions = resp.json()["questions"]
    assert isinstance(questions, list), "questions must be a list"
    assert len(questions) > 0, "questions list must not be empty"
    valid_kinds = {"text", "list", "pairs"}
    for q in questions:
        assert "id" in q, f"question missing 'id': {q}"
        assert "field" in q, f"question missing 'field': {q}"
        assert "question" in q, f"question missing 'question': {q}"
        assert "kind" in q, f"question missing 'kind': {q}"
        assert q["kind"] in valid_kinds, (
            f"kind '{q['kind']}' not in {valid_kinds}: {q}"
        )


def test_m1_onboarding_get_questions_cover_required_fields(client: TestClient):
    """Field values across all questions must cover exactly the six required fields."""
    token = _register(client, "fields@example.com", "password123", "FieldsBrand")
    resp = client.get("/onboarding/interview", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    fields_present = {q["field"] for q in resp.json()["questions"]}
    assert fields_present == _REQUIRED_FIELDS, (
        f"Questions must cover exactly {_REQUIRED_FIELDS}; got {fields_present}"
    )


# ---------------------------------------------------------------------------
# 2. PUT /onboarding/interview/answers — partial saves allowed
# ---------------------------------------------------------------------------


def test_m1_onboarding_put_answers_requires_auth(client: TestClient):
    """PUT /onboarding/interview/answers without Bearer token → 401."""
    resp = client.put(
        "/onboarding/interview/answers",
        json={"answers": {"tone": "test"}},
    )
    assert resp.status_code == 401, resp.text


def test_m1_onboarding_put_answers_partial_save_returns_200(client: TestClient):
    """PUT with partial answers (only tone + personas) → 200."""
    token = _register(client, "partial@example.com", "password123", "PartialBrand")
    resp = client.put(
        "/onboarding/interview/answers",
        json={"answers": {"tone": "صمیمی و حرفه‌ای", "personas": ["مدیر فروشگاه"]}},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text


def test_m1_onboarding_put_answers_persisted_in_subsequent_get(client: TestClient):
    """After a partial PUT, GET returns those answers merged; status stays 'draft'."""
    token = _register(client, "persist@example.com", "password123", "PersistBrand")
    partial = {"tone": "صمیمی و حرفه‌ای", "personas": ["مدیر فروشگاه"]}
    put_resp = client.put(
        "/onboarding/interview/answers",
        json={"answers": partial},
        headers=_auth(token),
    )
    assert put_resp.status_code == 200, put_resp.text

    get_resp = client.get("/onboarding/interview", headers=_auth(token))
    assert get_resp.status_code == 200, get_resp.text
    body = get_resp.json()
    assert body["status"] == "draft", (
        f"status must still be 'draft' after partial PUT; got: {body['status']}"
    )
    assert body["answers"]["tone"] == "صمیمی و حرفه‌ای", (
        f"tone not persisted in answers: {body['answers']}"
    )
    assert body["answers"]["personas"] == ["مدیر فروشگاه"], (
        f"personas not persisted in answers: {body['answers']}"
    )


# ---------------------------------------------------------------------------
# 3. POST /onboarding/interview/complete
# ---------------------------------------------------------------------------


def test_m1_onboarding_complete_requires_auth(client: TestClient):
    """POST /onboarding/interview/complete without Bearer token → 401."""
    resp = client.post("/onboarding/interview/complete")
    assert resp.status_code == 401, resp.text


def test_m1_onboarding_complete_with_all_fields_returns_completed(client: TestClient):
    """POST /complete after supplying all six answers → 200 with status 'completed'."""
    token = _register(client, "complete@example.com", "password123", "CompleteBrand")
    client.put(
        "/onboarding/interview/answers",
        json={"answers": _ALL_ANSWERS},
        headers=_auth(token),
    )
    resp = client.post("/onboarding/interview/complete", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed", (
        f"expected status 'completed'; got: {resp.json()}"
    )


def test_m1_onboarding_complete_missing_fields_returns_422(client: TestClient):
    """POST /complete when required fields are missing → 422 mentioning the missing field names."""
    token = _register(client, "missing@example.com", "password123", "MissingBrand")
    # Only supply tone — five required fields are absent.
    client.put(
        "/onboarding/interview/answers",
        json={"answers": {"tone": "فقط تن"}},
        headers=_auth(token),
    )
    resp = client.post("/onboarding/interview/complete", headers=_auth(token))
    assert resp.status_code == 422, resp.text
    body_text = resp.text
    missing_fields = _REQUIRED_FIELDS - {"tone"}
    assert any(field in body_text for field in missing_fields), (
        f"422 response must mention at least one missing field name from "
        f"{missing_fields}; got body: {body_text}"
    )


def test_m1_onboarding_complete_missing_fields_status_stays_draft(client: TestClient):
    """After a failed /complete (422), GET /onboarding/interview must still show status 'draft'."""
    token = _register(client, "draft-guard@example.com", "password123", "DraftGuardBrand")
    client.put(
        "/onboarding/interview/answers",
        json={"answers": {"tone": "فقط تن"}},
        headers=_auth(token),
    )
    # Expected to fail with 422; we deliberately ignore the response.
    client.post("/onboarding/interview/complete", headers=_auth(token))

    resp = client.get("/onboarding/interview", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "draft", (
        f"status must remain 'draft' after a failed /complete; got: {resp.json()['status']}"
    )


# ---------------------------------------------------------------------------
# 4. GET /brand-profile after completion — includes allowed_claims
# ---------------------------------------------------------------------------


def test_m1_onboarding_brand_profile_has_allowed_claims_field(client: TestClient):
    """GET /brand-profile must include 'allowed_claims' as a list field (new column)."""
    token = _register(client, "brandprofile@example.com", "password123", "ProfileBrand")
    resp = client.get("/brand-profile", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "allowed_claims" in body, (
        f"GET /brand-profile must expose 'allowed_claims'; got keys: {list(body.keys())}"
    )
    assert isinstance(body["allowed_claims"], list), (
        f"'allowed_claims' must be a list; got: {type(body['allowed_claims'])}"
    )


def test_m1_onboarding_brand_profile_reflects_interview_values(client: TestClient):
    """After interview completion, GET /brand-profile returns all six interview values."""
    token = _register(client, "reflect@example.com", "password123", "ReflectBrand")
    client.put(
        "/onboarding/interview/answers",
        json={"answers": _ALL_ANSWERS},
        headers=_auth(token),
    )
    complete_resp = client.post("/onboarding/interview/complete", headers=_auth(token))
    assert complete_resp.status_code == 200, complete_resp.text

    profile_resp = client.get("/brand-profile", headers=_auth(token))
    assert profile_resp.status_code == 200, profile_resp.text
    body = profile_resp.json()

    assert body["tone"] == _ALL_ANSWERS["tone"], f"tone mismatch: {body}"
    assert body["personas"] == _ALL_ANSWERS["personas"], f"personas mismatch: {body}"
    assert body["lexicon"] == _ALL_ANSWERS["lexicon"], f"lexicon mismatch: {body}"
    assert body["allowed_claims"] == _ALL_ANSWERS["allowed_claims"], (
        f"allowed_claims mismatch: {body}"
    )
    assert body["forbidden_claims"] == _ALL_ANSWERS["forbidden_claims"], (
        f"forbidden_claims mismatch: {body}"
    )
    assert body["red_lines"] == _ALL_ANSWERS["red_lines"], f"red_lines mismatch: {body}"


# ---------------------------------------------------------------------------
# 5. Cross-tenant isolation (CLAUDE.md rule 6)
#    Every new table ships with a cross-tenant isolation test.
# ---------------------------------------------------------------------------


def test_m1_onboarding_cross_tenant_isolation(client: TestClient):
    """
    Tenant A's draft answers must not appear in Tenant B's interview view.
    After B completes its own interview, A's brand profile must remain unaffected.

    Steps
    -----
    1. Tenant A saves a draft with a distinctive marker string in 'tone'.
    2. Tenant B's GET /onboarding/interview must NOT contain A's marker.
    3. B completes its own (different) interview.
    4. A completes its own interview with the marker in tone.
    5. GET /brand-profile as A must show the marker; must NOT show B's tone.
    """
    MARKER_A = "TENANT_A_UNIQUE_MARKER_XYZ_ISOLATION"

    # --- Tenant A: save a draft with the distinctive marker ---
    token_a = _register(client, "isol-a@example.com", "password123", "IsolBrandA")
    put_a = client.put(
        "/onboarding/interview/answers",
        json={"answers": {"tone": MARKER_A}},
        headers=_auth(token_a),
    )
    assert put_a.status_code == 200, put_a.text

    # --- Tenant B: GET must NOT see A's marker ---
    token_b = _register(client, "isol-b@example.com", "password123", "IsolBrandB")
    get_b = client.get("/onboarding/interview", headers=_auth(token_b))
    assert get_b.status_code == 200, get_b.text
    assert MARKER_A not in get_b.text, (
        f"Tenant B's GET /onboarding/interview leaks Tenant A's draft marker: {get_b.text}"
    )

    # --- Tenant B completes its own interview ---
    b_answers = {**_ALL_ANSWERS, "tone": "صدای اختصاصی برند ب"}
    client.put(
        "/onboarding/interview/answers",
        json={"answers": b_answers},
        headers=_auth(token_b),
    )
    complete_b = client.post("/onboarding/interview/complete", headers=_auth(token_b))
    assert complete_b.status_code == 200, complete_b.text

    # --- Tenant A completes its own interview (marker in tone) ---
    a_answers = {**_ALL_ANSWERS, "tone": MARKER_A}
    client.put(
        "/onboarding/interview/answers",
        json={"answers": a_answers},
        headers=_auth(token_a),
    )
    complete_a = client.post("/onboarding/interview/complete", headers=_auth(token_a))
    assert complete_a.status_code == 200, complete_a.text

    # --- A's brand profile must reflect the marker, NOT B's tone ---
    profile_a = client.get("/brand-profile", headers=_auth(token_a))
    assert profile_a.status_code == 200, profile_a.text
    assert profile_a.json()["tone"] == MARKER_A, (
        f"Tenant A's brand profile tone was corrupted by B's completion: {profile_a.json()}"
    )
    assert "صدای اختصاصی برند ب" not in profile_a.text, (
        f"Tenant A's brand profile leaks Tenant B's tone data: {profile_a.text}"
    )
