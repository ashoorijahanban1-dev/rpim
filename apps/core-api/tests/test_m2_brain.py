"""
M2 acceptance tests — core-api brain routes.

Routes under test:
  POST /brain/sources
    Body: {"title": str, "kind": str, "text": str}
    → 201 {"source_id": <str>, "chunks": <int ≥ 1>}

  GET /brain/search?q=<Persian query>&k=5
    → 200 {"results": [{"text": str, "source_id": str,
                         "source_title": str, "score": float} ...]}
       len(results) ≤ 5
       After uploading a source whose text IS the query, the top result's
       text contains the query (fake embeddings: identical text → identical
       vector → top cosine score).

Both routes require Bearer auth; unauthenticated requests → 401.
Cross-tenant isolation: Tenant B's search must not expose Tenant A's sources.

env EMBED_MODE=fake is set at module level so the implementation uses
rpim_shared.fake_embed locally — no network calls required.

These tests FAIL until the /brain/* routes are implemented.
"""

from __future__ import annotations

import os

# Must be set BEFORE any import of rpim_core_api.brain so the implementation
# uses the deterministic fake embedder, not the real model-gateway.
os.environ.setdefault("EMBED_MODE", "fake")

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers (mirrors the pattern used in test_m1_identity_tenancy.py)
# ---------------------------------------------------------------------------


def _register(client: TestClient, email: str, password: str, tenant_name: str) -> dict:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "tenant_name": tenant_name},
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    return resp.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _upload_source(
    client: TestClient,
    token: str,
    *,
    title: str,
    text: str,
    kind: str = "upload",
) -> dict:
    resp = client.post(
        "/brain/sources",
        json={"title": title, "kind": kind, "text": text},
        headers=_auth(token),
    )
    return resp


# A short Persian sentence used as both the upload text and the search query.
# Being ≤ 700 chars it becomes one chunk; fake_embed(chunk) == fake_embed(query).
_QUERY_SENTENCE = (
    "محصولات ما بهترین کیفیت را دارند و قیمت مناسب برای مشتریان ایرانی هستند."
)

# A large Persian text for upload-then-search tests (> 100 chars, distinct content).
_LONG_SOURCE_TEXT = (
    "کاتالوگ محصولات شرکت نوآوران ایران در سال جاری.\n\n"
    + _QUERY_SENTENCE + "\n\n"
    "این شرکت با بیش از بیست سال سابقه در تولید محصولات با کیفیت، "
    "خود را به عنوان یک برند معتبر در بازار ایران معرفی کرده است."
)


# ---------------------------------------------------------------------------
# 1. POST /brain/sources — upload & chunk
# ---------------------------------------------------------------------------


def test_m2_brain_sources_returns_201(client: TestClient):
    """POST /brain/sources with valid body and auth → 201."""
    token = _register(client, "brain1@example.com", "password123", "BrainBrand1")["access_token"]
    resp = _upload_source(client, token, title="کاتالوگ", text=_LONG_SOURCE_TEXT)
    assert resp.status_code == 201, (
        f"expected 201 from POST /brain/sources, got {resp.status_code}: {resp.text}"
    )


def test_m2_brain_sources_response_has_source_id(client: TestClient):
    """201 response must contain a non-empty source_id."""
    token = _register(client, "brain2@example.com", "password123", "BrainBrand2")["access_token"]
    resp = _upload_source(client, token, title="کاتالوگ محصول", text=_LONG_SOURCE_TEXT)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "source_id" in body, f"'source_id' missing from response: {body}"
    assert body["source_id"], "'source_id' must be non-empty"


def test_m2_brain_sources_response_chunks_gte_1(client: TestClient):
    """201 response must contain chunks ≥ 1 (at least one chunk was stored)."""
    token = _register(client, "brain3@example.com", "password123", "BrainBrand3")["access_token"]
    resp = _upload_source(client, token, title="سند برند", text=_LONG_SOURCE_TEXT)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "chunks" in body, f"'chunks' missing from response: {body}"
    assert isinstance(body["chunks"], int), f"'chunks' must be an int, got {type(body['chunks'])}"
    assert body["chunks"] >= 1, f"'chunks' must be ≥ 1, got {body['chunks']}"


def test_m2_brain_sources_unauthenticated_returns_401(client: TestClient):
    """POST /brain/sources without Authorization → 401."""
    resp = client.post(
        "/brain/sources",
        json={"title": "test", "kind": "upload", "text": "متن آزمایشی"},
    )
    assert resp.status_code == 401, (
        f"expected 401 for unauthenticated POST /brain/sources, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# 2. GET /brain/search — vector similarity retrieval
# ---------------------------------------------------------------------------


def test_m2_brain_search_returns_200(client: TestClient):
    """GET /brain/search with auth and query → 200."""
    token = _register(client, "search1@example.com", "password123", "SearchBrand1")["access_token"]
    _upload_source(client, token, title="سند جستجو", text=_LONG_SOURCE_TEXT)
    resp = client.get("/brain/search", params={"q": "کیفیت", "k": 5}, headers=_auth(token))
    assert resp.status_code == 200, (
        f"expected 200 from GET /brain/search, got {resp.status_code}: {resp.text}"
    )


def test_m2_brain_search_results_have_required_fields(client: TestClient):
    """Each result must have text, source_id, source_title, score fields."""
    token = _register(client, "search2@example.com", "password123", "SearchBrand2")["access_token"]
    _upload_source(client, token, title="کاتالوگ آزمایشی", text=_LONG_SOURCE_TEXT)
    resp = client.get("/brain/search", params={"q": "محصول", "k": 5}, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "results" in body, f"'results' key missing from response: {body}"
    for idx, result in enumerate(body["results"]):
        for field in ("text", "source_id", "source_title", "score"):
            assert field in result, (
                f"result[{idx}] missing field '{field}': {result}"
            )
        assert isinstance(result["score"], float), (
            f"result[{idx}]['score'] must be float, got {type(result['score'])}"
        )


def test_m2_brain_search_results_len_lte_k(client: TestClient):
    """GET /brain/search?k=5 → at most 5 results returned."""
    token = _register(client, "search3@example.com", "password123", "SearchBrand3")["access_token"]
    _upload_source(client, token, title="سند اول", text=_LONG_SOURCE_TEXT)
    resp = client.get("/brain/search", params={"q": "برند", "k": 5}, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    assert len(results) <= 5, (
        f"GET /brain/search?k=5 must return at most 5 results; got {len(results)}"
    )


def test_m2_brain_search_top_result_contains_query_sentence(client: TestClient):
    """After uploading a source whose text IS the query sentence, the top result
    must contain that sentence.

    Design rationale: _QUERY_SENTENCE is short (≤ 700 chars), so the chunker
    stores it as a single chunk.  fake_embed(_QUERY_SENTENCE) == fake_embed(query)
    → cosine similarity = 1.0 → guaranteed top score.
    """
    token = _register(client, "search4@example.com", "password123", "SearchBrand4")["access_token"]
    # Upload a source whose text IS the query sentence (≤ 700 chars → single chunk).
    _upload_source(client, token, title="جمله هدف", text=_QUERY_SENTENCE)

    resp = client.get(
        "/brain/search",
        params={"q": _QUERY_SENTENCE, "k": 5},
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()["results"]
    assert len(results) >= 1, "must return at least 1 result after uploading a matching source"

    top = results[0]
    assert _QUERY_SENTENCE in top["text"], (
        f"top result text must contain the query sentence.\n"
        f"query={_QUERY_SENTENCE!r}\ntop result text={top['text']!r}"
    )


def test_m2_brain_search_unauthenticated_returns_401(client: TestClient):
    """GET /brain/search without Authorization → 401."""
    resp = client.get("/brain/search", params={"q": "محصول", "k": 5})
    assert resp.status_code == 401, (
        f"expected 401 for unauthenticated GET /brain/search, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# 3. Cross-tenant isolation (CLAUDE.md rule 6)
#    New tables introduced by M2 must ship with a cross-tenant isolation test.
# ---------------------------------------------------------------------------


def test_m2_brain_cross_tenant_isolation(client: TestClient):
    """Tenant B's search must return zero results containing Tenant A's marker.

    Steps
    -----
    1. Tenant A uploads a source whose entire text is a distinctive marker sentence.
    2. Tenant B searches for that exact marker sentence.
    3. None of B's results must contain the marker.
    4. Tenant B can upload its own source and find it normally (positive control).

    This proves that the brain_sources and brain_chunks tables are scoped by
    tenant_id and never leak data across tenant boundaries.
    """
    MARKER = (
        "جمله‌ی منحصربه‌فرد اختصاصی برند الف که هرگز نباید در نتایج برند ب دیده شود."
    )
    B_TEXT = "متن اختصاصی برند ب برای آزمایش ایزولاسیون بین مستاجران سیستم."

    # --- Tenant A uploads the marker ---
    token_a = _register(client, "isol-a@brain.com", "password123", "IsolBrainA")["access_token"]
    upload_a = _upload_source(client, token_a, title="سند الف", text=MARKER)
    assert upload_a.status_code == 201, f"Tenant A upload failed: {upload_a.text}"

    # --- Tenant B searches for the marker ---
    token_b = _register(client, "isol-b@brain.com", "password123", "IsolBrainB")["access_token"]
    search_resp = client.get(
        "/brain/search",
        params={"q": MARKER, "k": 5},
        headers=_auth(token_b),
    )
    assert search_resp.status_code == 200, (
        f"Tenant B search failed: {search_resp.status_code}: {search_resp.text}"
    )

    for idx, result in enumerate(search_resp.json()["results"]):
        assert MARKER not in result["text"], (
            f"Tenant B's result[{idx}] contains Tenant A's marker — cross-tenant leak!\n"
            f"result text: {result['text']!r}"
        )

    # --- Positive control: Tenant B can find its own uploaded source ---
    upload_b = _upload_source(client, token_b, title="سند ب", text=B_TEXT)
    assert upload_b.status_code == 201, f"Tenant B upload failed: {upload_b.text}"

    search_b_own = client.get(
        "/brain/search",
        params={"q": B_TEXT, "k": 5},
        headers=_auth(token_b),
    )
    assert search_b_own.status_code == 200, search_b_own.text
    b_texts = [r["text"] for r in search_b_own.json()["results"]]
    assert any(B_TEXT in t for t in b_texts), (
        f"Tenant B cannot find its own uploaded source after isolation check.\n"
        f"B's results: {b_texts}"
    )


# ---------------------------------------------------------------------------
# Robustness (production incident): large sources must embed in batches and
# embedding failures must surface as clean 503s, never raw 500s
# ---------------------------------------------------------------------------


def test_embed_client_batches_large_inputs(monkeypatch):
    """embed_texts must split >32 texts into ≤32-sized calls and concatenate
    vectors in order — a 300-chunk PDF in one request blew the 15s timeout."""
    import rpim_core_api.brain.embed_client as ec  # noqa: PLC0415

    calls: list[int] = []

    class _Resp:
        def __init__(self, n: int):
            self._n = n

        def raise_for_status(self):
            return None

        def json(self):
            return {"vectors": [[0.0] * 3] * self._n}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        calls.append(len(json["texts"]))
        return _Resp(len(json["texts"]))

    monkeypatch.setenv("EMBED_MODE", "remote")
    monkeypatch.setenv("GATEWAY_URL", "http://gateway.test:8080")
    import httpx  # noqa: PLC0415

    monkeypatch.setattr(httpx, "post", fake_post)

    vectors = ec.embed_texts([f"t{i}" for i in range(70)], tenant_id="t1")
    assert len(vectors) == 70, f"all vectors must come back, got {len(vectors)}"
    assert all(size <= 32 for size in calls), f"batch sizes exceeded 32: {calls}"
    assert len(calls) == 3, f"70 texts should take 3 batches of <=32, got {calls}"


def test_ingest_embed_failure_returns_503_not_500(client, monkeypatch):
    """A dead/slow embedding path must be a clean 503 whose detail names the
    embedding service — the dashboard maps it to Persian."""
    import httpx  # noqa: PLC0415

    import rpim_core_api.routers.brain as brain_router  # noqa: PLC0415

    def dead_embed(texts, tenant_id=None):
        raise httpx.ConnectTimeout("embed path down")

    monkeypatch.setattr(brain_router, "embed_texts", dead_embed)

    token = _register(
        client, "embed-down@example.com", "Password123!", "EmbedDown"
    )["access_token"]
    resp = client.post(
        "/brain/sources",
        json={"title": "t", "text": "متن آزمایشی برای مسیر امبدینگ."},
        headers=_auth(token),
    )
    assert resp.status_code == 503, (
        f"embed failure must be 503, got {resp.status_code}: {resp.text}"
    )
    assert "embedding" in resp.json()["detail"].lower(), (
        f"detail must name the embedding service: {resp.json()}"
    )


def test_reindex_reembeds_only_own_tenant_chunks(client, monkeypatch):
    """POST /brain/reindex re-embeds every chunk of the CALLING tenant only
    (rule 6) and reports counts — the recovery path for sources ingested
    while the embedding backend was fake."""
    token_a = _register(
        client, "reindex-a@example.com", "Password123!", "ReindexA"
    )["access_token"]
    token_b = _register(
        client, "reindex-b@example.com", "Password123!", "ReindexB"
    )["access_token"]
    for i in range(2):
        resp = client.post(
            "/brain/sources",
            json={"title": f"s{i}", "text": f"متن منبع شماره {i} برای بازسازی ایندکس."},
            headers=_auth(token_a),
        )
        assert resp.status_code == 201, resp.text
    resp = client.post(
        "/brain/sources",
        json={"title": "b", "text": "منبع تنانت دیگر — نباید شمارش شود."},
        headers=_auth(token_b),
    )
    assert resp.status_code == 201, resp.text

    resp = client.post("/brain/reindex", headers=_auth(token_a))
    assert resp.status_code == 200, f"reindex failed: {resp.status_code} {resp.text}"
    body = resp.json()
    assert body["sources"] == 2, f"tenant A has 2 sources, got {body}"
    assert body["chunks"] >= 2, f"tenant A chunks must be re-embedded, got {body}"
