"""
M18 acceptance tests — Super Admin panel (پنل سوپرادمین).

Contract:
  Admin gate
    - Admins are named by env ADMIN_EMAILS (comma-separated, case-insensitive,
      whitespace-tolerant) — env NAMES only, checked against the VERIFIED
      user row at request time (revoking = removing from the list).
    - Unset/empty ADMIN_EMAILS → NOBODY is admin (safe default).
    - Non-admin authenticated users → 403; anonymous → 401.

  GET /admin/tenants  (admin only — the ONE authorized cross-tenant read;
                       rule 6 exception is gated, deliberate, ADR-documented)
    - Every tenant with {tenant_id, name, created_at, users, channels, costs}
    - channels: all four allowed channels as {channel, status, secret_set} —
      NO secret material, NO config values (isolation oversight = status only)
    - costs from the per-tenant ledger: {total_usd, tokens}

  Dashboard static contract: /admin page exists (direct URL, deliberately not
  in the tenant sidebar), locale-only Persian via fa.admin.*.

All tests named test_m18_<criterion>.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PAGE_TSX = _REPO_ROOT / "apps" / "dashboard" / "app" / "admin" / "page.tsx"
_SIDEBAR = _REPO_ROOT / "apps" / "dashboard" / "components" / "Sidebar.tsx"
_FA_JSON = _REPO_ROOT / "apps" / "dashboard" / "locales" / "fa.json"

_SECRET_TOKEN = "bot999:ADMIN-test-not-real"  # noqa: S105 — inoperable fixture


@pytest.fixture(autouse=True)
def _no_admins_by_default(monkeypatch):
    from cryptography.fernet import Fernet  # noqa: PLC0415

    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    monkeypatch.setenv("CHANNEL_SECRET_KEY", Fernet.generate_key().decode())
    yield


def _register(client: TestClient, email: str, name: str) -> str:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "tenant_name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# 1. The admin gate
# ===========================================================================


def test_m18_anonymous_gets_401(client: TestClient):
    assert client.get("/admin/tenants").status_code == 401


def test_m18_non_admin_gets_403(client: TestClient, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    token = _register(client, "mortal@example.com", "Mortal")
    assert client.get("/admin/tenants", headers=_auth(token)).status_code == 403


def test_m18_empty_allowlist_means_nobody(client: TestClient):
    token = _register(client, "anyone@example.com", "Anyone")
    assert client.get("/admin/tenants", headers=_auth(token)).status_code == 403, (
        "unset ADMIN_EMAILS must mean NO admins (safe default)"
    )


def test_m18_allowlist_is_case_and_space_tolerant(client: TestClient, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", " Other@x.com , BOSS@Example.COM ")
    token = _register(client, "boss@example.com", "BossCo")
    assert client.get("/admin/tenants", headers=_auth(token)).status_code == 200


# ===========================================================================
# 2. Cross-tenant oversight — shape, costs, channel statuses
# ===========================================================================


def test_m18_admin_sees_all_tenants_with_usage(client: TestClient, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    admin_token = _register(client, "boss@example.com", "BossCo")
    _register(client, "brand-a@example.com", "BrandA")
    _register(client, "brand-b@example.com", "BrandB")

    resp = client.get("/admin/tenants", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    tenants = resp.json()["tenants"]
    names = {t["name"] for t in tenants}
    assert {"BossCo", "BrandA", "BrandB"} <= names, (
        f"admin must see EVERY tenant: {names}"
    )
    for item in tenants:
        assert set(item) >= {"tenant_id", "name", "created_at", "users", "channels", "costs"}
        assert item["users"] >= 1
        assert {c["channel"] for c in item["channels"]} == {
            "telegram", "bale", "eitaa", "wordpress"
        }, f"all four allowed channels listed per tenant: {item['channels']}"
        # LEDGER_MODE=fake → the deterministic entry (125 tokens, $0.0125)
        assert item["costs"] == {"total_usd": 0.0125, "tokens": 125}, item["costs"]


def test_m18_channel_status_visible_but_never_secret_or_config(
    client: TestClient, monkeypatch
):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    admin_token = _register(client, "boss@example.com", "BossCo")
    brand_token = _register(client, "brand-c@example.com", "BrandC")
    resp = client.put(
        "/channels/bale",
        json={"secret": _SECRET_TOKEN, "config": {"chat_id": "@private-brand-c"}},
        headers=_auth(brand_token),
    )
    assert resp.status_code == 200, resp.text

    resp = client.get("/admin/tenants", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert _SECRET_TOKEN not in resp.text, "secrets must NEVER reach the admin view"
    assert "@private-brand-c" not in resp.text, (
        "tenant channel CONFIG stays private too — oversight is status-only"
    )
    brand_c = [t for t in resp.json()["tenants"] if t["name"] == "BrandC"][0]
    bale = [c for c in brand_c["channels"] if c["channel"] == "bale"][0]
    assert bale["status"] == "connected" and bale["secret_set"] is True, bale
    assert "config" not in bale, f"config must not be exposed: {bale}"


# ===========================================================================
# 3. Dashboard static contract (direct-URL page, locale-only)
# ===========================================================================


def test_m18_dashboard_page_and_locale():
    assert _PAGE_TSX.exists(), "apps/dashboard/app/admin/page.tsx must exist"
    src = _PAGE_TSX.read_text("utf-8")
    assert "/admin/tenants" in src
    assert not re.compile(r"[؀-ۿ]").search(src), "locale-only rule"
    assert 'href: "/admin"' not in _SIDEBAR.read_text("utf-8"), (
        "admin page is direct-URL only — the tenant sidebar stays clean"
    )
    fa = json.loads(_FA_JSON.read_text("utf-8"))
    section = fa.get("admin", {})
    for key in ("title", "hint", "denied", "tenants", "users", "cost", "tokens",
                "channels", "connected", "disconnected", "empty", "error"):
        assert section.get(key), f"fa.admin.{key} missing/empty"
