"""ADR 0030 — gemini-2.5 "thinking" models must not eat the output budget.

The phase-0 eval proved that gemini-2.5-flash spends maxOutputTokens on
internal reasoning and returns ~40 visible tokens of a 1024 budget, truncating
every marketing asset mid-sentence. The adapter must disable thinking
(thinkingBudget: 0) for 2.5-series models — and ONLY for them (2.0 models
reject the field).

Also pins the paid-tier PRICES entry for the chosen MODEL_T2 so the
per-tenant ledger stops costing it at zero.
"""

from __future__ import annotations

import json

import rpim_model_gateway.providers as providers


class _FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "candidates": [{"content": {"parts": [{"text": "سلام"}]}}],
            "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
        }


def _capture_post(captured: dict):
    def fake_post(url, headers=None, json=None, timeout=None):  # noqa: A002
        captured["url"] = url
        captured["body"] = json
        return _FakeResponse()

    return fake_post


def test_gemini_25_disables_thinking_budget(monkeypatch):
    """gemini-2.5-* requests carry generationConfig.thinkingConfig.thinkingBudget=0
    while preserving maxOutputTokens."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured: dict = {}
    monkeypatch.setattr(providers.httpx, "post", _capture_post(captured))

    providers.PROVIDERS["gemini"]("gemini-2.5-flash", "سلام", max_tokens=1024)

    cfg = captured["body"].get("generationConfig", {})
    assert cfg.get("maxOutputTokens") == 1024, f"maxOutputTokens lost: {captured['body']}"
    assert cfg.get("thinkingConfig") == {"thinkingBudget": 0}, (
        f"2.5-series call must disable thinking so the token budget goes to "
        f"visible text (ADR 0030), got generationConfig={json.dumps(cfg)}"
    )


def test_gemini_20_does_not_send_thinking_config(monkeypatch):
    """gemini-2.0-* must NOT carry thinkingConfig — the API rejects it there."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured: dict = {}
    monkeypatch.setattr(providers.httpx, "post", _capture_post(captured))

    providers.PROVIDERS["gemini"]("gemini-2.0-flash", "سلام", max_tokens=512)

    cfg = captured["body"].get("generationConfig", {})
    assert "thinkingConfig" not in cfg, f"2.0 call must not send thinkingConfig: {cfg}"


def test_prices_cover_model_t2_choice():
    """gemini-2.5-flash (the surviving T2 candidate, ADR 0030) must have a
    non-zero paid-tier price so the per-tenant cost ledger never books it at
    zero."""
    price_in, price_out = providers.PRICES.get("gemini-2.5-flash", (0.0, 0.0))
    assert price_in > 0 and price_out > 0, (
        "PRICES must carry the ADR 0030 T2-candidate entry (gemini-2.5-flash)"
    )
