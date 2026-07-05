"""
M2 acceptance tests — model-gateway POST /embed endpoint.

Contract:
  POST /embed
    Header: X-Internal-Token: <value of env INTERNAL_TOKEN>
    Body:   {"texts": ["..."], "tenant_id": "..."}

  - Missing or wrong X-Internal-Token → 401
  - Correct token → 200 {"vectors": [[...1024 floats...]], "model": "fake", "dim": 1024}
  - Uses EMBEDDING_BACKEND=fake (default) — no real model required

INTERNAL_TOKEN is set in os.environ at module level (before the app import) so
that the implementation reads the correct secret from the environment at
request time, not at import time.

These tests FAIL until the /embed route is implemented in the gateway.
"""

from __future__ import annotations

import os

# Set env vars BEFORE any import of the gateway app so that when the
# implementation reads them (at request time or startup), they are present.
import secrets as _secrets

# Generated per test run — no secret literal in the repo (CLAUDE.md rule 4).
os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(16))
os.environ.setdefault("EMBEDDING_BACKEND", "fake")

import pytest
from fastapi.testclient import TestClient

from rpim_model_gateway.main import app

_VALID_TOKEN = os.environ["INTERNAL_TOKEN"]
_EMBED_URL = "/embed"
_BODY = {"texts": ["محصولات با کیفیت برای مشتریان"], "tenant_id": "tenant-abc"}


@pytest.fixture()
def gw_client():
    """TestClient for the model-gateway app."""
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. Authentication guard
# ---------------------------------------------------------------------------


def test_m2_embed_missing_token_returns_401(gw_client: TestClient):
    """POST /embed without X-Internal-Token header → 401."""
    resp = gw_client.post(_EMBED_URL, json=_BODY)
    assert resp.status_code == 401, (
        f"expected 401 for missing token, got {resp.status_code}: {resp.text}"
    )


def test_m2_embed_wrong_token_returns_401(gw_client: TestClient):
    """POST /embed with an incorrect X-Internal-Token → 401."""
    resp = gw_client.post(
        _EMBED_URL,
        json=_BODY,
        headers={"X-Internal-Token": "definitely-wrong-secret"},
    )
    assert resp.status_code == 401, (
        f"expected 401 for wrong token, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 2. Successful embed request (fake backend)
# ---------------------------------------------------------------------------


def test_m2_embed_valid_token_returns_200(gw_client: TestClient):
    """POST /embed with the correct token → 200."""
    resp = gw_client.post(
        _EMBED_URL,
        json=_BODY,
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, (
        f"expected 200 for valid token, got {resp.status_code}: {resp.text}"
    )


def test_m2_embed_response_contains_vectors(gw_client: TestClient):
    """200 response body must contain 'vectors' key with a list of vector lists."""
    resp = gw_client.post(
        _EMBED_URL,
        json=_BODY,
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "vectors" in body, f"'vectors' key missing from response: {body}"
    assert isinstance(body["vectors"], list), "'vectors' must be a list"
    assert len(body["vectors"]) == len(_BODY["texts"]), (
        f"number of vectors ({len(body['vectors'])}) must match number of input texts "
        f"({len(_BODY['texts'])})"
    )


def test_m2_embed_vector_dim_is_1024(gw_client: TestClient):
    """Each vector in the response must have exactly 1024 dimensions."""
    resp = gw_client.post(
        _EMBED_URL,
        json=_BODY,
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for idx, vec in enumerate(body["vectors"]):
        assert len(vec) == 1024, (
            f"vector[{idx}] has {len(vec)} dims; expected 1024"
        )


def test_m2_embed_response_model_and_dim_fields(gw_client: TestClient):
    """Response must include 'model': 'fake' and 'dim': 1024."""
    resp = gw_client.post(
        _EMBED_URL,
        json=_BODY,
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("model") == "fake", (
        f"expected model='fake', got model={body.get('model')!r}"
    )
    assert body.get("dim") == 1024, (
        f"expected dim=1024, got dim={body.get('dim')!r}"
    )


def test_m2_embed_multiple_texts_returns_multiple_vectors(gw_client: TestClient):
    """Batch of N texts → N vectors in the response."""
    texts = [
        "اولین متن برای آزمایش دسته‌ای",
        "دومین متن با محتوای متفاوت",
        "سومین متن برای تکمیل آزمون",
    ]
    resp = gw_client.post(
        _EMBED_URL,
        json={"texts": texts, "tenant_id": "tenant-batch"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["vectors"]) == 3, (
        f"expected 3 vectors for 3 input texts, got {len(body['vectors'])}"
    )
