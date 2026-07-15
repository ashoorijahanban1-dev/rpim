"""
M15 acceptance tests — Visual Prompt Studio (استودیوی پرامپت بصری).

Contract:
  POST /studio/prompts  (tenant Bearer auth)
    - 401 without token; 422 for unknown kind or blank subject
    - Expands {kind: image|video, brief:{subject, mood?, channel?}} into a
      DETERMINISTIC professional generative-model prompt (English, since the
      target models are English-prompted): must carry the subject, the brand
      tone (from the tenant's brand profile), a channel-appropriate aspect
      ratio, quality descriptors, and a negative-prompt section for images;
      video prompts add motion/camera language.
    - Persists the row (tenant-scoped) and returns {prompt_id, prompt_text}.
  GET /studio/prompts — the calling tenant's prompts only (rule 6), newest first.

Dashboard static contract: /studio page exists, sidebar-linked, locale-only.
All tests named test_m15_<criterion>.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi.testclient import TestClient

os.environ.setdefault("EMBED_MODE", "fake")
os.environ.setdefault("COMPLETE_MODE", "fake")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PAGE_TSX = _REPO_ROOT / "apps" / "dashboard" / "app" / "studio" / "page.tsx"
_SIDEBAR = _REPO_ROOT / "apps" / "dashboard" / "components" / "Sidebar.tsx"
_FA_JSON = _REPO_ROOT / "apps" / "dashboard" / "locales" / "fa.json"

_TONE = "گرم و صمیمی"


def _register(client: TestClient, email: str, name: str) -> str:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "tenant_name": name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _tenant_with_tone(client: TestClient, email: str, name: str) -> str:
    token = _register(client, email, name)
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
    return token


def test_m15_create_requires_auth(client: TestClient):
    resp = client.post(
        "/studio/prompts", json={"kind": "image", "brief": {"subject": "قهوه"}}
    )
    assert resp.status_code == 401, f"expected 401, got {resp.status_code}"


def test_m15_validation(client: TestClient):
    token = _register(client, "studio-val@example.com", "StudioVal")
    resp = client.post(
        "/studio/prompts",
        json={"kind": "gif", "brief": {"subject": "قهوه"}},
        headers=_auth(token),
    )
    assert resp.status_code == 422, f"unknown kind must 422: {resp.status_code}"
    resp = client.post(
        "/studio/prompts",
        json={"kind": "image", "brief": {"subject": "   "}},
        headers=_auth(token),
    )
    assert resp.status_code == 422, f"blank subject must 422: {resp.status_code}"


def test_m15_image_prompt_carries_brief_tone_and_aspect(client: TestClient):
    token = _tenant_with_tone(client, "studio-img@example.com", "StudioImg")
    resp = client.post(
        "/studio/prompts",
        json={
            "kind": "image",
            "brief": {"subject": "پکیج دزدگیر BH10", "mood": "مدرن", "channel": "telegram"},
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    prompt = body["prompt_text"]
    assert body["prompt_id"]
    assert "پکیج دزدگیر BH10" in prompt, f"subject must appear verbatim: {prompt}"
    assert _TONE in prompt, f"brand tone must steer the style: {prompt}"
    assert "1:1" in prompt, f"telegram post → square aspect: {prompt}"
    assert "Negative prompt:" in prompt, f"images need a negative section: {prompt}"
    assert re.search(r"high detail|photorealistic|studio lighting", prompt), (
        f"professional quality descriptors expected: {prompt}"
    )


def test_m15_video_prompt_adds_motion_language(client: TestClient):
    token = _tenant_with_tone(client, "studio-vid@example.com", "StudioVid")
    resp = client.post(
        "/studio/prompts",
        json={"kind": "video", "brief": {"subject": "دوربین مداربسته", "channel": "story"}},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    prompt = resp.json()["prompt_text"]
    assert "9:16" in prompt, f"story → vertical aspect: {prompt}"
    assert re.search(r"camera|motion|cinematic", prompt), (
        f"video prompts must direct motion/camera: {prompt}"
    )
    assert "Negative prompt:" not in prompt, "negative section is image-only"


def test_m15_expansion_is_deterministic(client: TestClient):
    token = _tenant_with_tone(client, "studio-det@example.com", "StudioDet")
    payload = {"kind": "image", "brief": {"subject": "قهوه دانو", "channel": "wordpress"}}
    first = client.post("/studio/prompts", json=payload, headers=_auth(token)).json()
    second = client.post("/studio/prompts", json=payload, headers=_auth(token)).json()
    assert first["prompt_text"] == second["prompt_text"], (
        "same brief must expand identically (algorithmic, reviewable)"
    )


def test_m15_list_is_tenant_scoped_newest_first(client: TestClient):
    token_a = _tenant_with_tone(client, "studio-a@example.com", "StudioA")
    token_b = _tenant_with_tone(client, "studio-b@example.com", "StudioB")
    for subject in ("موضوع اول", "موضوع دوم"):
        assert (
            client.post(
                "/studio/prompts",
                json={"kind": "image", "brief": {"subject": subject}},
                headers=_auth(token_a),
            ).status_code
            == 201
        )
    b_items = client.get("/studio/prompts", headers=_auth(token_b)).json()["items"]
    assert b_items == [], f"tenant B must not see tenant A prompts (rule 6): {b_items}"
    a_items = client.get("/studio/prompts", headers=_auth(token_a)).json()["items"]
    assert len(a_items) == 2
    assert "موضوع دوم" in a_items[0]["prompt_text"], "newest first"
    assert set(a_items[0]) >= {"prompt_id", "kind", "prompt_text", "created_at"}


def test_m15_dashboard_page_and_locale():
    assert _PAGE_TSX.exists(), "apps/dashboard/app/studio/page.tsx must exist"
    src = _PAGE_TSX.read_text("utf-8")
    assert "/studio/prompts" in src
    assert not re.compile(r"[؀-ۿ]").search(src), "locale-only rule"
    assert 'href: "/studio"' in _SIDEBAR.read_text("utf-8")
    fa = json.loads(_FA_JSON.read_text("utf-8"))
    studio = fa.get("studio", {})
    for key in ("title", "subject", "mood", "channel", "kind_image", "kind_video",
                "submit", "empty", "copy", "hint"):
        assert studio.get(key), f"fa.studio.{key} missing/empty"
    assert fa["nav"].get("studio"), "fa.nav.studio missing"
