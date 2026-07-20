"""
M21 acceptance tests (gateway slice) — IMAGE_PROVIDERS + POST /image.

Contract (design §3.2, mirrors the M17 text-provider pattern):
  - IMAGE_PROVIDERS registry: fake | openai (DALL-E-style images/generations)
    | gemini (Imagen predict) — one shared signature
    (model, prompt, size, timeout) → {"image_b64": ..., "units": 1}.
  - Chain env MODEL_IMG="provider:model" + MODEL_IMG_FALLBACKS — swapping
    image backends is an env change, zero logic edits; a link missing its
    key falls through to the next link.
  - POST /image {prompt, size?, tenant_id?, request_id?} (X-Internal-Token):
    200 → {image_b64, sha256, provider, model, units, cost_usd}; every call
    books ledger task="image", units=1, cost=IMAGE_PRICES.get(model, 0.0)
    (unknown models cost 0 — the established PRICES convention).
  - Idempotency stores a LIGHTWEIGHT RECEIPT, never the image bytes (OOM
    prevention on the single US VPS): the cached replay answers
    {cached: true, sha256, ...} WITHOUT image_b64 and books NO second
    ledger charge.

All tests named test_m21_<criterion>.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(16))

from rpim_model_gateway import image_providers
from rpim_model_gateway.main import app

_VALID_TOKEN = os.environ["INTERNAL_TOKEN"]


@pytest.fixture()
def gw_client(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("MODEL_IMG", "fake:echo-img")
    monkeypatch.delenv("MODEL_IMG_FALLBACKS", raising=False)
    from rpim_model_gateway import idempotency  # noqa: PLC0415

    idempotency._MEMORY.clear()
    with TestClient(app) as c:
        yield c
    idempotency._MEMORY.clear()


def _post_image(client: TestClient, **overrides) -> object:
    payload = {"prompt": "پس‌زمینه مینیمال برای پکیج دزدگیر", "tenant_id": "ten-img"}
    payload.update(overrides)
    return client.post(
        "/image", json=payload, headers={"X-Internal-Token": _VALID_TOKEN}
    )


# ===========================================================================
# 1. Registry + adapters
# ===========================================================================


def test_m21_registry_members():
    assert {"fake", "openai", "gemini"} <= set(image_providers.IMAGE_PROVIDERS), (
        sorted(image_providers.IMAGE_PROVIDERS)
    )


def test_m21_fake_is_deterministic():
    a = image_providers.IMAGE_PROVIDERS["fake"]("echo-img", "متن ثابت")
    b = image_providers.IMAGE_PROVIDERS["fake"]("echo-img", "متن ثابت")
    c = image_providers.IMAGE_PROVIDERS["fake"]("echo-img", "متن دیگر")
    assert a["image_b64"] == b["image_b64"] and a["units"] == 1
    assert a["image_b64"] != c["image_b64"]


def test_m21_openai_adapter_wire_format(monkeypatch):
    import httpx  # noqa: PLC0415

    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": base64.b64encode(b"png-bytes").decode()}]}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured.update(url=url, json=json, headers=headers)
        return _Resp()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-img-not-real")
    monkeypatch.setattr(httpx, "post", fake_post)
    out = image_providers.IMAGE_PROVIDERS["openai"]("dall-e-3", "prompt", size="1024x1024")
    assert captured["url"] == "https://api.openai.com/v1/images/generations"
    assert captured["headers"]["Authorization"] == "Bearer sk-img-not-real"
    assert "sk-img-not-real" not in captured["url"], "key never in the URL (rule 4)"
    assert captured["json"]["model"] == "dall-e-3"
    assert captured["json"]["response_format"] == "b64_json"
    assert out == {"image_b64": base64.b64encode(b"png-bytes").decode(), "units": 1}


def test_m21_openai_missing_key_raises_provider_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(image_providers.ImageProviderError) as excinfo:
        image_providers.IMAGE_PROVIDERS["openai"]("dall-e-3", "p")
    assert "OPENAI_API_KEY" in str(excinfo.value)


def test_m21_gemini_missing_key_raises_provider_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(image_providers.ImageProviderError):
        image_providers.IMAGE_PROVIDERS["gemini"]("imagen-3.0-generate-002", "p")


# ===========================================================================
# 2. /image route — chain, auth, ledger, costs
# ===========================================================================


def test_m21_image_requires_internal_token(gw_client: TestClient):
    resp = gw_client.post("/image", json={"prompt": "x"})
    assert resp.status_code == 401


def test_m21_image_serves_via_chain_with_receipt_fields(gw_client: TestClient):
    resp = _post_image(gw_client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "fake" and body["model"] == "echo-img"
    raw = base64.b64decode(body["image_b64"])
    assert body["sha256"] == hashlib.sha256(raw).hexdigest()
    assert body["units"] == 1 and body["cost_usd"] == 0.0, body


def test_m21_broken_primary_falls_through(gw_client: TestClient, monkeypatch):
    monkeypatch.setenv("MODEL_IMG", "openai:dall-e-3")  # no key set → dead link
    monkeypatch.setenv("MODEL_IMG_FALLBACKS", "fake:echo-img")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resp = _post_image(gw_client)
    assert resp.status_code == 200, resp.text
    assert resp.json()["provider"] == "fake"


def test_m21_all_links_dead_returns_503(gw_client: TestClient, monkeypatch):
    monkeypatch.setenv("MODEL_IMG", "openai:dall-e-3")
    monkeypatch.setenv("MODEL_IMG_FALLBACKS", "gemini:imagen-3.0-generate-002")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert _post_image(gw_client).status_code == 503


def test_m21_ledger_books_image_units(gw_client: TestClient):
    from rpim_model_gateway.ledger import _MEMORY as LEDGER  # noqa: PLC0415

    before = sum(1 for e in LEDGER if e["tenant_id"] == "ten-img-ledger")
    resp = _post_image(gw_client, tenant_id="ten-img-ledger")
    assert resp.status_code == 200
    entries = [e for e in LEDGER if e["tenant_id"] == "ten-img-ledger"]
    assert len(entries) == before + 1
    assert entries[-1]["task"] == "image" and entries[-1]["units"] == 1


def test_m21_known_model_priced_unknown_costs_zero():
    assert image_providers.IMAGE_PRICES.get("dall-e-3", 0.0) > 0.0
    assert image_providers.IMAGE_PRICES.get("no-such-model", 0.0) == 0.0


# ===========================================================================
# 3. Idempotency — lightweight receipt, never bytes (OOM prevention)
# ===========================================================================


def test_m21_replay_returns_receipt_without_bytes_or_second_charge(
    gw_client: TestClient,
):
    from rpim_model_gateway import idempotency  # noqa: PLC0415
    from rpim_model_gateway.ledger import _MEMORY as LEDGER  # noqa: PLC0415

    first = _post_image(gw_client, tenant_id="ten-idem-img", request_id="img-req-1")
    assert first.status_code == 200, first.text
    charges = sum(
        1 for e in LEDGER if e["tenant_id"] == "ten-idem-img" and e["task"] == "image"
    )

    second = _post_image(gw_client, tenant_id="ten-idem-img", request_id="img-req-1")
    assert second.status_code == 200, second.text
    body = second.json()
    assert body.get("cached") is True, body
    assert "image_b64" not in body or not body["image_b64"], (
        "replay must serve the lightweight receipt, not bytes"
    )
    assert body["sha256"] == first.json()["sha256"]
    assert (
        sum(1 for e in LEDGER if e["tenant_id"] == "ten-idem-img" and e["task"] == "image")
        == charges
    ), "no double charge on replay"

    for cached in idempotency._MEMORY.values():
        assert "image_b64" not in cached, (
            "the idempotency cache must NEVER hold image bytes (OOM prevention)"
        )
