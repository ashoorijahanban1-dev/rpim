"""
M1 acceptance-criteria tests — Identity & Tenancy.

All tests are named test_m1_<criterion> and must FAIL until the implementation
provides:
  - rpim_core_api.db  (get_session, init_db, engine)
  - POST /auth/register
  - POST /auth/login
  - GET  /brand-profile
  - PUT  /brand-profile

These tests are black-box: they only exercise the HTTP API; they do NOT import
ORM models or inspect the database directly.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BRAND_PAYLOAD = {
    "tone": "professional",
    "personas": ["busy-manager", "tech-lead"],
    "lexicon": {"راهکار": "solution"},
    "forbidden_claims": ["ضمانت سود"],
    "red_lines": ["رقبا را مسخره نکن"],
}


def _register(client: TestClient, email: str, password: str, tenant_name: str) -> dict:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "tenant_name": tenant_name},
    )
    return resp


def _login(client: TestClient, email: str, password: str):
    return client.post("/auth/login", json={"email": email, "password": password})


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. Registration
# ---------------------------------------------------------------------------


def test_m1_register_returns_201_with_tenant_id_and_access_token(client: TestClient):
    """POST /auth/register with valid body → 201 containing tenant_id and access_token."""
    resp = _register(client, "alice@example.com", "s3cr3t!-longer", "BrandAlpha")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "tenant_id" in body, f"tenant_id missing from response: {body}"
    assert "access_token" in body, f"access_token missing from response: {body}"


def test_m1_register_duplicate_email_returns_409(client: TestClient):
    """Registering the same email twice → 409 Conflict."""
    _register(client, "bob@example.com", "pass1-longer", "BrandBeta")
    resp = _register(client, "bob@example.com", "pass2-longer", "BrandBeta2")
    assert resp.status_code == 409, resp.text


# ---------------------------------------------------------------------------
# 2. Login
# ---------------------------------------------------------------------------


def test_m1_login_returns_200_with_access_token(client: TestClient):
    """POST /auth/login with correct credentials → 200 with access_token."""
    _register(client, "carol@example.com", "hunter2-longer", "BrandCarol")
    resp = _login(client, "carol@example.com", "hunter2-longer")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "access_token" in body, f"access_token missing: {body}"


def test_m1_login_wrong_password_returns_401(client: TestClient):
    """POST /auth/login with wrong password → 401."""
    _register(client, "dave@example.com", "correct-horse", "BrandDave")
    resp = _login(client, "dave@example.com", "wrong-password")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# 3. Brand-profile — authenticated CRUD
# ---------------------------------------------------------------------------


def test_m1_brand_profile_put_returns_200(client: TestClient):
    """PUT /brand-profile with a valid Bearer token → 200."""
    reg = _register(client, "eve@example.com", "evePW1-longer", "BrandEve")
    token = reg.json()["access_token"]
    resp = client.put("/brand-profile", json=_BRAND_PAYLOAD, headers=_auth_headers(token))
    assert resp.status_code == 200, resp.text


def test_m1_brand_profile_get_returns_what_was_put(client: TestClient):
    """GET /brand-profile returns the exact payload that was PUT."""
    reg = _register(client, "frank@example.com", "frankPW1", "BrandFrank")
    token = reg.json()["access_token"]
    headers = _auth_headers(token)

    client.put("/brand-profile", json=_BRAND_PAYLOAD, headers=headers)
    resp = client.get("/brand-profile", headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tone"] == _BRAND_PAYLOAD["tone"]
    assert body["personas"] == _BRAND_PAYLOAD["personas"]
    assert body["lexicon"] == _BRAND_PAYLOAD["lexicon"]
    assert body["forbidden_claims"] == _BRAND_PAYLOAD["forbidden_claims"]
    assert body["red_lines"] == _BRAND_PAYLOAD["red_lines"]


def test_m1_brand_profile_unauthenticated_get_returns_401(client: TestClient):
    """GET /brand-profile without Authorization header → 401."""
    resp = client.get("/brand-profile")
    assert resp.status_code == 401, resp.text


def test_m1_brand_profile_unauthenticated_put_returns_401(client: TestClient):
    """PUT /brand-profile without Authorization header → 401."""
    resp = client.put("/brand-profile", json=_BRAND_PAYLOAD)
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# 4. Cross-tenant isolation  (CLAUDE.md rule 6 + blueprint §tenancy)
# ---------------------------------------------------------------------------


def test_m1_cross_tenant_isolation(client: TestClient):
    """
    THE isolation acceptance test.

    Tenant A and Tenant B each PUT their own brand profile.  B's GET must NOT
    expose A's data.  Every DB query is scoped by tenant_id — proved black-box
    through the API only (no ORM imports).

    Steps
    -----
    1. Register A, PUT profile with distinctive tone "voice-of-A".
    2. Register B, PUT profile with tone "voice-of-B".
    3. GET /brand-profile as B → must contain "voice-of-B", must NOT contain
       "voice-of-A".
    4. GET /brand-profile as A → must still contain "voice-of-A", must NOT
       contain "voice-of-B" (symmetry check).
    5. Any route that would allow B to read A's resource by ID must either not
       exist (404) or return 403/404 — no 200 leaking A's data.
    """
    # --- Tenant A ---
    reg_a = _register(client, "tenant-a@example.com", "pwdA!1-longer", "TenantOrgA")
    assert reg_a.status_code == 201, reg_a.text
    body_a = reg_a.json()
    token_a = body_a["access_token"]
    tenant_id_a = body_a["tenant_id"]

    profile_a = {
        "tone": "voice-of-A",
        "personas": ["persona-A"],
        "lexicon": {"key": "value-A"},
        "forbidden_claims": ["claim-A"],
        "red_lines": ["line-A"],
    }
    put_a = client.put("/brand-profile", json=profile_a, headers=_auth_headers(token_a))
    assert put_a.status_code == 200, put_a.text

    # --- Tenant B ---
    reg_b = _register(client, "tenant-b@example.com", "pwdB!2-longer", "TenantOrgB")
    assert reg_b.status_code == 201, reg_b.text
    body_b = reg_b.json()
    token_b = body_b["access_token"]
    tenant_id_b = body_b["tenant_id"]

    # Sanity: A and B must be different tenants.
    assert tenant_id_a != tenant_id_b, "Two separate registrations must yield distinct tenant_ids"

    profile_b = {
        "tone": "voice-of-B",
        "personas": ["persona-B"],
        "lexicon": {"key": "value-B"},
        "forbidden_claims": ["claim-B"],
        "red_lines": ["line-B"],
    }
    put_b = client.put("/brand-profile", json=profile_b, headers=_auth_headers(token_b))
    assert put_b.status_code == 200, put_b.text

    # --- Isolation: B reads its own profile ---
    get_b = client.get("/brand-profile", headers=_auth_headers(token_b))
    assert get_b.status_code == 200, get_b.text
    data_b = get_b.json()

    # B must see its own tone.
    assert data_b["tone"] == "voice-of-B", f"B should see its own tone, got: {data_b}"

    # B must NOT see A's tone anywhere in its response.
    response_text_b = get_b.text
    assert "voice-of-A" not in response_text_b, (
        f"Tenant B's GET /brand-profile leaks Tenant A's data: {response_text_b}"
    )

    # --- Symmetry: A still reads its own profile uncontaminated ---
    get_a = client.get("/brand-profile", headers=_auth_headers(token_a))
    assert get_a.status_code == 200, get_a.text
    data_a = get_a.json()

    assert data_a["tone"] == "voice-of-A", f"A should see its own tone, got: {data_a}"
    response_text_a = get_a.text
    assert "voice-of-B" not in response_text_a, (
        f"Tenant A's GET /brand-profile leaks Tenant B's data: {response_text_a}"
    )

    # --- B cannot reach A's resource by tenant_id path (if such a route exists) ---
    # If the implementation ever exposes /brand-profile/{tenant_id}, B must get
    # 403 or 404 when trying to fetch A's record — never a 200 with A's data.
    attempt = client.get(
        f"/brand-profile/{tenant_id_a}", headers=_auth_headers(token_b)
    )
    # 200 leaking A's data is the only forbidden outcome.
    if attempt.status_code == 200:
        assert "voice-of-A" not in attempt.text, (
            f"Route /brand-profile/{{tenant_id}} leaks cross-tenant data to B: {attempt.text}"
        )
