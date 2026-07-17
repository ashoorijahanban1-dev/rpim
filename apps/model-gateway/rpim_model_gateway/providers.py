"""Provider adapters (T1/T2 completion). Thin httpx calls, no SDKs.
Keys come from env NAMES only; a missing key is a failed chain link, never an
exception that reaches the user (the router falls through to the next link)."""

import hashlib
import os

import httpx


class ProviderError(Exception):
    pass


def _fake_complete(
    model: str,
    prompt: str,
    system: str | None = None,
    max_tokens: int | None = None,
    timeout: float = 60.0,
) -> dict:
    """Deterministic offline provider for tests/CI/dev."""
    seed = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
    text = f"[echo:{seed}] پیش‌نویس آزمایشی: {prompt[:200]}"
    return {
        "text": text,
        "tokens_in": max(1, len(prompt) // 4),
        "tokens_out": max(1, len(text) // 4),
    }


def _gemini_complete(model, prompt, system=None, max_tokens=None, timeout=60.0) -> dict:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise ProviderError("GEMINI_API_KEY not set")
    body: dict = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if max_tokens:
        body["generationConfig"] = {"maxOutputTokens": max_tokens}
    if model.startswith("gemini-2.5"):
        # 2.5-series are "thinking" models: internal reasoning consumes
        # maxOutputTokens and truncates the visible reply to a stub (proven
        # in the phase-0 eval — ADR 0030). Marketing copy needs the whole
        # budget as text. 2.0 models reject this field, so gate by prefix.
        body.setdefault("generationConfig", {})["thinkingConfig"] = {"thinkingBudget": 0}
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        # Key travels in the official header, NEVER the URL — httpx exception
        # strings embed the URL, so a query-param key would leak into error
        # messages and result rows (rule 4).
        headers={"x-goog-api-key": key},
        json=body,
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    usage = data.get("usageMetadata", {})
    return {
        "text": data["candidates"][0]["content"]["parts"][0]["text"],
        "tokens_in": usage.get("promptTokenCount", 0),
        "tokens_out": usage.get("candidatesTokenCount", 0),
    }


def _openai_compatible(base_url: str, api_key_env: str):
    def call(model, prompt, system=None, max_tokens=None, timeout=60.0) -> dict:
        key = os.environ.get(api_key_env, "").strip()
        if not key:
            raise ProviderError(f"{api_key_env} not set")
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        response = httpx.post(
            f"{base_url}/chat/completions",
            json={"model": model, "messages": messages, "max_tokens": max_tokens or 1024},
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage", {})
        return {
            "text": data["choices"][0]["message"]["content"],
            "tokens_in": usage.get("prompt_tokens", 0),
            "tokens_out": usage.get("completion_tokens", 0),
        }

    return call


def _openai_compat_complete(model, prompt, system=None, max_tokens=None, timeout=60.0) -> dict:
    """Operator-configured OpenAI-compatible endpoint (M17 — GapGPT-style).
    Base URL is read at CALL time so swapping providers is an env change with
    zero code; a missing var is a failed chain link like any other."""
    base = os.environ.get("OPENAI_COMPAT_BASE_URL", "").strip().rstrip("/")
    if not base:
        raise ProviderError("OPENAI_COMPAT_BASE_URL not set")
    return _openai_compatible(base, "OPENAI_COMPAT_API_KEY")(
        model, prompt, system=system, max_tokens=max_tokens, timeout=timeout
    )


def _anthropic_complete(model, prompt, system=None, max_tokens=None, timeout=60.0) -> dict:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise ProviderError("ANTHROPIC_API_KEY not set")
    body: dict = {
        "model": model,
        "max_tokens": max_tokens or 1024,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        json=body,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return {
        "text": data["content"][0]["text"],
        "tokens_in": data["usage"]["input_tokens"],
        "tokens_out": data["usage"]["output_tokens"],
    }


PROVIDERS = {
    "fake": _fake_complete,
    "gemini": _gemini_complete,
    "deepseek": _openai_compatible("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "anthropic": _anthropic_complete,
    "openai_compat": _openai_compat_complete,
}

# USD per 1M tokens (input, output) — [فرض] anchors until the phase-0 eval
# refines them (ADR 0013). Unknown models cost 0 and are flagged in entries.
PRICES: dict[str, tuple[float, float]] = {
    "echo": (0.0, 0.0),
    "gemini-2.0-flash": (0.10, 0.40),
    # MODEL_T2 (ADR 0030). Paid-tier list price so the ledger books real cost
    # even while the key rides the free tier.
    "gemini-2.5-flash": (0.30, 2.50),
    "deepseek-chat": (0.27, 1.10),
}


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out
