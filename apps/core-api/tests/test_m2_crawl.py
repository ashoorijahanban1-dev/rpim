"""
M2 crawl-ingestion acceptance tests.

Route under test:
  POST /brain/sources/crawl  (Bearer auth)
    Body: {"url": str, "max_pages": int}  (max_pages optional, default 5, server cap 10)
    → 201 {"source_id": str, "chunks": int >= 1, "pages": int}

The crawler fetches same-domain pages breadth-first starting at url.
For tests, monkeypatch rpim_core_api.brain.crawler.fetch_page.
Signature: fetch_page(url: str) -> tuple[str, list[str]]
  Returns (extracted_page_text, discovered_same_domain_links).

These tests FAIL until POST /brain/sources/crawl is implemented:
  - tests that do not need monkeypatching fail with 404 (route absent)
  - tests that monkeypatch fail with ModuleNotFoundError on
    rpim_core_api.brain.crawler (module absent)
"""

from __future__ import annotations

import os

# Must be set BEFORE any import of rpim_core_api.brain so the implementation
# uses the deterministic fake embedder — no network calls required.
os.environ.setdefault("EMBED_MODE", "fake")

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Distinctive Persian marker sentence embedded in the stub root page.
# Short enough to land in a single chunk; fake_embed identical text → score 1.0.
_MARKER = "شرکت نوآوران دیجیتال محصولات آینده را برای بازار ایران می‌سازد."

_ROOT_URL = "https://brand.example"
_PAGE_A_URL = "https://brand.example/a"
_PAGE_B_URL = "https://brand.example/b"

# ---------------------------------------------------------------------------
# Reusable stub: tiny 3-page site (root → /a, /b; /a and /b have no links)
# ---------------------------------------------------------------------------


def _three_page_stub(url: str) -> tuple[str, list[str]]:
    """Serve a deterministic 3-page site for the crawler to traverse."""
    if url in (_ROOT_URL, _ROOT_URL + "/"):
        return (
            f"صفحه اصلی برند. {_MARKER}",
            [_PAGE_A_URL, _PAGE_B_URL],
        )
    if url == _PAGE_A_URL:
        return ("صفحه الف: توضیحات محصول الف.", [])
    if url == _PAGE_B_URL:
        return ("صفحه ب: توضیحات محصول ب.", [])
    return ("", [])


# ---------------------------------------------------------------------------
# Helpers (established pattern from test_m2_brain.py / test_m2_pdf.py)
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


def _crawl(
    client: TestClient,
    token: str | None,
    url: str,
    max_pages: int | None = None,
) -> object:
    """POST to /brain/sources/crawl, optionally with Bearer auth and max_pages."""
    body: dict = {"url": url}
    if max_pages is not None:
        body["max_pages"] = max_pages
    headers = _auth(token) if token is not None else {}
    return client.post("/brain/sources/crawl", json=body, headers=headers)


# ---------------------------------------------------------------------------
# 1. Happy path — 3-page crawl → 201 + search round-trip
# ---------------------------------------------------------------------------


def test_m2_crawl_happy_path_returns_201(client: TestClient, monkeypatch):
    """Crawling a 3-page site with valid auth → 201 with source_id and chunks >= 1.

    The stub serves root + /a + /b.  The 201 body must include source_id,
    chunks >= 1, and pages >= 1.
    """
    import rpim_core_api.brain.crawler as _crawler_mod  # noqa: PLC0415

    monkeypatch.setattr(_crawler_mod, "fetch_page", _three_page_stub)

    token = _register(
        client, "crawl-happy@example.com", "Password123!", "CrawlHappy"
    )["access_token"]
    resp = _crawl(client, token, _ROOT_URL)
    assert resp.status_code == 201, (
        f"expected 201 from POST /brain/sources/crawl, "
        f"got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "source_id" in body, f"'source_id' missing from response: {body}"
    assert body["source_id"], "'source_id' must be non-empty"
    assert "chunks" in body, f"'chunks' missing from response: {body}"
    assert isinstance(body["chunks"], int), (
        f"'chunks' must be int, got {type(body['chunks'])}"
    )
    assert body["chunks"] >= 1, f"'chunks' must be >= 1, got {body['chunks']}"
    assert "pages" in body, f"'pages' missing from response: {body}"
    assert isinstance(body["pages"], int), (
        f"'pages' must be int, got {type(body['pages'])}"
    )
    assert body["pages"] >= 1, f"'pages' must be >= 1, got {body['pages']}"


def test_m2_crawl_happy_path_search_finds_marker(client: TestClient, monkeypatch):
    """After crawling a 3-page site, GET /brain/search for the Persian marker
    (same tenant) returns a top result whose text contains the marker.

    The marker is embedded in the root page text.  fake_embed(marker) ==
    fake_embed(query) → cosine 1.0 → guaranteed top rank.
    """
    import rpim_core_api.brain.crawler as _crawler_mod  # noqa: PLC0415

    monkeypatch.setattr(_crawler_mod, "fetch_page", _three_page_stub)

    token = _register(
        client, "crawl-search@example.com", "Password123!", "CrawlSearch"
    )["access_token"]
    crawl_resp = _crawl(client, token, _ROOT_URL)
    assert crawl_resp.status_code == 201, (
        f"crawl failed: {crawl_resp.status_code}: {crawl_resp.text}"
    )

    search_resp = client.get(
        "/brain/search",
        params={"q": _MARKER, "k": 5},
        headers=_auth(token),
    )
    assert search_resp.status_code == 200, (
        f"expected 200 from GET /brain/search, "
        f"got {search_resp.status_code}: {search_resp.text}"
    )
    results = search_resp.json()["results"]
    assert len(results) >= 1, (
        "must return at least 1 result after crawling a site with the marker"
    )
    assert any(_MARKER in r["text"] for r in results), (
        f"no result contains the Persian marker.\n"
        f"marker: {_MARKER!r}\n"
        f"result texts: {[r['text'] for r in results]}"
    )


# ---------------------------------------------------------------------------
# 2. max_pages is respected
# ---------------------------------------------------------------------------


def test_m2_crawl_max_pages_respected(client: TestClient, monkeypatch):
    """With max_pages=2 and root linking to 4 children, the 201 response must
    have pages == 2 and fetch_page must be called exactly twice.

    The breadth-first crawler visits the root first (call 1), discovers 4
    children, but stops after the second call because max_pages=2.
    """
    import rpim_core_api.brain.crawler as _crawler_mod  # noqa: PLC0415

    call_log: list[str] = []

    def four_child_site(url: str) -> tuple[str, list[str]]:
        call_log.append(url)
        children = [
            "https://brand.example/c",
            "https://brand.example/d",
            "https://brand.example/e",
            "https://brand.example/f",
        ]
        if url == "https://brand.example":
            return ("صفحه ریشه با چهار فرزند.", children)
        return (f"محتوای {url}.", [])

    monkeypatch.setattr(_crawler_mod, "fetch_page", four_child_site)

    token = _register(
        client, "crawl-maxpg@example.com", "Password123!", "CrawlMaxPages"
    )["access_token"]
    resp = _crawl(client, token, "https://brand.example", max_pages=2)
    assert resp.status_code == 201, (
        f"expected 201, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body.get("pages") == 2, (
        f"expected pages=2 in response, got {body.get('pages')!r}; full body: {body}"
    )
    assert len(call_log) == 2, (
        f"expected fetch_page called exactly 2 times, got {len(call_log)}; "
        f"calls: {call_log}"
    )


# ---------------------------------------------------------------------------
# 3. Unauthenticated → 401
# ---------------------------------------------------------------------------


def test_m2_crawl_unauthenticated_returns_401(client: TestClient):
    """POST /brain/sources/crawl without Authorization → 401."""
    resp = _crawl(client, None, _ROOT_URL)
    assert resp.status_code == 401, (
        f"expected 401 for unauthenticated crawl request, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# 4. SSRF guards → 422 without calling fetch_page
# ---------------------------------------------------------------------------


def test_m2_crawl_ssrf_ftp_scheme_rejected(client: TestClient, monkeypatch):
    """URL with ftp:// scheme → 422 and fetch_page must NOT be called.

    Only http:// and https:// are valid schemes for web crawling; non-HTTP
    schemes are SSRF attack vectors and must be rejected before any I/O.
    """
    import rpim_core_api.brain.crawler as _crawler_mod  # noqa: PLC0415

    call_log: list[str] = []

    def stub(url: str) -> tuple[str, list[str]]:
        call_log.append(url)
        return ("", [])

    monkeypatch.setattr(_crawler_mod, "fetch_page", stub)

    token = _register(
        client, "crawl-ftp@example.com", "Password123!", "CrawlFTP"
    )["access_token"]
    resp = _crawl(client, token, "ftp://brand.example/resource")
    assert resp.status_code == 422, (
        f"expected 422 for ftp:// URL, got {resp.status_code}: {resp.text}"
    )
    assert len(call_log) == 0, (
        f"fetch_page must NOT be called for a rejected URL; "
        f"it was called with: {call_log}"
    )


def test_m2_crawl_ssrf_loopback_ip_rejected(client: TestClient, monkeypatch):
    """URL pointing at 127.0.0.1 (loopback) → 422; fetch_page must NOT be called.

    The implementation resolves hostnames; literal 127.0.0.1 resolves to itself
    and falls in the loopback range — must be rejected before any I/O.
    """
    import rpim_core_api.brain.crawler as _crawler_mod  # noqa: PLC0415

    call_log: list[str] = []

    def stub(url: str) -> tuple[str, list[str]]:
        call_log.append(url)
        return ("", [])

    monkeypatch.setattr(_crawler_mod, "fetch_page", stub)

    token = _register(
        client, "crawl-loop@example.com", "Password123!", "CrawlLoopback"
    )["access_token"]
    resp = _crawl(client, token, "http://127.0.0.1/x")
    assert resp.status_code == 422, (
        f"expected 422 for loopback IP, got {resp.status_code}: {resp.text}"
    )
    assert len(call_log) == 0, (
        f"fetch_page must NOT be called for a rejected URL; "
        f"it was called with: {call_log}"
    )


def test_m2_crawl_ssrf_private_ip_rejected(client: TestClient, monkeypatch):
    """URL pointing at 192.168.1.10 (private range) → 422; fetch_page must NOT be called.

    The implementation resolves hostnames; literal 192.168.1.10 resolves to
    itself and falls in RFC-1918 space — must be rejected before any I/O.
    """
    import rpim_core_api.brain.crawler as _crawler_mod  # noqa: PLC0415

    call_log: list[str] = []

    def stub(url: str) -> tuple[str, list[str]]:
        call_log.append(url)
        return ("", [])

    monkeypatch.setattr(_crawler_mod, "fetch_page", stub)

    token = _register(
        client, "crawl-priv@example.com", "Password123!", "CrawlPrivate"
    )["access_token"]
    resp = _crawl(client, token, "http://192.168.1.10/x")
    assert resp.status_code == 422, (
        f"expected 422 for private IP, got {resp.status_code}: {resp.text}"
    )
    assert len(call_log) == 0, (
        f"fetch_page must NOT be called for a rejected URL; "
        f"it was called with: {call_log}"
    )


# ---------------------------------------------------------------------------
# 5. Idempotency — same URL twice → same source_id
# ---------------------------------------------------------------------------


def test_m2_crawl_idempotent_same_source_id(client: TestClient, monkeypatch):
    """Crawling the same URL twice for the same tenant with identical stub content
    → second call returns the SAME source_id.

    The crawler hashes the aggregated page text; the same content for the same
    tenant must be deduplicated (idempotency for tunnel-drop retries).
    """
    import rpim_core_api.brain.crawler as _crawler_mod  # noqa: PLC0415

    monkeypatch.setattr(_crawler_mod, "fetch_page", _three_page_stub)

    token = _register(
        client, "crawl-idem@example.com", "Password123!", "CrawlIdem"
    )["access_token"]
    resp1 = _crawl(client, token, _ROOT_URL)
    resp2 = _crawl(client, token, _ROOT_URL)

    assert resp1.status_code == 201, (
        f"first crawl call failed: {resp1.status_code}: {resp1.text}"
    )
    assert resp2.status_code == 201, (
        f"second crawl call failed: {resp2.status_code}: {resp2.text}"
    )
    sid1 = resp1.json()["source_id"]
    sid2 = resp2.json()["source_id"]
    assert sid1 == sid2, (
        f"same URL + same tenant must return the same source_id on second call; "
        f"first={sid1!r}, second={sid2!r}"
    )


# ---------------------------------------------------------------------------
# 6. Cross-tenant isolation (CLAUDE.md rule 6)
# ---------------------------------------------------------------------------


def test_m2_crawl_cross_tenant_isolation(client: TestClient, monkeypatch):
    """Tenant A crawls the marker site; Tenant B's search for the marker must
    return no result containing it.

    Steps
    -----
    1. Tenant A crawls _ROOT_URL (stub: root text contains _MARKER).
    2. Tenant B searches for _MARKER — none of B's results may contain it.
    3. Positive control: Tenant B can upload and find its own source normally.

    This proves that crawl-ingested chunks are scoped by tenant_id and never
    leak across tenant boundaries (CLAUDE.md rule 6).
    """
    import rpim_core_api.brain.crawler as _crawler_mod  # noqa: PLC0415

    monkeypatch.setattr(_crawler_mod, "fetch_page", _three_page_stub)

    # --- Tenant A crawls the marker site ---
    token_a = _register(
        client, "crawl-isol-a@example.com", "Password123!", "CrawlIsolA"
    )["access_token"]
    resp_a = _crawl(client, token_a, _ROOT_URL)
    assert resp_a.status_code == 201, (
        f"Tenant A crawl failed: {resp_a.status_code}: {resp_a.text}"
    )

    # --- Tenant B searches for the marker ---
    token_b = _register(
        client, "crawl-isol-b@example.com", "Password123!", "CrawlIsolB"
    )["access_token"]
    search_resp = client.get(
        "/brain/search",
        params={"q": _MARKER, "k": 5},
        headers=_auth(token_b),
    )
    assert search_resp.status_code == 200, (
        f"Tenant B search failed: {search_resp.status_code}: {search_resp.text}"
    )
    for idx, result in enumerate(search_resp.json()["results"]):
        assert _MARKER not in result["text"], (
            f"Tenant B's result[{idx}] contains Tenant A's crawled marker — "
            f"cross-tenant leak!\nresult text: {result['text']!r}"
        )

    # --- Positive control: Tenant B can find its own uploaded source ---
    b_text = "متن اختصاصی برند ب برای آزمایش ایزولاسیون خزنده وب."
    upload_b = client.post(
        "/brain/sources",
        json={"title": "سند ب", "kind": "upload", "text": b_text},
        headers=_auth(token_b),
    )
    assert upload_b.status_code == 201, (
        f"Tenant B text upload failed: {upload_b.text}"
    )
    search_b_own = client.get(
        "/brain/search",
        params={"q": b_text, "k": 5},
        headers=_auth(token_b),
    )
    assert search_b_own.status_code == 200, search_b_own.text
    b_texts = [r["text"] for r in search_b_own.json()["results"]]
    assert any(b_text in t for t in b_texts), (
        f"Tenant B cannot find its own uploaded source after isolation check.\n"
        f"B's results: {b_texts}"
    )
