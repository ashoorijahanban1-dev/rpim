"""
M2B acceptance tests — model-gateway forwards non-fake backend embed requests.

When EMBEDDING_BACKEND is not "fake", POST /embed must:
  1. Forward the texts to {EMBEDDINGS_URL}/embed via httpx.post.
  2. Include the X-Internal-Token header in the forwarded request.
  3. Return the embeddings service's JSON verbatim (status 200).
  4. Return 502 if the embeddings service raises httpx.HTTPError.

The implementation will `import httpx` at module level in rpim_model_gateway.main
so that tests can monkeypatch `rpim_model_gateway.main.httpx.post`.
The gateway reads EMBEDDING_BACKEND and EMBEDDINGS_URL per-request (not at import),
so monkeypatch.setenv is sufficient.
"""

from __future__ import annotations

import os
import secrets as _secrets

# INTERNAL_TOKEN must be set before importing the gateway app so the endpoint
# can validate it.  EMBEDDING_BACKEND is overridden per-test via monkeypatch.
os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(16))

import httpx
import pytest
from fastapi.testclient import TestClient

from rpim_model_gateway.main import app

_VALID_TOKEN = os.environ["INTERNAL_TOKEN"]
_EMBEDDINGS_URL = "http://embeddings.test"
_EMBED_ENDPOINT = _EMBEDDINGS_URL + "/embed"
_BODY = {"texts": ["متن برای بازارگردانی هوشمند"], "tenant_id": "tenant-fwd"}


class _StubResponse:
    """Minimal stub for httpx.Response — avoids a real network call."""

    def __init__(self, data: dict) -> None:
        self._data = data

    def json(self) -> dict:
        return self._data

    def raise_for_status(self) -> None:
        pass  # no error


@pytest.fixture()
def gw_fwd_client(monkeypatch):
    """TestClient with EMBEDDING_BACKEND=bge-m3 and EMBEDDINGS_URL set."""
    monkeypatch.setenv("EMBEDDING_BACKEND", "bge-m3")
    monkeypatch.setenv("EMBEDDINGS_URL", _EMBEDDINGS_URL)
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. Forwarded URL is EMBEDDINGS_URL + "/embed"
# ---------------------------------------------------------------------------


def test_m2b_forward_calls_embeddings_url(monkeypatch, gw_fwd_client: TestClient):
    """Gateway must POST to {EMBEDDINGS_URL}/embed — not any other URL."""
    captured: dict = {}
    stub_payload = {"vectors": [[0.1] * 1024], "model": "bge-m3", "dim": 1024}

    def fake_post(url, **kwargs):
        captured["url"] = url
        return _StubResponse(stub_payload)

    monkeypatch.setattr("rpim_model_gateway.main.httpx.post", fake_post)

    resp = gw_fwd_client.post(
        "/embed", json=_BODY, headers={"X-Internal-Token": _VALID_TOKEN}
    )
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    assert captured.get("url") == _EMBED_ENDPOINT, (
        f"expected forwarded URL {_EMBED_ENDPOINT!r}, got {captured.get('url')!r}"
    )


# ---------------------------------------------------------------------------
# 2. X-Internal-Token is forwarded to the embeddings service
# ---------------------------------------------------------------------------


def test_m2b_forward_passes_internal_token(monkeypatch, gw_fwd_client: TestClient):
    """X-Internal-Token must be forwarded in the httpx.post headers."""
    captured: dict = {}
    stub_payload = {"vectors": [[0.2] * 1024], "model": "bge-m3", "dim": 1024}

    def fake_post(url, *, headers=None, **kwargs):
        captured["headers"] = dict(headers or {})
        return _StubResponse(stub_payload)

    monkeypatch.setattr("rpim_model_gateway.main.httpx.post", fake_post)

    resp = gw_fwd_client.post(
        "/embed", json=_BODY, headers={"X-Internal-Token": _VALID_TOKEN}
    )
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    assert captured.get("headers", {}).get("X-Internal-Token") == _VALID_TOKEN, (
        f"X-Internal-Token not forwarded; captured headers: {captured.get('headers')}"
    )


# ---------------------------------------------------------------------------
# 3. Embeddings service response flows through verbatim
# ---------------------------------------------------------------------------


def test_m2b_forward_response_flows_through(monkeypatch, gw_fwd_client: TestClient):
    """Gateway must return the embeddings service's JSON body unchanged."""
    service_payload = {"vectors": [[0.3] * 1024], "model": "bge-m3", "dim": 1024}

    def fake_post(url, **kwargs):
        return _StubResponse(service_payload)

    monkeypatch.setattr("rpim_model_gateway.main.httpx.post", fake_post)

    resp = gw_fwd_client.post(
        "/embed", json=_BODY, headers={"X-Internal-Token": _VALID_TOKEN}
    )
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json() == service_payload, (
        f"expected verbatim payload {service_payload!r}, got {resp.json()!r}"
    )


# ---------------------------------------------------------------------------
# 4. Forwarding failure → 502
# ---------------------------------------------------------------------------


def test_m2b_forward_http_error_returns_502(monkeypatch, gw_fwd_client: TestClient):
    """If the embeddings service raises httpx.HTTPError, gateway must return 502."""

    def fake_post(url, **kwargs):
        raise httpx.HTTPError("connection refused to embeddings service")

    monkeypatch.setattr("rpim_model_gateway.main.httpx.post", fake_post)

    resp = gw_fwd_client.post(
        "/embed", json=_BODY, headers={"X-Internal-Token": _VALID_TOKEN}
    )
    assert resp.status_code == 502, (
        f"expected 502 for httpx.HTTPError from embeddings service, "
        f"got {resp.status_code}: {resp.text}"
    )
