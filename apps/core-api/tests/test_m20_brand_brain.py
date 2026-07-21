"""
M20 acceptance tests — Kind-Centric Brand Brain (مغز برند کایند-محور).

Contract (design: docs/design/fable5-pentarchy.md §1 0015 + §3.1):
  Taxonomy
    - brain_chunks.kind ∈ product|tone|faq|claim|doc (default doc); the
      provenance kind on brain_sources (upload|crawl|pdf|catalog) stays a
      SEPARATE fact.
    - POST /brain/sources accepts knowledge_kind (validated Literal, 422
      otherwise); crawl/pdf ingest as doc.

  POST /brain/catalog  (tenant Bearer auth)
    - {products: [{name, sku?, price?, features[], url?}]} — each product
      becomes a DETERMINISTIC canonical Persian text block embedded as
      kind=product chunks; the raw structure persists in brain_sources.meta.
    - Replay upserts, never duplicates (content-hash dedupe, rule 8):
      response counts {ingested, skipped}.
    - rule 6: another tenant never sees the catalog.

  Retrieval
    - search_chunks/GET /brain/search accept a kinds filter (strict) and
      results carry the chunk kind.
    - BrandBrain.retrieve degrades instead of starving: kinds filter widens
      to include 'doc' when the tenant has no chunks of the asked kinds.
    - BrandBrain.compose_context: '[title] text' blocks, hard char budget.

  Injection
    - create_draft context_refs include catalog knowledge (facade-backed).
    - Visual Prompt Studio stops being retrieval-free: with product/tone
      knowledge present the expanded prompt carries a grounding section;
      with an empty brain the prompt is unchanged (m15 stays green).

  Export (DoD: the tenant owns every byte)
    - sources carry meta, chunks carry kind, export_version bumps to 2.

  Migration 0015 exists (0014 → 0015).

All tests named test_m20_<criterion>.
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

_PRODUCT = {
    "name": "پکیج دزدگیر BH10",
    "sku": "BH10",
    "price": "۱۲٬۵۰۰٬۰۰۰ تومان",
    "features": ["پشتیبانی سیم‌کارت", "آژیر بی‌سیم", "اپلیکیشن فارسی"],
    "url": "https://beewaz.ir/bh10",
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


def _session():
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from rpim_core_api import db as db_module  # noqa: PLC0415

    return Session(db_module.engine)


# ===========================================================================
# 1. Taxonomy at the ingest door
# ===========================================================================


def test_m20_source_accepts_knowledge_kind(client: TestClient):
    token = _register(client, "m20-kind@example.com", "M20Kind")
    resp = client.post(
        "/brain/sources",
        json={
            "title": "لحن برند",
            "text": "صمیمی ولی حرفه‌ای، بدون اغراق. " * 3,
            "knowledge_kind": "tone",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text


def test_m20_unknown_knowledge_kind_rejected(client: TestClient):
    token = _register(client, "m20-bad@example.com", "M20Bad")
    resp = client.post(
        "/brain/sources",
        json={"title": "x", "text": "متن آزمایشی کافی", "knowledge_kind": "banana"},
        headers=_auth(token),
    )
    assert resp.status_code == 422, f"unknown kind must 422: {resp.status_code}"


def test_m20_search_filters_by_kind_and_carries_kind(client: TestClient):
    token = _register(client, "m20-filter@example.com", "M20Filter")
    client.post(
        "/brain/sources",
        json={
            "title": "لحن",
            "text": "لحن برند ما گرم و صمیمی است. " * 3,
            "knowledge_kind": "tone",
        },
        headers=_auth(token),
    )
    client.post(
        "/brain/sources",
        json={"title": "سند عمومی", "text": "تاریخچه شرکت و مسیر رشد. " * 3},
        headers=_auth(token),
    )

    both = client.get("/brain/search", params={"q": "برند"}, headers=_auth(token)).json()
    assert {r["kind"] for r in both["results"]} == {"tone", "doc"}, (
        f"results must carry the chunk kind: {both}"
    )
    only_tone = client.get(
        "/brain/search", params={"q": "برند", "kinds": "tone"}, headers=_auth(token)
    ).json()
    assert only_tone["results"], "kind filter must not be empty here"
    assert {r["kind"] for r in only_tone["results"]} == {"tone"}, only_tone
    bad = client.get(
        "/brain/search", params={"q": "برند", "kinds": "banana"}, headers=_auth(token)
    )
    assert bad.status_code == 422, "unknown kinds value must 422"


# ===========================================================================
# 2. Product catalog door
# ===========================================================================


def test_m20_catalog_requires_auth_and_validates(client: TestClient):
    assert client.post("/brain/catalog", json={"products": [_PRODUCT]}).status_code == 401
    token = _register(client, "m20-val@example.com", "M20Val")
    assert (
        client.post("/brain/catalog", json={"products": []}, headers=_auth(token)).status_code
        == 422
    )
    assert (
        client.post(
            "/brain/catalog",
            json={"products": [{"name": "   "}]},
            headers=_auth(token),
        ).status_code
        == 422
    )


def test_m20_catalog_ingests_products_as_product_chunks(client: TestClient):
    token = _register(client, "m20-cat@example.com", "M20Cat")
    resp = client.post(
        "/brain/catalog", json={"products": [_PRODUCT]}, headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ingested"] == 1 and body["skipped"] == 0, body

    results = client.get(
        "/brain/search",
        params={"q": "دزدگیر", "kinds": "product"},
        headers=_auth(token),
    ).json()["results"]
    assert results, "catalog must be retrievable as kind=product"
    text = results[0]["text"]
    assert "پکیج دزدگیر BH10" in text, text
    assert "۱۲٬۵۰۰٬۰۰۰ تومان" in text, "price must survive into the canonical text"
    assert "آژیر بی‌سیم" in text, "features must survive into the canonical text"
    assert results[0]["source_title"] == "پکیج دزدگیر BH10"


def test_m20_catalog_replay_upserts_never_duplicates(client: TestClient):
    token = _register(client, "m20-replay@example.com", "M20Replay")
    first = client.post(
        "/brain/catalog", json={"products": [_PRODUCT]}, headers=_auth(token)
    ).json()
    second = client.post(
        "/brain/catalog", json={"products": [_PRODUCT]}, headers=_auth(token)
    ).json()
    assert first["ingested"] == 1, first
    assert second == {"ingested": 0, "skipped": 1}, (
        f"replayed catalog must dedupe (rule 8): {second}"
    )
    results = client.get(
        "/brain/search",
        params={"q": "دزدگیر", "kinds": "product", "k": 20},
        headers=_auth(token),
    ).json()["results"]
    titles = [r["source_title"] for r in results]
    assert titles.count("پکیج دزدگیر BH10") == len(titles), titles


def test_m20_catalog_is_tenant_isolated(client: TestClient):
    token_a = _register(client, "m20-iso-a@example.com", "M20IsoA")
    token_b = _register(client, "m20-iso-b@example.com", "M20IsoB")
    client.post("/brain/catalog", json={"products": [_PRODUCT]}, headers=_auth(token_a))
    b_view = client.get(
        "/brain/search", params={"q": "دزدگیر"}, headers=_auth(token_b)
    ).json()["results"]
    assert b_view == [], f"tenant B must not see A's catalog (rule 6): {b_view}"


# ===========================================================================
# 3. BrandBrain facade — strict filter, graceful fallback, budget
# ===========================================================================


def test_m20_facade_falls_back_to_doc_when_no_kinded_chunks(client: TestClient):
    from rpim_core_api.brain.service import BrandBrain  # noqa: PLC0415

    token = _register(client, "m20-fb@example.com", "M20Fb")
    client.post(
        "/brain/sources",
        json={"title": "سند عمومی", "text": "ما تولیدکننده دزدگیر هستیم. " * 3},
        headers=_auth(token),
    )
    me = client.get("/brand-profile", headers=_auth(token))
    tenant_id = me.json().get("tenant_id") or ""
    if not tenant_id:
        import jwt  # noqa: PLC0415

        tenant_id = jwt.decode(token, options={"verify_signature": False})["tenant_id"]

    with _session() as session:
        brain = BrandBrain(session, tenant_id)
        hits = brain.retrieve("دزدگیر", k=3, kinds=("product",))
        assert hits, "facade must degrade to doc chunks, never starve"
        assert {h["kind"] for h in hits} == {"doc"}, hits

        client.post(
            "/brain/catalog", json={"products": [_PRODUCT]}, headers=_auth(token)
        )
    with _session() as session:
        brain = BrandBrain(session, tenant_id)
        hits = brain.retrieve("دزدگیر", k=5, kinds=("product",))
        assert hits and {h["kind"] for h in hits} == {"product"}, (
            f"once product chunks exist the strict filter applies: {hits}"
        )


def test_m20_compose_context_format_and_budget():
    from rpim_core_api.brain.service import BrandBrain  # noqa: PLC0415

    chunks = [
        {"source_title": "منبع اول", "text": "متن اول", "kind": "doc"},
        {"source_title": "منبع دوم", "text": "م" * 500, "kind": "doc"},
    ]
    block = BrandBrain.compose_context(chunks)
    assert block.startswith("[منبع اول] متن اول"), block
    assert "\n\n[منبع دوم] " in block, "blocks join with a blank line"

    tight = BrandBrain.compose_context(chunks, budget_chars=30)
    assert tight == "[منبع اول] متن اول", (
        f"budget must drop whole blocks that do not fit: {tight!r}"
    )


# ===========================================================================
# 4. Injection — drafts and the studio both ask the brain
# ===========================================================================


def test_m20_draft_context_includes_catalog_knowledge(client: TestClient):
    token = _register(client, "m20-draft@example.com", "M20Draft")
    client.post("/brain/catalog", json={"products": [_PRODUCT]}, headers=_auth(token))
    resp = client.post(
        "/content/drafts",
        json={
            "brief": {
                "goal": "معرفی پکیج دزدگیر",
                "audience": "خانواده‌ها",
                "channel": "تلگرام",
                "format": "پست متنی",
                "hook": None,
                "cta": None,
            }
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    refs = resp.json().get("context_refs", [])
    assert "پکیج دزدگیر BH10" in refs, (
        f"catalog knowledge must ground the draft (context_refs): {refs}"
    )


def test_m20_studio_prompt_grounds_on_brand_knowledge(client: TestClient):
    token = _register(client, "m20-studio@example.com", "M20Studio")
    client.post("/brain/catalog", json={"products": [_PRODUCT]}, headers=_auth(token))
    resp = client.post(
        "/studio/prompts",
        json={"kind": "image", "brief": {"subject": "دزدگیر BH10"}},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    prompt = resp.json()["prompt_text"]
    assert "Brand grounding" in prompt, f"studio must retrieve now: {prompt}"
    assert "پکیج دزدگیر BH10" in prompt, prompt


def test_m20_studio_without_brain_stays_ungrounded(client: TestClient):
    token = _register(client, "m20-empty@example.com", "M20Empty")
    resp = client.post(
        "/studio/prompts",
        json={"kind": "image", "brief": {"subject": "قهوه"}},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    assert "Brand grounding" not in resp.json()["prompt_text"], (
        "empty brain must not inject an empty grounding section"
    )


# ===========================================================================
# 5. Export delta (DoD) + migration exists
# ===========================================================================


def test_m20_export_carries_meta_and_kind(client: TestClient):
    token = _register(client, "m20-export@example.com", "M20Export")
    client.post("/brain/catalog", json={"products": [_PRODUCT]}, headers=_auth(token))
    body = client.get("/export", headers=_auth(token)).json()
    assert body["export_version"] == 4, "M22 slice D is the current export contract"
    sources = body["brain"]["sources"]
    catalog = [s for s in sources if s["kind"] == "catalog"]
    assert catalog, f"catalog source must export with provenance kind: {sources}"
    assert catalog[0]["meta"]["sku"] == "BH10", catalog[0]
    assert catalog[0]["chunks"][0]["kind"] == "product", catalog[0]["chunks"][0]


def test_m20_migration_0015_exists():
    path = (
        _REPO_ROOT
        / "apps"
        / "core-api"
        / "migrations"
        / "versions"
        / "0015_brand_knowledge_kinds.py"
    )
    assert path.exists(), "migration 0015 must exist"
    src = path.read_text("utf-8")
    assert re.search(r'revision\s*=\s*"0015"', src)
    assert re.search(r'down_revision\s*=\s*"0014"', src)
    assert "ix_brain_chunks_tenant_kind" in src, "composite (tenant, kind) index required"


def test_m20_export_marker_still_json(client: TestClient):
    token = _register(client, "m20-json@example.com", "M20Json")
    body = client.get("/export", headers=_auth(token)).json()
    json.dumps(body)  # remains serializable end-to-end
