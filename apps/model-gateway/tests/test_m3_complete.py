"""
M3 acceptance tests — model-gateway POST /complete endpoint and GET /ledger.

These tests encode the milestone acceptance criteria verbatim. They FAIL until
the implementation is in place (routes return 404 now).

Contract:
  POST /complete
    Header: X-Internal-Token: <INTERNAL_TOKEN>
    Body:   {"task": "t1"|"t2", "prompt": str, "system": str|null,
             "tenant_id": str|null, "max_tokens": int|null}
  GET /ledger/{tenant_id}
    Header: X-Internal-Token: <INTERNAL_TOKEN>

Env vars read per-request (use monkeypatch.setenv inside tests):
  MODEL_T1          — primary provider:model string (e.g. "fake:echo")
  MODEL_T1_FALLBACKS — comma-separated fallback chain (e.g. "fake:echo")
  MODEL_T2          — provider:model for T2 tasks (unset = pending eval)

INTERNAL_TOKEN is set at module level before any gateway import (pattern
from test_m2_embed.py) so the app reads the correct secret at request time.
"""

from __future__ import annotations

import os
import secrets as _secrets

# Set INTERNAL_TOKEN before importing the gateway app (CLAUDE.md pattern).
os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(16))

import pytest
from fastapi.testclient import TestClient

from rpim_model_gateway.main import app

_VALID_TOKEN = os.environ["INTERNAL_TOKEN"]
_COMPLETE_URL = "/complete"

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def gw_client():
    """TestClient for the model-gateway app."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def gw_t1_fake(monkeypatch, gw_client):
    """Client with MODEL_T1=fake:echo so the fake provider handles t1 tasks."""
    monkeypatch.setenv("MODEL_T1", "fake:echo")
    monkeypatch.delenv("MODEL_T1_FALLBACKS", raising=False)
    return gw_client


# ---------------------------------------------------------------------------
# 1. Authentication guard on POST /complete
# ---------------------------------------------------------------------------


def test_m3_auth_missing_token_returns_401(gw_client: TestClient, monkeypatch):
    """POST /complete without X-Internal-Token → 401."""
    monkeypatch.setenv("MODEL_T1", "fake:echo")
    resp = gw_client.post(
        _COMPLETE_URL,
        json={"task": "t1", "prompt": "سلام"},
    )
    assert resp.status_code == 401, (
        f"expected 401 for missing token, got {resp.status_code}: {resp.text}"
    )


def test_m3_auth_wrong_token_returns_401(gw_client: TestClient, monkeypatch):
    """POST /complete with an incorrect X-Internal-Token → 401."""
    monkeypatch.setenv("MODEL_T1", "fake:echo")
    resp = gw_client.post(
        _COMPLETE_URL,
        json={"task": "t1", "prompt": "سلام"},
        headers={"X-Internal-Token": "definitely-wrong-secret"},
    )
    assert resp.status_code == 401, (
        f"expected 401 for wrong token, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 2. Successful t1 completion via fake provider
# ---------------------------------------------------------------------------


def test_m3_t1_fake_returns_200(gw_t1_fake: TestClient):
    """task=t1 with MODEL_T1=fake:echo → 200."""
    resp = gw_t1_fake.post(
        _COMPLETE_URL,
        json={"task": "t1", "prompt": "محصولات با کیفیت"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, (
        f"expected 200, got {resp.status_code}: {resp.text}"
    )


def test_m3_t1_fake_response_shape(gw_t1_fake: TestClient):
    """200 response must include text (non-empty), provider, model, tokens_in>0,
    tokens_out>0, cost_usd>=0."""
    resp = gw_t1_fake.post(
        _COMPLETE_URL,
        json={"task": "t1", "prompt": "محصولات با کیفیت"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "text" in body, f"'text' key missing: {body}"
    assert isinstance(body["text"], str) and body["text"], (
        f"'text' must be a non-empty string, got {body['text']!r}"
    )
    assert body.get("provider") == "fake", (
        f"expected provider='fake', got {body.get('provider')!r}"
    )
    assert body.get("model") == "echo", (
        f"expected model='echo', got {body.get('model')!r}"
    )
    assert isinstance(body.get("tokens_in"), int) and body["tokens_in"] > 0, (
        f"tokens_in must be int >0, got {body.get('tokens_in')!r}"
    )
    assert isinstance(body.get("tokens_out"), int) and body["tokens_out"] > 0, (
        f"tokens_out must be int >0, got {body.get('tokens_out')!r}"
    )
    assert isinstance(body.get("cost_usd"), (int, float)) and body["cost_usd"] >= 0.0, (
        f"cost_usd must be float >=0, got {body.get('cost_usd')!r}"
    )


def test_m3_t1_fake_deterministic(gw_t1_fake: TestClient):
    """Fake provider is deterministic: same prompt → same text."""
    payload = {"task": "t1", "prompt": "برند ما بهترین است"}
    headers = {"X-Internal-Token": _VALID_TOKEN}
    r1 = gw_t1_fake.post(_COMPLETE_URL, json=payload, headers=headers)
    r2 = gw_t1_fake.post(_COMPLETE_URL, json=payload, headers=headers)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json()["text"] == r2.json()["text"], (
        "fake provider must be deterministic: same prompt must yield same text"
    )


# ---------------------------------------------------------------------------
# 3. Fallback acceptance test
# ---------------------------------------------------------------------------


def test_m3_fallback_primary_broken_fallback_serves(gw_client: TestClient, monkeypatch):
    """Primary provider unknown → fallback (fake:echo) serves with 200 and
    provider=='fake'. The user sees NO error (blueprint §6.4 fallback chain)."""
    monkeypatch.setenv("MODEL_T1", "nosuchprovider:x")
    monkeypatch.setenv("MODEL_T1_FALLBACKS", "fake:echo")

    resp = gw_client.post(
        _COMPLETE_URL,
        json={"task": "t1", "prompt": "تست فالبک"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, (
        f"expected 200 from fallback, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body.get("provider") == "fake", (
        f"expected fallback provider='fake', got {body.get('provider')!r}"
    )


# ---------------------------------------------------------------------------
# 4. All links fail → 503
# ---------------------------------------------------------------------------


def test_m3_all_providers_fail_returns_503(gw_client: TestClient, monkeypatch):
    """When both primary and all fallbacks are unknown providers → 503."""
    monkeypatch.setenv("MODEL_T1", "nosuch:x")
    monkeypatch.setenv("MODEL_T1_FALLBACKS", "alsonone:y")

    resp = gw_client.post(
        _COMPLETE_URL,
        json={"task": "t1", "prompt": "همه ارائه‌دهندگان شکست خوردند"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 503, (
        f"expected 503 when all providers fail, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 5. task=t2 with MODEL_T2 unset → 503 mentioning pending eval
# ---------------------------------------------------------------------------


def test_m3_t2_model_unset_returns_503_with_eval_message(
    gw_client: TestClient, monkeypatch
):
    """task=t2 with MODEL_T2 unset → 503; detail must mention 'eval'
    (Persian eval gate from CLAUDE.md: MODEL_T2 stays unset until eval done)."""
    monkeypatch.delenv("MODEL_T2", raising=False)

    resp = gw_client.post(
        _COMPLETE_URL,
        json={"task": "t2", "prompt": "محتوای تیر دو"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 503, (
        f"expected 503 when MODEL_T2 unset, got {resp.status_code}: {resp.text}"
    )
    detail = resp.json().get("detail", "")
    assert "eval" in detail.lower(), (
        f"503 detail must mention 'eval' (pending Persian eval gate), got: {detail!r}"
    )


def test_m3_t2_model_empty_returns_503_with_eval_message(
    gw_client: TestClient, monkeypatch
):
    """task=t2 with MODEL_T2='' → 503; detail must mention 'eval'."""
    monkeypatch.setenv("MODEL_T2", "")

    resp = gw_client.post(
        _COMPLETE_URL,
        json={"task": "t2", "prompt": "محتوای تیر دو"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 503, (
        f"expected 503 when MODEL_T2='', got {resp.status_code}: {resp.text}"
    )
    detail = resp.json().get("detail", "")
    assert "eval" in detail.lower(), (
        f"503 detail must mention 'eval' (pending Persian eval gate), got: {detail!r}"
    )


# ---------------------------------------------------------------------------
# 6. Ledger — GET /ledger/{tenant_id} authentication guard
# ---------------------------------------------------------------------------


def test_m3_ledger_missing_token_returns_401(gw_client: TestClient):
    """GET /ledger/{tenant_id} without X-Internal-Token → 401."""
    resp = gw_client.get("/ledger/ten-abc")
    assert resp.status_code == 401, (
        f"expected 401 for missing token on /ledger, got {resp.status_code}: {resp.text}"
    )


def test_m3_ledger_wrong_token_returns_401(gw_client: TestClient):
    """GET /ledger/{tenant_id} with wrong token → 401."""
    resp = gw_client.get(
        "/ledger/ten-abc",
        headers={"X-Internal-Token": "wrong-token"},
    )
    assert resp.status_code == 401, (
        f"expected 401 for wrong token on /ledger, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 7. Ledger — shape and cost recording
# ---------------------------------------------------------------------------


def test_m3_ledger_returns_200_shape(gw_client: TestClient, monkeypatch):
    """GET /ledger/{tenant_id} with correct token → 200 with entries list and
    total_cost_usd float."""
    monkeypatch.setenv("MODEL_T1", "fake:echo")
    monkeypatch.delenv("MODEL_T1_FALLBACKS", raising=False)

    resp = gw_client.get(
        "/ledger/ten-shape-test",
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, (
        f"expected 200 on /ledger, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert "entries" in body, f"'entries' key missing from ledger response: {body}"
    assert isinstance(body["entries"], list), "'entries' must be a list"
    assert "total_cost_usd" in body, (
        f"'total_cost_usd' key missing from ledger response: {body}"
    )
    assert isinstance(body["total_cost_usd"], (int, float)), (
        f"'total_cost_usd' must be a float, got {type(body['total_cost_usd'])}"
    )


def test_m3_ledger_records_successful_t1_completion(gw_client: TestClient, monkeypatch):
    """After a successful t1 completion with tenant_id='ten-abc', GET /ledger/ten-abc
    must contain at least one entry with task=='complete:t1', provider=='fake',
    tokens_in>0, cost_usd>=0.  Redis is absent; the in-memory fallback is used."""
    monkeypatch.setenv("MODEL_T1", "fake:echo")
    monkeypatch.delenv("MODEL_T1_FALLBACKS", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    # Trigger a completion so the ledger has something.
    comp_resp = gw_client.post(
        _COMPLETE_URL,
        json={"task": "t1", "prompt": "ثبت هزینه در دفتر کل", "tenant_id": "ten-abc"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert comp_resp.status_code == 200, (
        f"completion must succeed before checking ledger: {comp_resp.text}"
    )

    ledger_resp = gw_client.get(
        "/ledger/ten-abc",
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert ledger_resp.status_code == 200, ledger_resp.text
    body = ledger_resp.json()

    entries = body.get("entries", [])
    matching = [e for e in entries if e.get("task") == "complete:t1"]
    assert matching, (
        f"no entry with task='complete:t1' found in ledger for ten-abc; entries: {entries}"
    )

    entry = matching[0]
    assert entry.get("provider") == "fake", (
        f"expected provider='fake' in ledger entry, got {entry.get('provider')!r}"
    )
    assert isinstance(entry.get("tokens_in"), int) and entry["tokens_in"] > 0, (
        f"ledger entry tokens_in must be int >0, got {entry.get('tokens_in')!r}"
    )
    assert isinstance(entry.get("cost_usd"), (int, float)) and entry["cost_usd"] >= 0.0, (
        f"ledger entry cost_usd must be float >=0, got {entry.get('cost_usd')!r}"
    )


def test_m3_ledger_cross_tenant_isolation(gw_client: TestClient, monkeypatch):
    """Entries recorded for tenant A must NOT appear in tenant B's ledger
    (CLAUDE.md rule 6: tenant isolation is absolute)."""
    monkeypatch.setenv("MODEL_T1", "fake:echo")
    monkeypatch.delenv("MODEL_T1_FALLBACKS", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    # Complete for tenant-alpha only.
    comp = gw_client.post(
        _COMPLETE_URL,
        json={"task": "t1", "prompt": "داده مستاجر آلفا", "tenant_id": "tenant-alpha"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert comp.status_code == 200, comp.text

    # Ledger for tenant-beta must have no entries from tenant-alpha.
    beta_resp = gw_client.get(
        "/ledger/tenant-beta",
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert beta_resp.status_code == 200, beta_resp.text
    beta_entries = beta_resp.json().get("entries", [])
    alpha_leak = [e for e in beta_entries if e.get("tenant_id") == "tenant-alpha"]
    assert not alpha_leak, (
        f"cross-tenant isolation violated: tenant-alpha entries appeared in "
        f"tenant-beta's ledger: {alpha_leak}"
    )


def test_m3_idempotent_request_id_no_double_charge(gw_client, monkeypatch):
    """Rule 8: a retried request with the same request_id must NOT re-call the
    provider or add a second ledger entry."""
    monkeypatch.setenv("MODEL_T1", "fake:echo")
    from rpim_model_gateway.ledger import _MEMORY

    body = {
        "task": "t1",
        "prompt": "متن آزمون idempotency",
        "tenant_id": "ten-idem",
        "request_id": "req-fixed-123",
    }
    first = gw_client.post("/complete", json=body, headers={"X-Internal-Token": _VALID_TOKEN})
    assert first.status_code == 200, first.text
    count_after_first = sum(1 for e in _MEMORY if e["tenant_id"] == "ten-idem")

    second = gw_client.post("/complete", json=body, headers={"X-Internal-Token": _VALID_TOKEN})
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    count_after_second = sum(1 for e in _MEMORY if e["tenant_id"] == "ten-idem")
    assert count_after_second == count_after_first, "duplicate ledger charge on retry"


def test_m3_idempotency_key_is_tenant_scoped(gw_client, monkeypatch):
    """Rule 6: tenant B reusing tenant A's request_id must get ITS OWN
    completion, never A's cached payload."""
    monkeypatch.setenv("MODEL_T1", "fake:echo")
    common = {"task": "t1", "request_id": "req-shared-999"}
    resp_a = gw_client.post(
        "/complete",
        json={**common, "prompt": "متن مخصوص مستاجر الف", "tenant_id": "ten-a"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    resp_b = gw_client.post(
        "/complete",
        json={**common, "prompt": "متن مخصوص مستاجر ب", "tenant_id": "ten-b"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp_a.status_code == 200 and resp_b.status_code == 200
    assert resp_b.json()["text"] != resp_a.json()["text"], (
        "tenant B received tenant A's cached completion"
    )
