"""
M17 acceptance tests — operator-configurable OpenAI-compatible adapter
(آداپتر openai_compat: سوییچ‌پذیری provider بدون تغییر کد).

Contract:
  - PROVIDERS registry gains "openai_compat": the SAME call signature as every
    other adapter (strict adapter pattern — the router/business logic never
    changes when the provider swaps).
  - Endpoint + key come from env NAMES read at CALL time (rule 4):
      OPENAI_COMPAT_BASE_URL  — e.g. https://api.gapgpt.app/v1
      OPENAI_COMPAT_API_KEY   — Bearer credential
    so switching provider = changing two env vars, zero code.
  - Missing either var → ProviderError NAMING the var; in the /complete chain
    that is a failed link that falls through to the next fallback — the user
    never sees the raw error.
  - The key travels ONLY in the Authorization header, never the URL.
  - MODEL_T2 eval gate untouched: openai_compat is available to T1 and as a
    fallback link, but MODEL_T2 stays the eval-passed value (ADR 0031).

All tests named test_m17_<criterion>.
"""

from __future__ import annotations

import os
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

# Set INTERNAL_TOKEN before importing the gateway app (established pattern).
os.environ.setdefault("INTERNAL_TOKEN", _secrets.token_hex(16))

from rpim_model_gateway import providers
from rpim_model_gateway.main import app

_VALID_TOKEN = os.environ["INTERNAL_TOKEN"]
_KEY = "sk-test-not-real"  # noqa: S105 — inoperable test fixture


@pytest.fixture()
def gw_client():
    with TestClient(app) as c:
        yield c


class _Resp:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_chat_response() -> dict:
    return {
        "choices": [{"message": {"content": "پاسخ آزمایشی از سرویس سازگار"}}],
        "usage": {"prompt_tokens": 21, "completion_tokens": 13},
    }


# ===========================================================================
# 1. Registry — the adapter exists with the shared signature
# ===========================================================================


def test_m17_registry_has_openai_compat():
    assert "openai_compat" in providers.PROVIDERS, (
        f"PROVIDERS must register openai_compat: {sorted(providers.PROVIDERS)}"
    )


# ===========================================================================
# 2. Env-driven endpoint — swap the provider with env vars only
# ===========================================================================


def test_m17_call_hits_configured_base_url_with_bearer_key(monkeypatch):
    import httpx  # noqa: PLC0415

    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured.update(url=url, json=json, headers=headers)
        return _Resp(_fake_chat_response())

    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "https://api.gapgpt.app/v1/")
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", _KEY)
    monkeypatch.setattr(httpx, "post", fake_post)

    result = providers.PROVIDERS["openai_compat"]("gpt-4o-mini", "سلام دنیا", system="لحن گرم")

    assert captured["url"] == "https://api.gapgpt.app/v1/chat/completions", (
        f"trailing slash must normalize: {captured['url']}"
    )
    assert captured["headers"]["Authorization"] == f"Bearer {_KEY}"
    assert _KEY not in captured["url"], "key must NEVER ride in the URL (rule 4)"
    assert captured["json"]["model"] == "gpt-4o-mini"
    assert captured["json"]["messages"][0] == {"role": "system", "content": "لحن گرم"}
    assert captured["json"]["messages"][1] == {"role": "user", "content": "سلام دنیا"}
    assert result == {
        "text": "پاسخ آزمایشی از سرویس سازگار",
        "tokens_in": 21,
        "tokens_out": 13,
    }


def test_m17_swapping_env_swaps_endpoint_without_code_change(monkeypatch):
    import httpx  # noqa: PLC0415

    urls: list[str] = []

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        urls.append(url)
        return _Resp(_fake_chat_response())

    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", _KEY)
    monkeypatch.setattr(httpx, "post", fake_post)

    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "https://api.gapgpt.app/v1")
    providers.PROVIDERS["openai_compat"]("m", "متن")
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "https://other-llm.example.com/v1")
    providers.PROVIDERS["openai_compat"]("m", "متن")

    assert urls == [
        "https://api.gapgpt.app/v1/chat/completions",
        "https://other-llm.example.com/v1/chat/completions",
    ], f"base url must be read at CALL time (dynamic swap): {urls}"


# ===========================================================================
# 3. Rule 4 — missing config NAMES the env var
# ===========================================================================


def test_m17_missing_base_url_names_the_var(monkeypatch):
    monkeypatch.delenv("OPENAI_COMPAT_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", _KEY)
    with pytest.raises(providers.ProviderError) as excinfo:
        providers.PROVIDERS["openai_compat"]("m", "متن")
    assert "OPENAI_COMPAT_BASE_URL" in str(excinfo.value)


def test_m17_missing_key_names_the_var(monkeypatch):
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "https://api.gapgpt.app/v1")
    monkeypatch.delenv("OPENAI_COMPAT_API_KEY", raising=False)
    with pytest.raises(providers.ProviderError) as excinfo:
        providers.PROVIDERS["openai_compat"]("m", "متن")
    assert "OPENAI_COMPAT_API_KEY" in str(excinfo.value)


# ===========================================================================
# 4. Chain behavior — a link like any other (no business-logic change)
# ===========================================================================


def test_m17_complete_serves_via_openai_compat_link(gw_client: TestClient, monkeypatch):
    import httpx  # noqa: PLC0415

    monkeypatch.setenv("MODEL_T1", "openai_compat:gpt-4o-mini")
    monkeypatch.delenv("MODEL_T1_FALLBACKS", raising=False)
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "https://api.gapgpt.app/v1")
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", _KEY)
    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        return _Resp(_fake_chat_response())

    monkeypatch.setattr(httpx, "post", fake_post)

    resp = gw_client.post(
        "/complete",
        json={"task": "t1", "prompt": "متن تبلیغاتی", "tenant_id": "ten-m17"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "openai_compat", body
    assert body["model"] == "gpt-4o-mini", body
    assert body["tokens_in"] == 21 and body["tokens_out"] == 13, body


def test_m17_unconfigured_link_falls_through_to_fallback(gw_client: TestClient, monkeypatch):
    """Missing OPENAI_COMPAT_* is a failed chain link — the fallback serves
    and the user sees NO error (blueprint fallback-chain behavior)."""
    monkeypatch.setenv("MODEL_T1", "openai_compat:gpt-4o-mini")
    monkeypatch.setenv("MODEL_T1_FALLBACKS", "fake:echo")
    monkeypatch.delenv("OPENAI_COMPAT_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_COMPAT_API_KEY", raising=False)

    resp = gw_client.post(
        "/complete",
        json={"task": "t1", "prompt": "متن فالبک"},
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["provider"] == "fake", resp.json()


# ===========================================================================
# 5. Env templates carry the NAMES (rule 4, us leg)
# ===========================================================================


def test_m17_env_example_names_openai_compat_vars():
    from pathlib import Path  # noqa: PLC0415

    text = (Path(__file__).resolve().parents[3] / ".env.us.example").read_text("utf-8")
    for var in ("OPENAI_COMPAT_BASE_URL", "OPENAI_COMPAT_API_KEY"):
        assert f"{var}=" in text, f".env.us.example must name {var} (rule 4)"
