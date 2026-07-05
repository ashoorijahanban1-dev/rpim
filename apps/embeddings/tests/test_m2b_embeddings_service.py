"""
M2B acceptance tests — rpim_embeddings FastAPI service.

Contract:
  GET /health → 200 {"status": "ok", "service": "embeddings", "leg": "us"}

  POST /embed
    Header: X-Internal-Token: <value of env INTERNAL_TOKEN>
    Body:   {"texts": ["..."]}
    - Missing or wrong X-Internal-Token → 401
    - Valid token + EMBEDDING_BACKEND=fake → 200
        {"vectors": [[...1024 floats...]], "model": "fake", "dim": 1024}
    - vectors[i] equals rpim_shared.fake_embed(texts[i]) exactly (deterministic)

INTERNAL_TOKEN and EMBEDDING_BACKEND are set at module level (before the app is
imported) exactly as apps/model-gateway/tests/test_m2_embed.py does.

rpim_embeddings is imported LAZILY inside fixtures so that pytest collection of
other suites succeeds even when the package is not yet installed.
"""

from __future__ import annotations

import os
import secrets as _secrets

# Set env vars BEFORE any import of the embeddings app.
os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(16))
os.environ.setdefault("EMBEDDING_BACKEND", "fake")

import pytest
from fastapi.testclient import TestClient

_VALID_TOKEN = os.environ["INTERNAL_TOKEN"]


@pytest.fixture()
def emb_client():
    """TestClient for the rpim_embeddings FastAPI app (lazy import)."""
    from rpim_embeddings.main import app  # noqa: PLC0415

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. Health endpoint
# ---------------------------------------------------------------------------


def test_m2b_embeddings_health_returns_200(emb_client: TestClient):
    """GET /health → 200."""
    resp = emb_client.get("/health")
    assert resp.status_code == 200, (
        f"expected 200 from GET /health, got {resp.status_code}: {resp.text}"
    )


def test_m2b_embeddings_health_body(emb_client: TestClient):
    """GET /health → exact body {"status":"ok","service":"embeddings","leg":"us"}."""
    resp = emb_client.get("/health")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok", "service": "embeddings", "leg": "us"}, (
        f"unexpected health body: {resp.json()}"
    )


# ---------------------------------------------------------------------------
# 2. Authentication guard
# ---------------------------------------------------------------------------


def test_m2b_embeddings_missing_token_returns_401(emb_client: TestClient):
    """POST /embed without X-Internal-Token → 401."""
    resp = emb_client.post("/embed", json={"texts": ["سلام"]})
    assert resp.status_code == 401, (
        f"expected 401 for missing token, got {resp.status_code}: {resp.text}"
    )


def test_m2b_embeddings_wrong_token_returns_401(emb_client: TestClient):
    """POST /embed with wrong X-Internal-Token → 401."""
    resp = emb_client.post(
        "/embed",
        json={"texts": ["سلام"]},
        headers={"X-Internal-Token": "definitely-wrong"},
    )
    assert resp.status_code == 401, (
        f"expected 401 for wrong token, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 3. Successful embed (fake backend)
# ---------------------------------------------------------------------------


def test_m2b_embeddings_valid_token_returns_200(emb_client: TestClient):
    """POST /embed with valid token and EMBEDDING_BACKEND=fake → 200."""
    resp = emb_client.post(
        "/embed",
        json={"texts": ["محصولات با کیفیت برای مشتریان"]},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, (
        f"expected 200 for valid token, got {resp.status_code}: {resp.text}"
    )


def test_m2b_embeddings_response_shape(emb_client: TestClient):
    """200 response has 'vectors' list, 'model'='fake', 'dim'=1024."""
    resp = emb_client.post(
        "/embed",
        json={"texts": ["متن آزمایشی"]},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "vectors" in body, f"'vectors' key missing: {body}"
    assert isinstance(body["vectors"], list), "'vectors' must be a list"
    assert len(body["vectors"]) == 1, f"expected 1 vector for 1 text, got {len(body['vectors'])}"
    assert body.get("model") == "fake", f"expected model='fake', got {body.get('model')!r}"
    assert body.get("dim") == 1024, f"expected dim=1024, got {body.get('dim')!r}"


def test_m2b_embeddings_vector_dim_1024(emb_client: TestClient):
    """Each returned vector must have exactly 1024 dimensions."""
    texts = ["یک", "دو", "سه"]
    resp = emb_client.post(
        "/embed",
        json={"texts": texts},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    vectors = resp.json()["vectors"]
    assert len(vectors) == len(texts), (
        f"expected {len(texts)} vectors, got {len(vectors)}"
    )
    for idx, vec in enumerate(vectors):
        assert len(vec) == 1024, (
            f"vector[{idx}] has {len(vec)} dims; expected 1024"
        )


def test_m2b_embeddings_vectors_match_fake_embed(emb_client: TestClient):
    """vectors[i] must equal rpim_shared.fake_embed(texts[i]) exactly (deterministic)."""
    from rpim_shared import fake_embed  # noqa: PLC0415

    texts = ["برند ایرانی", "محصول با کیفیت", "بازارگردانی هوشمند"]
    resp = emb_client.post(
        "/embed",
        json={"texts": texts},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    vectors = resp.json()["vectors"]
    for i, text in enumerate(texts):
        expected = fake_embed(text)
        assert vectors[i] == pytest.approx(expected, abs=1e-9), (
            f"vector[{i}] does not match fake_embed({text!r})"
        )
