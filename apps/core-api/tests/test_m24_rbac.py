"""
M24 acceptance tests (slice B) — RBAC (Owner/Editor/Observer) + invites.

Contract (design §1 0019):
  users.role ∈ owner|editor|observer; /auth/register keeps creating the
  tenant's OWNER (backfill semantics). Role is read from the DB per request
  (require_role layered on get_identity — fresh, revocable, no stale JWT).

  Invites (multi-seat, v1):
    POST /auth/invites          (owner only) {email, role: editor|observer}
      → 201 {token} — the RAW token is shown exactly once (sha256 stored)
    POST /auth/invites/accept   (public — the token IS the auth)
      {token, password} → 201 {access_token}; the user joins the INVITING
      tenant with the invited role.
    - already-registered email → 409 (accounts never move across tenants)
    - unknown / used / expired token → 410 (no probing oracle)
    - invited role "owner" → 422 (owner is never invited)

  Matrix (representative routes):
    observer: read-only — GETs 200; create/publish/secrets/export → 403
    editor:   content + studio + publish jobs; secrets/export/profile → 403
    owner:    everything, incl. brand profile, channel secrets, export,
              tenant silence, invites.

  rule 6: an invited member sees ONLY the inviting tenant's data.

All tests named test_m24_<criterion>.
"""

from __future__ import annotations

import os
import secrets as _secrets
from datetime import timedelta

from fastapi.testclient import TestClient

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("PUBLISH_MODE", "fake")
os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))

_BRIEF = {
    "goal": "افزایش آگاهی از برند",
    "audience": "مدیران",
    "channel": "بله",
    "format": "پست متنی",
    "hook": None,
    "cta": None,
}


def _register(client: TestClient, email: str, name: str) -> str:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "tenant_name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _invite(client: TestClient, owner_token: str, email: str, role: str) -> str:
    resp = client.post(
        "/auth/invites", json={"email": email, "role": role}, headers=_auth(owner_token)
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["token"]
    assert token, "raw invite token must be returned exactly once"
    return token

def _accept(client: TestClient, invite_token: str) -> str:
    resp = client.post(
        "/auth/invites/accept",
        json={"token": invite_token, "password": "Password123!"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _member(client: TestClient, owner_token: str, email: str, role: str) -> str:
    return _accept(client, _invite(client, owner_token, email, role))


# ===========================================================================
# 1. Invite lifecycle
# ===========================================================================


def test_m24_owner_invites_editor_who_joins_same_tenant(client: TestClient):
    owner = _register(client, "m24-own@example.com", "M24Own")
    draft = client.post("/content/drafts", json={"brief": _BRIEF}, headers=_auth(owner))
    assert draft.status_code == 201, draft.text

    editor = _member(client, owner, "m24-ed@example.com", "editor")
    drafts = client.get("/content/drafts", headers=_auth(editor)).json()["drafts"]
    assert len(drafts) == 1, "invited editor must see the INVITING tenant's drafts"


def test_m24_invite_requires_owner(client: TestClient):
    owner = _register(client, "m24-inv-own@example.com", "M24InvOwn")
    editor = _member(client, owner, "m24-inv-ed@example.com", "editor")
    resp = client.post(
        "/auth/invites",
        json={"email": "x@example.com", "role": "observer"},
        headers=_auth(editor),
    )
    assert resp.status_code == 403, f"only owners invite: {resp.status_code}"


def test_m24_owner_role_cannot_be_invited(client: TestClient):
    owner = _register(client, "m24-noown@example.com", "M24NoOwn")
    resp = client.post(
        "/auth/invites",
        json={"email": "y@example.com", "role": "owner"},
        headers=_auth(owner),
    )
    assert resp.status_code == 422, resp.text


def test_m24_registered_email_cannot_accept(client: TestClient):
    owner_a = _register(client, "m24-taken@example.com", "M24TakenA")
    owner_b = _register(client, "m24-other@example.com", "M24TakenB")
    invite = _invite(client, owner_b, "m24-taken@example.com", "editor")
    resp = client.post(
        "/auth/invites/accept", json={"token": invite, "password": "Password123!"}
    )
    assert resp.status_code == 409, (
        f"accounts never move across tenants (rule 6): {resp.status_code}"
    )
    # And the existing account still belongs to its own tenant only.
    drafts = client.get("/content/drafts", headers=_auth(owner_a)).json()["drafts"]
    assert drafts == []


def test_m24_invite_token_is_single_use(client: TestClient):
    owner = _register(client, "m24-once@example.com", "M24Once")
    invite = _invite(client, owner, "m24-once-ed@example.com", "editor")
    _accept(client, invite)
    resp = client.post(
        "/auth/invites/accept", json={"token": invite, "password": "Password123!"}
    )
    assert resp.status_code == 410, f"used token must be dead: {resp.status_code}"


def test_m24_unknown_and_expired_tokens_are_410(client: TestClient):
    resp = client.post(
        "/auth/invites/accept", json={"token": "no-such-token", "password": "Password123!"}
    )
    assert resp.status_code == 410, resp.status_code

    owner = _register(client, "m24-exp@example.com", "M24Exp")
    invite = _invite(client, owner, "m24-exp-ed@example.com", "editor")
    # Age the invite past its expiry (app-TZ clock, ADR 0032).
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from rpim_core_api import db as db_module  # noqa: PLC0415
    from rpim_core_api.models import TenantInvite  # noqa: PLC0415
    from rpim_shared.tz import now_app  # noqa: PLC0415

    with Session(db_module.engine) as session:
        row = session.scalars(select(TenantInvite)).all()[-1]
        row.expires_at = now_app() - timedelta(hours=1)
        session.commit()
    resp = client.post(
        "/auth/invites/accept", json={"token": invite, "password": "Password123!"}
    )
    assert resp.status_code == 410, f"expired token must be dead: {resp.status_code}"


def test_m24_raw_token_never_stored(client: TestClient):
    owner = _register(client, "m24-hash@example.com", "M24Hash")
    invite = _invite(client, owner, "m24-hash-ed@example.com", "observer")
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from rpim_core_api import db as db_module  # noqa: PLC0415
    from rpim_core_api.models import TenantInvite  # noqa: PLC0415

    with Session(db_module.engine) as session:
        rows = session.scalars(select(TenantInvite)).all()
        assert rows and all(invite not in (r.token_hash or "") for r in rows), (
            "only the sha256 of the invite token may be stored"
        )


# ===========================================================================
# 2. The role matrix on representative routes
# ===========================================================================


def test_m24_observer_is_read_only(client: TestClient):
    owner = _register(client, "m24-obs-own@example.com", "M24ObsOwn")
    observer = _member(client, owner, "m24-obs@example.com", "observer")

    assert client.get("/trends", headers=_auth(observer)).status_code == 200
    assert client.get("/content/drafts", headers=_auth(observer)).status_code == 200
    assert client.get("/publish/jobs", headers=_auth(observer)).status_code == 200

    assert (
        client.post(
            "/content/drafts", json={"brief": _BRIEF}, headers=_auth(observer)
        ).status_code
        == 403
    ), "observer must not create drafts"
    assert (
        client.put(
            "/channels/bale",
            json={"secret": "x", "config": {}},
            headers=_auth(observer),
        ).status_code
        == 403
    ), "observer must not touch channel secrets"
    assert client.get("/export", headers=_auth(observer)).status_code == 403


def test_m24_editor_creates_content_but_not_secrets_or_export(client: TestClient):
    owner = _register(client, "m24-edi-own@example.com", "M24EdiOwn")
    editor = _member(client, owner, "m24-edi@example.com", "editor")

    draft = client.post("/content/drafts", json={"brief": _BRIEF}, headers=_auth(editor))
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["draft_id"]
    assert (
        client.post(f"/content/drafts/{draft_id}/approve", headers=_auth(editor)).status_code
        == 200
    )
    assert client.get("/channels", headers=_auth(editor)).status_code == 200

    assert (
        client.put(
            "/channels/bale", json={"secret": "x", "config": {}}, headers=_auth(editor)
        ).status_code
        == 403
    )
    assert client.get("/export", headers=_auth(editor)).status_code == 403
    profile = {
        "tone": "گرم",
        "personas": [],
        "lexicon": {},
        "allowed_claims": [],
        "forbidden_claims": [],
        "red_lines": [],
    }
    assert (
        client.put("/brand-profile", json=profile, headers=_auth(editor)).status_code == 403
    ), "brand profile writes are owner-only"


def test_m24_owner_retains_full_control(client: TestClient, monkeypatch):
    from cryptography.fernet import Fernet  # noqa: PLC0415

    monkeypatch.setenv("CHANNEL_SECRET_KEY", Fernet.generate_key().decode())
    owner = _register(client, "m24-full@example.com", "M24Full")
    profile = {
        "tone": "گرم",
        "personas": [],
        "lexicon": {},
        "allowed_claims": [],
        "forbidden_claims": [],
        "red_lines": [],
    }
    assert client.put("/brand-profile", json=profile, headers=_auth(owner)).status_code == 200
    assert (
        client.put(
            "/channels/bale",
            json={"secret": "bot1:x", "config": {}},
            headers=_auth(owner),
        ).status_code
        == 200
    )
    assert client.get("/export", headers=_auth(owner)).status_code == 200
    assert (
        client.post(
            "/governance/silence",
            json={"active": True, "reason": "تست"},
            headers=_auth(owner),
        ).status_code
        == 200
    )


# ===========================================================================
# 3. rule 6 across the invite path
# ===========================================================================


def test_m24_invited_member_sees_only_inviting_tenant(client: TestClient):
    owner_a = _register(client, "m24-iso-a@example.com", "M24IsoA")
    owner_b = _register(client, "m24-iso-b@example.com", "M24IsoB")
    assert (
        client.post(
            "/content/drafts", json={"brief": _BRIEF}, headers=_auth(owner_b)
        ).status_code
        == 201
    )
    editor_a = _member(client, owner_a, "m24-iso-ed@example.com", "editor")
    drafts = client.get("/content/drafts", headers=_auth(editor_a)).json()["drafts"]
    assert drafts == [], "member of A must never see B's data (rule 6)"
