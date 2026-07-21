"""
M21 acceptance tests (media slice) — the media-asset lifecycle.

Contract (design §1 0016 + §3.2):
  POST /studio/media {prompt_id}   (editor+)
    - Executes the visual prompt (IMAGE_MODE=fake → deterministic local
      bytes; remote → gateway /image with request_id = the asset id), stores
      bytes under MEDIA_STORAGE_DIR (never in the DB), computes sha256, and
      builds a DETERMINISTIC Persian SEO alt_text carrying the subject.
    - Dedupe: same tenant + same sha256 → the existing asset returns, no
      duplicate row (rule 8).
  GET /studio/media — tenant-scoped, newest first.
  POST /studio/media/{id}/approve  (editor+) — draft → approved. Rule 1
    covers IMAGES too: only an approved asset may attach to a publish job.
  Publish compile (create_job) with image {kind:"generated", media_asset_id}:
    - foreign/missing asset → 404 (rule 6, tested cross-tenant)
    - unapproved asset → 409
    - approved → 201 and the asset transitions to 'attached'
    - template jobs keep the old shape untouched.
  Dispatch: generated jobs load bytes from storage (tenant-scoped, status
    re-verified — defense in depth) and go out as photo sends.
  Migration 0016 revises 0019: media_assets + publish_jobs.first_failed_at.
  Export v3 carries media metadata (never bytes).

All tests named test_m21_<criterion>.
"""

from __future__ import annotations

import json
import os
import re
import secrets as _secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rpim_core_api.publisher import channels

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")
os.environ.setdefault("PUBLISH_MODE", "fake")
os.environ.setdefault("IMAGE_MODE", "fake")
_INTERNAL_TOKEN: str = os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(32))

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FA_JSON = _REPO_ROOT / "apps" / "dashboard" / "locales" / "fa.json"


@pytest.fixture(autouse=True)
def _media_env(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGE_MODE", "fake")
    monkeypatch.setenv("MEDIA_STORAGE_DIR", str(tmp_path / "media"))
    monkeypatch.setenv("PUBLISH_MODE", "fake")
    channels._OUTBOX.clear()
    channels._FAIL_NEXT.clear()
    yield
    channels._OUTBOX.clear()
    channels._FAIL_NEXT.clear()


def _register(client: TestClient, email: str, name: str) -> str:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "tenant_name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _visual_prompt(client: TestClient, token: str, subject: str = "پکیج دزدگیر BH10") -> str:
    resp = client.post(
        "/studio/prompts",
        json={"kind": "image", "brief": {"subject": subject, "channel": "telegram"}},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["prompt_id"]


def _generate(client: TestClient, token: str, prompt_id: str) -> dict:
    resp = client.post(
        "/studio/media", json={"prompt_id": prompt_id}, headers=_auth(token)
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _approved_draft_job_payload(client: TestClient, token: str, media_id: str) -> dict:
    brief = {
        "goal": "معرفی محصول",
        "audience": "خانواده‌ها",
        "channel": "تلگرام",
        "format": "پست تصویری",
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
    return {
        "draft_id": draft_id,
        "channel": "telegram",
        "chat_id": "@x",
        "campaign_code": "camp_m21",
        "image": {"kind": "generated", "media_asset_id": media_id},
    }


# ===========================================================================
# 1. Generation, storage, alt text, dedupe
# ===========================================================================


def test_m21_generate_stores_bytes_and_persian_alt(client: TestClient):
    token = _register(client, "m21-gen@example.com", "M21Gen")
    prompt_id = _visual_prompt(client, token)
    body = _generate(client, token, prompt_id)
    assert body["status"] == "draft"
    assert body["sha256"] and body["media_id"]
    assert "پکیج دزدگیر BH10" in body["alt_text"], (
        f"SEO alt must carry the subject: {body['alt_text']}"
    )
    assert re.compile(r"[؀-ۿ]").search(body["alt_text"]), "alt text is Persian"
    stored = list(Path(os.environ["MEDIA_STORAGE_DIR"]).rglob("*"))
    assert any(p.is_file() for p in stored), "bytes must land under MEDIA_STORAGE_DIR"


def test_m21_generate_dedupes_by_sha256(client: TestClient):
    token = _register(client, "m21-dedupe@example.com", "M21Dedupe")
    prompt_id = _visual_prompt(client, token)
    first = _generate(client, token, prompt_id)
    second = _generate(client, token, prompt_id)
    assert second["media_id"] == first["media_id"], "same bytes → same asset (rule 8)"
    items = client.get("/studio/media", headers=_auth(token)).json()["items"]
    assert len(items) == 1, items


def test_m21_media_list_is_tenant_scoped(client: TestClient):
    token_a = _register(client, "m21-lsa@example.com", "M21LsA")
    token_b = _register(client, "m21-lsb@example.com", "M21LsB")
    _generate(client, token_a, _visual_prompt(client, token_a))
    assert client.get("/studio/media", headers=_auth(token_b)).json()["items"] == [], (
        "tenant B must not see A's media (rule 6)"
    )


def test_m21_generate_requires_editor(client: TestClient):
    owner = _register(client, "m21-role-own@example.com", "M21RoleOwn")
    prompt_id = _visual_prompt(client, owner)
    invite = client.post(
        "/auth/invites",
        json={"email": "m21-obs@example.com", "role": "observer"},
        headers=_auth(owner),
    ).json()["token"]
    observer = client.post(
        "/auth/invites/accept", json={"token": invite, "password": "Password123!"}
    ).json()["access_token"]
    resp = client.post(
        "/studio/media", json={"prompt_id": prompt_id}, headers=_auth(observer)
    )
    assert resp.status_code == 403


# ===========================================================================
# 2. Approval gate — rule 1 covers images
# ===========================================================================


def test_m21_unapproved_asset_cannot_compile(client: TestClient):
    token = _register(client, "m21-gate@example.com", "M21Gate")
    media_id = _generate(client, token, _visual_prompt(client, token))["media_id"]
    payload = _approved_draft_job_payload(client, token, media_id)
    resp = client.post("/publish/jobs", json=payload, headers=_auth(token))
    assert resp.status_code == 409, (
        f"a draft visual must NOT reach a publish job (rule 1): {resp.status_code}"
    )


def test_m21_approved_asset_compiles_and_attaches(client: TestClient):
    token = _register(client, "m21-ok@example.com", "M21Ok")
    media_id = _generate(client, token, _visual_prompt(client, token))["media_id"]
    assert (
        client.post(f"/studio/media/{media_id}/approve", headers=_auth(token)).status_code
        == 200
    )
    payload = _approved_draft_job_payload(client, token, media_id)
    resp = client.post("/publish/jobs", json=payload, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    items = client.get("/studio/media", headers=_auth(token)).json()["items"]
    assert items[0]["status"] == "attached", items


def test_m21_foreign_asset_is_404(client: TestClient):
    token_a = _register(client, "m21-for-a@example.com", "M21ForA")
    token_b = _register(client, "m21-for-b@example.com", "M21ForB")
    media_b = _generate(client, token_b, _visual_prompt(client, token_b))["media_id"]
    client.post(f"/studio/media/{media_b}/approve", headers=_auth(token_b))
    payload = _approved_draft_job_payload(client, token_a, media_b)
    resp = client.post("/publish/jobs", json=payload, headers=_auth(token_a))
    assert resp.status_code == 404, (
        f"tenant B's asset must be invisible to A (rule 6): {resp.status_code}"
    )


def test_m21_template_jobs_unchanged(client: TestClient):
    token = _register(client, "m21-tmpl@example.com", "M21Tmpl")
    payload = _approved_draft_job_payload(client, token, "unused")
    payload["image"] = {"kind": "template", "template": "announce", "size": "square"}
    resp = client.post("/publish/jobs", json=payload, headers=_auth(token))
    assert resp.status_code == 201, resp.text


# ===========================================================================
# 3. Dispatch — generated bytes go out as photos
# ===========================================================================


def test_m21_dispatch_sends_generated_photo(client: TestClient):
    token = _register(client, "m21-send@example.com", "M21Send")
    media_id = _generate(client, token, _visual_prompt(client, token))["media_id"]
    client.post(f"/studio/media/{media_id}/approve", headers=_auth(token))
    payload = _approved_draft_job_payload(client, token, media_id)
    payload["channel"] = "bale"
    assert (
        client.post("/publish/jobs", json=payload, headers=_auth(token)).status_code == 201
    )
    resp = client.post(
        "/publish/dispatch", headers={"X-Internal-Token": _INTERNAL_TOKEN}
    )
    assert resp.status_code == 200 and resp.json()["sent"] == 1, resp.text
    assert channels._OUTBOX[0]["kind"] == "photo", channels._OUTBOX
    assert channels._OUTBOX[0]["image_size"] > 0


# ===========================================================================
# 4. Migration, export, locale
# ===========================================================================


def test_m21_migration_0016_exists_and_revises_0019():
    path = (
        _REPO_ROOT / "apps" / "core-api" / "migrations" / "versions" / "0016_media_assets.py"
    )
    assert path.exists(), "migration 0016 must exist"
    src = path.read_text("utf-8")
    assert re.search(r'revision\s*=\s*"0016"', src)
    assert re.search(r'down_revision\s*=\s*"0019"', src), (
        "chain order is execution order: 0015 → 0019 → 0016"
    )
    assert "media_assets" in src and "first_failed_at" in src


def test_m21_export_v3_carries_media_metadata_not_bytes(client: TestClient):
    token = _register(client, "m21-exp@example.com", "M21Exp")
    _generate(client, token, _visual_prompt(client, token))
    body = client.get("/export", headers=_auth(token)).json()
    assert body["export_version"] == 4, "M22 slice D is the current export contract"
    media = body["media_assets"]
    assert media and set(media[0]) >= {
        "id", "kind", "status", "alt_text", "sha256", "provider", "created_at"
    }, media
    assert "image_b64" not in json.dumps(media), "export carries metadata, never bytes"


def test_m21_locale_has_media_and_stalled_keys():
    fa = json.loads(_FA_JSON.read_text("utf-8"))
    for key in ("media_title", "media_generate", "media_empty", "media_approve",
                "media_status_draft", "media_status_approved", "media_status_attached"):
        assert fa["studio"].get(key), f"fa.studio.{key} missing"
    assert fa["publish"].get("status_stalled"), "fa.publish.status_stalled missing"
    assert fa["publish"].get("requeue"), "fa.publish.requeue missing"
