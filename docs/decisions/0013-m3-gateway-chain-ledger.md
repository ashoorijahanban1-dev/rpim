# ADR 0013 — M3 gateway: completion chain + full cost ledger

**Status:** accepted (M3, slice A)

**Decisions.**
- **Chain config is env-only**: `MODEL_T1` / `MODEL_T2` hold the primary
  `provider:model` link; `MODEL_T{1,2}_FALLBACKS` a comma list. Every link
  failure (missing key, HTTP error, timeout, unknown provider) falls through
  to the next link; the user sees no error unless the WHOLE chain fails
  (503 with per-link reasons) — the §6.4 acceptance encoded as a test.
- **Constitution enforced in code**: task=t2 with `MODEL_T2` unset returns
  503 citing the pending 50-prompt Persian eval, instead of guessing a model.
- **Providers**: thin httpx adapters (gemini / deepseek-as-openai-compatible /
  anthropic) + the deterministic `fake` for tests/CI/dev. No SDKs; keys by
  env NAME only.
- **Ledger v2**: every completion records provider, model, tokens_in/out and
  `cost_usd` (price table is a [فرض] anchor per 1M tokens, refined by the
  phase-0 eval; unknown models cost 0). `GET /ledger/{tenant_id}` (internal
  token) returns entries + total — the per-tenant cost dashboard (M9) reads
  from here.

**Still open in M3:** aggressive brand-context caching, retry-with-backoff
within a link (currently one attempt per link), and the T5 degraded-mode
local model — deliberately deferred (T5 is an "emergency light", web
blueprint §5).
