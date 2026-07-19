"""
M24 acceptance tests (slice A) — Vault v2: AES-GCM-256 with row binding.

Contract (design §1 0019 + §3.4, ADR 0033 amended):
  - seal(plaintext, tenant_id=..., channel=...) → "v2:" + b64(nonce‖ct),
    AES-GCM-256 keyed by env CHANNEL_SECRET_KEY_V2, AAD = "tenant:channel"
    — a sealed blob is BOUND to its row; copied elsewhere it will not open.
  - unseal dispatches on the prefix: v2 → AESGCM; anything else → v1
    Fernet (CHANNEL_SECRET_KEY) — the transition reads both.
  - Rollout-safe seal: missing V2 key falls back to v1 sealing (never
    breaks the connect flow mid-rollout); neither key → VaultKeyError
    NAMING the env var (rule 4).
  - EVERY v2 failure (wrong AAD, corrupt blob, bad key) surfaces as
    VaultKeyError — never a raw InvalidTag that would abort a whole
    dispatch batch.
  - Lazy re-seal is BEST-EFFORT inside tenant_creds.resolve: v1 blob +
    V2 key present → upgraded to v2 on the next publish; V2 key absent →
    publish still succeeds and the blob stays v1. Never blocks the
    pipeline; never falls back to the global identity (m16b invariant).

All tests named test_m24_<criterion>.
"""

from __future__ import annotations

import base64
import os
import re
import secrets as _secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rpim_core_api import vault
from rpim_core_api.publisher import channels

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("PUBLISH_MODE", "fake")
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PLAIN = "bot777:M24-test-not-real"  # noqa: S105 — inoperable fixture


def _v2_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    from cryptography.fernet import Fernet  # noqa: PLC0415

    monkeypatch.setenv("CHANNEL_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("CHANNEL_SECRET_KEY_V2", _v2_key())
    monkeypatch.setenv("PUBLISH_MODE", "fake")
    channels._OUTBOX.clear()
    channels._FAIL_NEXT.clear()
    yield
    channels._OUTBOX.clear()
    channels._FAIL_NEXT.clear()


def _session():
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from rpim_core_api import db as db_module  # noqa: PLC0415

    return Session(db_module.engine)


def _register(client: TestClient, email: str, name: str) -> str:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "tenant_name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _internal() -> dict:
    return {"X-Internal-Token": _INTERNAL_TOKEN}


def _queued_bale_job(client: TestClient, token: str) -> str:
    brief = {
        "goal": "افزایش آگاهی",
        "audience": "خانواده‌ها",
        "channel": "بله",
        "format": "پست متنی",
        "hook": None,
        "cta": None,
    }
    resp = client.post("/content/drafts", json={"brief": brief}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    draft_id = resp.json()["draft_id"]
    assert (
        client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(token)).status_code
        == 200
    )
    resp = client.post(
        "/publish/jobs",
        json={
            "draft_id": draft_id,
            "channel": "bale",
            "chat_id": "@x",
            "campaign_code": "camp_m24",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["job_id"]


def _stored_blob(tenant_token: str, client: TestClient, channel: str = "bale") -> str:
    import jwt  # noqa: PLC0415

    from rpim_core_api.models import ChannelConnection  # noqa: PLC0415

    tenant_id = jwt.decode(tenant_token, options={"verify_signature": False})["tenant_id"]
    with _session() as session:
        from sqlalchemy import select  # noqa: PLC0415

        row = session.scalar(
            select(ChannelConnection).where(
                ChannelConnection.tenant_id == tenant_id,
                ChannelConnection.channel == channel,
            )
        )
        assert row is not None
        return row.secret_sealed or ""


# ===========================================================================
# 1. Primitives — format, AAD binding, transition reads, rollout fallback
# ===========================================================================


def test_m24_v2_roundtrip_with_prefix():
    sealed = vault.seal(_PLAIN, tenant_id="ten-a", channel="bale")
    assert sealed.startswith("v2:"), sealed
    assert _PLAIN not in sealed
    assert vault.unseal(sealed, tenant_id="ten-a", channel="bale") == _PLAIN


def test_m24_aad_binds_blob_to_its_row():
    sealed = vault.seal(_PLAIN, tenant_id="ten-a", channel="bale")
    with pytest.raises(vault.VaultKeyError):
        vault.unseal(sealed, tenant_id="ten-B", channel="bale")
    with pytest.raises(vault.VaultKeyError):
        vault.unseal(sealed, tenant_id="ten-a", channel="eitaa")


def test_m24_v1_blobs_still_open():
    from cryptography.fernet import Fernet  # noqa: PLC0415

    v1 = Fernet(os.environ["CHANNEL_SECRET_KEY"].encode()).encrypt(_PLAIN.encode()).decode()
    assert vault.unseal(v1, tenant_id="ten-a", channel="bale") == _PLAIN


def test_m24_seal_falls_back_to_v1_without_v2_key(monkeypatch):
    monkeypatch.delenv("CHANNEL_SECRET_KEY_V2", raising=False)
    sealed = vault.seal(_PLAIN, tenant_id="ten-a", channel="bale")
    assert not sealed.startswith("v2:"), "rollout gap must fall back to v1 sealing"
    assert vault.unseal(sealed, tenant_id="ten-a", channel="bale") == _PLAIN


def test_m24_no_keys_names_the_env_var(monkeypatch):
    monkeypatch.delenv("CHANNEL_SECRET_KEY_V2", raising=False)
    monkeypatch.delenv("CHANNEL_SECRET_KEY", raising=False)
    with pytest.raises(vault.VaultKeyError) as excinfo:
        vault.seal(_PLAIN, tenant_id="t", channel="bale")
    assert "CHANNEL_SECRET_KEY" in str(excinfo.value), "error must NAME the env var"


def test_m24_corrupt_or_foreign_v2_material_is_vault_error():
    with pytest.raises(vault.VaultKeyError):
        vault.unseal("v2:not-base64!!!", tenant_id="t", channel="bale")
    sealed = vault.seal(_PLAIN, tenant_id="t", channel="bale")
    mangled = sealed[:-6] + "AAAAAA"
    with pytest.raises(vault.VaultKeyError):
        vault.unseal(mangled, tenant_id="t", channel="bale")


def test_m24_invalid_v2_key_is_vault_error(monkeypatch):
    monkeypatch.setenv("CHANNEL_SECRET_KEY_V2", "too-short")
    with pytest.raises(vault.VaultKeyError):
        vault.seal(_PLAIN, tenant_id="t", channel="bale")


# ===========================================================================
# 2. Hub + publisher integration — write v2, read both, upgrade lazily
# ===========================================================================


def test_m24_hub_put_seals_v2_when_key_present(client: TestClient):
    token = _register(client, "m24-hub@example.com", "M24Hub")
    resp = client.put(
        "/channels/bale",
        json={"secret": _PLAIN, "config": {"chat_id": "@x"}},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    assert _stored_blob(token, client).startswith("v2:")


def test_m24_missing_v2_key_never_blocks_publishing(client: TestClient, monkeypatch):
    """v1-sealed connection + V2 key absent → publish succeeds with the
    TENANT credential and the blob stays v1 (best-effort, never an outage)."""
    monkeypatch.delenv("CHANNEL_SECRET_KEY_V2", raising=False)
    token = _register(client, "m24-nov2@example.com", "M24NoV2")
    assert (
        client.put(
            "/channels/bale",
            json={"secret": _PLAIN, "config": {}},
            headers=_auth(token),
        ).status_code
        == 200
    )
    blob_before = _stored_blob(token, client)
    assert not blob_before.startswith("v2:")
    _queued_bale_job(client, token)

    resp = client.post("/publish/dispatch", headers=_internal())
    assert resp.status_code == 200 and resp.json()["sent"] == 1, resp.text
    assert channels._OUTBOX[0]["creds_source"] == "tenant"
    assert not _stored_blob(token, client).startswith("v2:"), (
        "no V2 key → blob must stay v1, untouched"
    )


def test_m24_lazy_reseal_upgrades_v1_blob_on_publish(client: TestClient, monkeypatch):
    from cryptography.fernet import Fernet  # noqa: PLC0415

    # Connect while V2 key is absent → v1 blob on disk.
    monkeypatch.delenv("CHANNEL_SECRET_KEY_V2", raising=False)
    token = _register(client, "m24-lazy@example.com", "M24Lazy")
    assert (
        client.put(
            "/channels/bale",
            json={"secret": _PLAIN, "config": {}},
            headers=_auth(token),
        ).status_code
        == 200
    )
    assert not _stored_blob(token, client).startswith("v2:")

    # Operator rolls out the V2 key; next publish upgrades the blob in place.
    monkeypatch.setenv("CHANNEL_SECRET_KEY_V2", _v2_key())
    _queued_bale_job(client, token)
    resp = client.post("/publish/dispatch", headers=_internal())
    assert resp.status_code == 200 and resp.json()["sent"] == 1, resp.text
    upgraded = _stored_blob(token, client)
    assert upgraded.startswith("v2:"), f"lazy re-seal must upgrade the blob: {upgraded[:12]}"
    # And the upgraded blob opens with the row AAD.
    import jwt  # noqa: PLC0415

    tenant_id = jwt.decode(token, options={"verify_signature": False})["tenant_id"]
    assert vault.unseal(upgraded, tenant_id=tenant_id, channel="bale") == _PLAIN
    # Fernet key alone can no longer read it — it is truly v2 material.
    with pytest.raises(Exception):  # noqa: B017 — any failure is fine here
        Fernet(os.environ["CHANNEL_SECRET_KEY"].encode()).decrypt(upgraded.encode())


def test_m24_corrupt_blob_isolated_per_job(client: TestClient):
    """Tenant A's corrupt blob must keep A queued while tenant B publishes in
    the SAME dispatch pass — VaultKeyError wrapping keeps the engine's
    per-job isolation intact."""
    token_a = _register(client, "m24-corrupt-a@example.com", "M24CorA")
    token_b = _register(client, "m24-corrupt-b@example.com", "M24CorB")
    for tok in (token_a, token_b):
        assert (
            client.put(
                "/channels/bale",
                json={"secret": _PLAIN, "config": {}},
                headers=_auth(tok),
            ).status_code
            == 200
        )
    # Corrupt A's stored blob directly.
    import jwt  # noqa: PLC0415

    from rpim_core_api.models import ChannelConnection  # noqa: PLC0415

    tenant_a = jwt.decode(token_a, options={"verify_signature": False})["tenant_id"]
    with _session() as session:
        from sqlalchemy import select  # noqa: PLC0415

        row = session.scalar(
            select(ChannelConnection).where(
                ChannelConnection.tenant_id == tenant_a,
                ChannelConnection.channel == "bale",
            )
        )
        row.secret_sealed = "v2:@@@corrupted@@@"
        session.commit()

    _queued_bale_job(client, token_a)
    _queued_bale_job(client, token_b)
    resp = client.post("/publish/dispatch", headers=_internal())
    assert resp.status_code == 200, resp.text
    assert resp.json()["sent"] == 1 and resp.json()["failed"] == 1, resp.json()
    assert len(channels._OUTBOX) == 1
    jobs_a = client.get("/publish/jobs", headers=_auth(token_a)).json()["jobs"]
    assert jobs_a[0]["status"] == "queued", "corrupt blob → A stays queued, no fallback"


# ===========================================================================
# 3. Env template carries the NAME (rule 4)
# ===========================================================================


def test_m24_env_example_names_v2_key():
    text = (_REPO_ROOT / ".env.iran.example").read_text("utf-8")
    assert re.search(r"^CHANNEL_SECRET_KEY_V2=$", text, re.MULTILINE), (
        ".env.iran.example must name CHANNEL_SECRET_KEY_V2 with an EMPTY value"
    )
