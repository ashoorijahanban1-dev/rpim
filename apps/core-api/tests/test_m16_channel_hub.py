"""
M16 acceptance tests — Per-Brand Social Media Hub (هاب کانال‌ها).

Contract:
  vault.py
    - seal()/unseal() roundtrip via Fernet, key from env CHANNEL_SECRET_KEY
    - missing key → VaultKeyError NAMING the env var (rule 4)

  PUT /channels/{channel}   (tenant Bearer auth; channel ∈ telegram|bale|eitaa|wordpress)
    - upserts THIS tenant's connection: non-secret config JSON + write-only
      secret (encrypted at rest); replay updates, never duplicates
    - unknown channel → 404/422; response NEVER carries the secret
  GET /channels
    - all four channels with {channel, status, secret_set, config}; secrets
      never appear anywhere in the payload (rule 4 extended to tenant creds)
    - rule 6: only the calling tenant's connections
  DELETE /channels/{channel}
    - disconnects: secret wiped, status back to disconnected

Dashboard static contract: /channels page, sidebar link, fa.channels locale.
All tests named test_m16_<criterion>.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rpim_core_api import vault

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PAGE_TSX = _REPO_ROOT / "apps" / "dashboard" / "app" / "channels" / "page.tsx"
_SIDEBAR = _REPO_ROOT / "apps" / "dashboard" / "components" / "Sidebar.tsx"
_FA_JSON = _REPO_ROOT / "apps" / "dashboard" / "locales" / "fa.json"

_SECRET_TOKEN = "bot123456:TEST-not-a-real-token"  # noqa: S105 — test fixture


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    from cryptography.fernet import Fernet  # noqa: PLC0415

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
# 1. Vault primitives
# ===========================================================================


def test_m16_vault_roundtrip():
    # M24 evolved the signature: seals are bound to their row (AAD).
    sealed = vault.seal(_SECRET_TOKEN, tenant_id="ten-t", channel="bale")
    assert sealed != _SECRET_TOKEN and _SECRET_TOKEN not in sealed, (
        "sealed value must not contain the plaintext"
    )
    assert vault.unseal(sealed, tenant_id="ten-t", channel="bale") == _SECRET_TOKEN


def test_m16_vault_missing_key_names_the_var(monkeypatch):
    monkeypatch.delenv("CHANNEL_SECRET_KEY", raising=False)
    monkeypatch.delenv("CHANNEL_SECRET_KEY_V2", raising=False)
    with pytest.raises(vault.VaultKeyError) as excinfo:
        vault.seal("x", tenant_id="ten-t", channel="bale")
    assert "CHANNEL_SECRET_KEY" in str(excinfo.value), (
        f"error must NAME the env var (rule 4): {excinfo.value}"
    )


# ===========================================================================
# 2. Connect / view / manage — auth, upsert, no-secret-leak
# ===========================================================================


def test_m16_endpoints_require_auth(client: TestClient):
    assert client.get("/channels").status_code == 401
    assert (
        client.put("/channels/telegram", json={"secret": "x", "config": {}}).status_code
        == 401
    )
    assert client.delete("/channels/telegram").status_code == 401


def test_m16_unknown_channel_rejected(client: TestClient):
    token = _register(client, "hub-bad@example.com", "HubBad")
    resp = client.put(
        "/channels/instagram", json={"secret": "x", "config": {}}, headers=_auth(token)
    )
    assert resp.status_code in (404, 422), (
        f"instagram is assisted-only (rule 5) — no connection slot: {resp.status_code}"
    )


def test_m16_connect_view_never_leaks_secret(client: TestClient):
    token = _register(client, "hub-a@example.com", "HubA")
    resp = client.put(
        "/channels/telegram",
        json={"secret": _SECRET_TOKEN, "config": {"chat_id": "@beewaz"}},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert _SECRET_TOKEN not in resp.text, "secret must never echo back"

    resp = client.get("/channels", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert _SECRET_TOKEN not in resp.text, "secret must never appear in listings"
    items = {c["channel"]: c for c in resp.json()["channels"]}
    assert set(items) == {"telegram", "bale", "eitaa", "wordpress"}, (
        f"all four allowed channels must be listed: {set(items)}"
    )
    tg = items["telegram"]
    assert tg["status"] == "connected" and tg["secret_set"] is True, tg
    assert tg["config"] == {"chat_id": "@beewaz"}, tg
    assert items["bale"]["status"] == "disconnected"
    assert items["bale"]["secret_set"] is False


def test_m16_reconnect_updates_not_duplicates(client: TestClient):
    token = _register(client, "hub-upd@example.com", "HubUpd")
    for chat in ("@one", "@two"):
        resp = client.put(
            "/channels/bale",
            json={"secret": _SECRET_TOKEN, "config": {"chat_id": chat}},
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
    channels = client.get("/channels", headers=_auth(token)).json()["channels"]
    bale = [c for c in channels if c["channel"] == "bale"]
    assert len(bale) == 1, f"reconnect must UPSERT: {bale}"
    assert bale[0]["config"] == {"chat_id": "@two"}


def test_m16_config_only_update_keeps_secret(client: TestClient):
    token = _register(client, "hub-keep@example.com", "HubKeep")
    assert (
        client.put(
            "/channels/wordpress",
            json={"secret": "app pass", "config": {"base_url": "https://a.ir"}},
            headers=_auth(token),
        ).status_code
        == 200
    )
    resp = client.put(
        "/channels/wordpress",
        json={"config": {"base_url": "https://b.ir"}},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    wp = [
        c
        for c in client.get("/channels", headers=_auth(token)).json()["channels"]
        if c["channel"] == "wordpress"
    ][0]
    assert wp["secret_set"] is True, "omitting secret must keep the stored one"
    assert wp["config"] == {"base_url": "https://b.ir"}


def test_m16_disconnect_wipes_secret(client: TestClient):
    token = _register(client, "hub-del@example.com", "HubDel")
    assert (
        client.put(
            "/channels/eitaa",
            json={"secret": _SECRET_TOKEN, "config": {}},
            headers=_auth(token),
        ).status_code
        == 200
    )
    assert client.delete("/channels/eitaa", headers=_auth(token)).status_code == 200
    eitaa = [
        c
        for c in client.get("/channels", headers=_auth(token)).json()["channels"]
        if c["channel"] == "eitaa"
    ][0]
    assert eitaa["status"] == "disconnected" and eitaa["secret_set"] is False, eitaa


# ===========================================================================
# 3. Tenant isolation (rule 6)
# ===========================================================================


def test_m16_cross_tenant_isolation(client: TestClient):
    token_a = _register(client, "hub-iso-a@example.com", "HubIsoA")
    token_b = _register(client, "hub-iso-b@example.com", "HubIsoB")
    assert (
        client.put(
            "/channels/telegram",
            json={"secret": _SECRET_TOKEN, "config": {"chat_id": "@private-a"}},
            headers=_auth(token_a),
        ).status_code
        == 200
    )
    b_view = client.get("/channels", headers=_auth(token_b))
    assert "@private-a" in client.get("/channels", headers=_auth(token_a)).text
    assert "@private-a" not in b_view.text, "tenant B must not see A's config (rule 6)"
    b_tg = [c for c in b_view.json()["channels"] if c["channel"] == "telegram"][0]
    assert b_tg["status"] == "disconnected" and b_tg["secret_set"] is False


# ===========================================================================
# 4. Dashboard static contract
# ===========================================================================


def test_m16_dashboard_page_and_locale():
    assert _PAGE_TSX.exists(), "apps/dashboard/app/channels/page.tsx must exist"
    src = _PAGE_TSX.read_text("utf-8")
    assert "/channels" in src
    assert 'type="password"' in src, "secret inputs must be password-masked"
    assert not re.compile(r"[؀-ۿ]").search(src), "locale-only rule"
    assert 'href: "/channels"' in _SIDEBAR.read_text("utf-8")
    fa = json.loads(_FA_JSON.read_text("utf-8"))
    section = fa.get("channels_hub", {})
    for key in ("title", "hint", "connected", "disconnected", "secret_label",
                "secret_keep_hint", "save", "disconnect", "saved", "error"):
        assert section.get(key), f"fa.channels_hub.{key} missing/empty"
    assert fa["nav"].get("channels"), "fa.nav.channels missing"
