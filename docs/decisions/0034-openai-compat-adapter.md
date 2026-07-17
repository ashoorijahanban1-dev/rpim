# ADR 0034 — openai_compat: operator-swappable OpenAI-compatible provider (M17)

**Status:** accepted (2026-07-17)

## Context

The gateway's `PROVIDERS` registry already implements the adapter pattern:
every provider is a callable with one shared signature
`(model, prompt, system, max_tokens, timeout) → {text, tokens_in, tokens_out}`,
and the `/complete` chain walks `provider:model` links without knowing what
sits behind them. But every registered provider had a HARD-CODED endpoint
(deepseek's base URL is baked into the registry entry). Pointing the system
at a new OpenAI-compatible reseller (e.g. GapGPT, evaluated for quota relief)
required a code change — against the sprint requirement "dynamically
swappable between LLM providers without changing core business logic."

## Decision

- New registry entry **`openai_compat`** whose base URL and key come from env
  NAMES read **at call time** (rule 4): `OPENAI_COMPAT_BASE_URL`,
  `OPENAI_COMPAT_API_KEY`. Swapping providers = changing two env vars in
  Coolify, zero code, no redeploy of logic.
- It reuses the existing `_openai_compatible` factory — one implementation of
  the chat-completions wire format, two consumers (deepseek, openai_compat).
- A missing var raises `ProviderError` naming the var, which the chain treats
  as a failed link (falls through to the next fallback; users never see it).
- The key travels ONLY in the `Authorization` header, never the URL — httpx
  exception strings embed URLs, so a query-param key would leak (rule 4).

## Boundaries

- **The MODEL_T2 eval gate is untouched (ADR 0031).** `openai_compat` may
  serve T1 or ride fallback chains, but MODEL_T2 stays the eval-passed value;
  no endpoint becomes a T2 link without passing the 50-prompt Persian eval.
- OpenAI-compat resellers strip native-Gemini fields (`thinkingBudget=0`,
  proven necessary in ADR 0030), so `openai_compat:gemini-*` is expected to
  truncate replies — the adapter does not pretend to fix that; the eval gate
  is what protects quality.
- Unknown models price at 0 in the ledger (existing PRICES behavior); add a
  PRICES row when a real reseller model goes live.
