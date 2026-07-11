"""
M2 PDF ingestion acceptance tests.

Route under test:
  POST /brain/sources/pdf — multipart upload
    Fields: file (UploadFile, field name "file"), title (form field)
    Auth: Bearer token (same as other brain routes)

Acceptance criteria (verbatim from milestone contract):
  1. Valid PDF with extractable text → 201 {"source_id": ..., "chunks": >=1};
     a subsequent GET /brain/search?q=<text from the pdf>&k=5 (same tenant)
     returns a top result containing that text.
  2. Unauthenticated → 401.
  3. Non-PDF upload (e.g. b"not a pdf at all") → 422.
  4. PDF whose pages contain NO extractable text → 422 (empty text).

EMBED_MODE=fake is set at module level — same established pattern as
test_m2_brain.py — so the implementation uses rpim_shared.fake_embed locally
with no network calls.

All new tests fail with 404/405 (route does not exist yet).  The existing
suite (76 tests) remains green.
"""

from __future__ import annotations

import os

# Must be set BEFORE any import of rpim_core_api.brain so the implementation
# uses the deterministic fake embedder, not the real model-gateway.
os.environ.setdefault("EMBED_MODE", "fake")

from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# PDF byte fixtures — hand-written minimal valid single-page PDFs
# ---------------------------------------------------------------------------


def _make_minimal_pdf() -> bytes:
    """Build a minimal single-page PDF whose content stream contains extractable
    ASCII text via the classic BT...ET operator block.

    pypdf can extract "Hello RPIM brain PDF" from this document deterministically.
    We do NOT import pypdf in the tests (see task contract); the assertion that
    text was extracted is done indirectly via chunks >= 1 in the upload response.
    """
    header = b"%PDF-1.4\n"

    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\n"
        b"endobj\n"
    )
    # Content stream: BT /F1 24 Tf 72 720 Td (Hello RPIM brain PDF) Tj ET
    content_stream = b"BT /F1 24 Tf 72 720 Td (Hello RPIM brain PDF) Tj ET\n"
    obj4 = (
        b"4 0 obj\n<< /Length "
        + str(len(content_stream)).encode()
        + b" >>\nstream\n"
        + content_stream
        + b"endstream\nendobj\n"
    )
    # Helvetica font object — standard Type1, no encoding stream needed.
    obj5 = (
        b"5 0 obj\n"
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
        b"endobj\n"
    )

    # Compute xref byte offsets.
    off1 = len(header)
    off2 = off1 + len(obj1)
    off3 = off2 + len(obj2)
    off4 = off3 + len(obj3)
    off5 = off4 + len(obj4)
    xref_pos = off5 + len(obj5)

    xref = (
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        + f"{off1:010d} 00000 n \n".encode()
        + f"{off2:010d} 00000 n \n".encode()
        + f"{off3:010d} 00000 n \n".encode()
        + f"{off4:010d} 00000 n \n".encode()
        + f"{off5:010d} 00000 n \n".encode()
    )
    trailer = (
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )

    return header + obj1 + obj2 + obj3 + obj4 + obj5 + xref + trailer


def _make_empty_text_pdf() -> bytes:
    """Build a minimal single-page PDF whose content stream contains no text
    operators — pypdf extracts an empty string from every page.

    The implementation must detect the empty extraction result and return 422.
    """
    header = b"%PDF-1.4\n"

    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        b"   /Contents 4 0 R /Resources << >> >>\n"
        b"endobj\n"
    )
    # Empty content stream — no text operators.
    obj4 = b"4 0 obj\n<< /Length 0 >>\nstream\nendstream\nendobj\n"

    off1 = len(header)
    off2 = off1 + len(obj1)
    off3 = off2 + len(obj2)
    off4 = off3 + len(obj3)
    xref_pos = off4 + len(obj4)

    xref = (
        b"xref\n0 5\n"
        b"0000000000 65535 f \n"
        + f"{off1:010d} 00000 n \n".encode()
        + f"{off2:010d} 00000 n \n".encode()
        + f"{off3:010d} 00000 n \n".encode()
        + f"{off4:010d} 00000 n \n".encode()
    )
    trailer = (
        b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )

    return header + obj1 + obj2 + obj3 + obj4 + xref + trailer


# Build once at import time — shared across all tests in this module.
_VALID_PDF: bytes = _make_minimal_pdf()
_EMPTY_TEXT_PDF: bytes = _make_empty_text_pdf()
_NON_PDF: bytes = b"not a pdf at all"

# The exact text embedded in _VALID_PDF's content stream.
_PDF_TEXT = "Hello RPIM brain PDF"


# ---------------------------------------------------------------------------
# Helpers (mirrors the register-helper pattern from test_m2_brain.py)
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


def _upload_pdf(
    client: TestClient,
    token: str | None,
    pdf_bytes: bytes,
    *,
    filename: str = "doc.pdf",
    content_type: str = "application/pdf",
    title: str = "کاتالوگ PDF",
) -> object:
    """POST multipart to /brain/sources/pdf, optionally with Bearer auth."""
    headers = _auth(token) if token is not None else {}
    return client.post(
        "/brain/sources/pdf",
        files={"file": (filename, pdf_bytes, content_type)},
        data={"title": title},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# 1. Valid PDF — upload + search round-trip
# ---------------------------------------------------------------------------


def test_m2_pdf_valid_pdf_returns_201(client: TestClient):
    """Valid PDF with extractable text → 201."""
    token = _register(client, "pdf1@example.com", "password1!", "PdfBrand1")["access_token"]
    resp = _upload_pdf(client, token, _VALID_PDF)
    assert resp.status_code == 201, (
        f"expected 201 from POST /brain/sources/pdf, got {resp.status_code}: {resp.text}"
    )


def test_m2_pdf_response_has_source_id_and_chunks_gte_1(client: TestClient):
    """201 response must have a non-empty source_id and chunks >= 1."""
    token = _register(client, "pdf2@example.com", "password2!", "PdfBrand2")["access_token"]
    resp = _upload_pdf(client, token, _VALID_PDF)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "source_id" in body, f"'source_id' missing from response: {body}"
    assert body["source_id"], "'source_id' must be non-empty"
    assert "chunks" in body, f"'chunks' missing from response: {body}"
    assert isinstance(body["chunks"], int), (
        f"'chunks' must be int, got {type(body['chunks'])}"
    )
    assert body["chunks"] >= 1, f"'chunks' must be >= 1, got {body['chunks']}"


def test_m2_pdf_search_finds_pdf_text(client: TestClient):
    """After uploading a valid PDF, GET /brain/search returns a top result
    containing the text extracted from the PDF.

    _PDF_TEXT ("Hello RPIM brain PDF") fits in a single chunk.
    fake_embed produces the same vector for identical text, so cosine
    similarity == 1.0 guarantees it ranks first.
    """
    token = _register(client, "pdf3@example.com", "password3!", "PdfBrand3")["access_token"]
    upload_resp = _upload_pdf(client, token, _VALID_PDF)
    assert upload_resp.status_code == 201, f"upload failed: {upload_resp.text}"

    search_resp = client.get(
        "/brain/search",
        params={"q": _PDF_TEXT, "k": 5},
        headers=_auth(token),
    )
    assert search_resp.status_code == 200, (
        f"expected 200 from GET /brain/search, got "
        f"{search_resp.status_code}: {search_resp.text}"
    )
    results = search_resp.json()["results"]
    assert len(results) >= 1, "must return at least 1 result after uploading PDF"
    top = results[0]
    assert _PDF_TEXT in top["text"], (
        f"top result text must contain the PDF text.\n"
        f"expected to find: {_PDF_TEXT!r}\n"
        f"top result text: {top['text']!r}"
    )


# ---------------------------------------------------------------------------
# 2. Unauthenticated request → 401
# ---------------------------------------------------------------------------


def test_m2_pdf_unauthenticated_returns_401(client: TestClient):
    """POST /brain/sources/pdf without Authorization → 401."""
    resp = _upload_pdf(client, None, _VALID_PDF)
    assert resp.status_code == 401, (
        f"expected 401 for unauthenticated PDF upload, got {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# 3. Non-PDF upload → 422
# ---------------------------------------------------------------------------


def test_m2_pdf_non_pdf_returns_422(client: TestClient):
    """Uploading bytes that are not a PDF → 422.

    The client declares content-type application/pdf; the implementation must
    validate the actual file bytes (not just trust the declared MIME type) and
    return 422 when the content is not a valid PDF.
    """
    token = _register(client, "pdf5@example.com", "password5!", "PdfBrand5")["access_token"]
    resp = _upload_pdf(client, token, _NON_PDF, content_type="application/pdf")
    assert resp.status_code == 422, (
        f"expected 422 for non-PDF upload, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 4. PDF with no extractable text → 422
# ---------------------------------------------------------------------------


def test_m2_pdf_empty_text_pdf_returns_422(client: TestClient):
    """PDF whose pages contain NO extractable text → 422 (empty text).

    _EMPTY_TEXT_PDF is a structurally valid PDF whose content stream contains
    no text operators.  The implementation must extract text, find it empty,
    and return 422.
    """
    token = _register(client, "pdf6@example.com", "password6!", "PdfBrand6")["access_token"]
    resp = _upload_pdf(client, token, _EMPTY_TEXT_PDF)
    assert resp.status_code == 422, (
        f"expected 422 for PDF with no extractable text, "
        f"got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 5. Cross-tenant isolation (CLAUDE.md rule 6)
#    The PDF ingestion path stores content via the same tenant-scoped tables;
#    this test verifies the PDF upload path does not introduce any cross-tenant
#    data leakage.
# ---------------------------------------------------------------------------


def test_m2_pdf_cross_tenant_isolation(client: TestClient):
    """Tenant B must not see Tenant A's PDF content in search results.

    Steps:
    1. Tenant A uploads the valid PDF (text = _PDF_TEXT).
    2. Tenant B searches for _PDF_TEXT — must get zero results containing it.
    3. Positive control: Tenant B uploads its own source and finds it normally.

    This proves the PDF ingestion path scopes stored chunks by tenant_id.
    """
    # Tenant A uploads the PDF.
    token_a = _register(
        client, "pdf-isol-a@example.com", "passwordA1!", "PdfIsolA"
    )["access_token"]
    resp_a = _upload_pdf(client, token_a, _VALID_PDF, title="سند الف PDF")
    assert resp_a.status_code == 201, f"Tenant A PDF upload failed: {resp_a.text}"

    # Tenant B searches for the same text.
    token_b = _register(
        client, "pdf-isol-b@example.com", "passwordB1!", "PdfIsolB"
    )["access_token"]
    search_resp = client.get(
        "/brain/search",
        params={"q": _PDF_TEXT, "k": 5},
        headers=_auth(token_b),
    )
    assert search_resp.status_code == 200, (
        f"Tenant B search failed: {search_resp.status_code}: {search_resp.text}"
    )
    for idx, result in enumerate(search_resp.json()["results"]):
        assert _PDF_TEXT not in result["text"], (
            f"Tenant B's result[{idx}] contains Tenant A's PDF text — "
            f"cross-tenant leak!\nresult text: {result['text']!r}"
        )

    # Positive control: Tenant B can find its own text source.
    b_text = "متن اختصاصی برند ب برای آزمایش ایزولاسیون PDF."
    upload_b = client.post(
        "/brain/sources",
        json={"title": "سند ب", "kind": "upload", "text": b_text},
        headers=_auth(token_b),
    )
    assert upload_b.status_code == 201, f"Tenant B text upload failed: {upload_b.text}"
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


# ---------------------------------------------------------------------------
# 7. Robustness — encrypted PDFs must be a clean 422, never a 500
#    (production incident: user uploads failed with a generic 500)
# ---------------------------------------------------------------------------


def test_m2_pdf_password_protected_returns_422(client: TestClient):
    """A password-protected PDF → 422 whose detail names the password problem."""
    import io  # noqa: PLC0415

    from pypdf import PdfReader, PdfWriter  # noqa: PLC0415

    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(_VALID_PDF)))
    writer.encrypt("owner-secret")
    buf = io.BytesIO()
    writer.write(buf)

    token = _register(client, "pdf-enc@example.com", "password1!", "PdfEnc")["access_token"]
    resp = _upload_pdf(client, token, buf.getvalue())
    assert resp.status_code == 422, (
        f"encrypted PDF must be a 422, got {resp.status_code}: {resp.text}"
    )
    assert "password" in resp.json()["detail"].lower(), (
        f"detail must name the password problem: {resp.json()}"
    )
