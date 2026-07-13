# ADR 0030 — T2 candidate narrowed to gemini-2.5-flash; thinking disabled; MODEL_T2 still unset

**Status:** accepted & completed by ADR 0031 (2026-07-13) — the tail-20
slice ran 20/20 with zero errors, qa_safety was judged, the gate cleared,
and MODEL_T2 is set to `gemini:gemini-2.5-flash`. Original interim status
below, kept for the record.

**Status (original, 2026-07-12):** interim — the CLAUDE.md gate ("MODEL_T2 stays unset until the
50-prompt Persian eval decides it") is NOT yet cleared: only 26/50 prompts
have produced output. MODEL_T2 therefore **remains unset** until the full
run completes. What IS decided here: candidate elimination, the adapter fix
the partial data proved necessary, and the ledger price entry.

**Evidence (eval runs 2026-07-07 → 2026-07-11, free tier, judge = this
session, strict on rag_grounded/qa_safety).**

- `gemini-2.0-flash`: **0 successful calls out of 56 attempts across
  multiple days and quota windows** — every call 429. The free tier for this
  model is effectively dead on our key. **Eliminated**: a model that cannot
  be called cannot be MODEL_T2, whatever its quality.
- `gemini-2.5-flash`: 26 unique successful outputs before the daily quota
  died; qa_safety (e41-e50) was never reached. Judged scores (1–5):

  | category | n | mean | notes |
  |---|---|---|---|
  | rag_grounded | 4 | **4.4** | excellent grounding: says "not in context" instead of inventing; no unsourced claims |
  | summarize_rewrite | 2 | 4.0 | faithful, natural register shifts |
  | tone_post | 10 | 2.5 | Persian fluent and on-tone, but every long output truncated + chat preambles |
  | hook_cta | 10 | 2.5 | same truncation/preamble pattern; one premise-second-guessing miss |
  | qa_safety | 0 | — | **no data** — the gate cannot clear without this slice |

**Root cause of the low tone/hook scores is ours, not the model's.** 2.5 is
a "thinking" model: internal reasoning consumes `maxOutputTokens`, so a 1024
budget yielded ~40 visible tokens and mid-sentence truncation on every long
asset. Fixed in the adapter: 2.5-series requests now send
`generationConfig.thinkingConfig.thinkingBudget: 0` (2.0 models reject the
field, so it is prefix-gated). The chat preambles ("حتماً! اینم...") are a
prompting concern for M4 templates: production prompts must demand
final-output-only.

**Decided now.**
- `gemini-2.0-flash` is out of the T2 race (unavailability, see above).
- The thinking-budget adapter fix ships immediately — it also benefits the
  rerun (faster, full-length outputs) since the eval imports the adapters
  from the checkout.
- `PRICES` carries gemini-2.5-flash's paid-tier list price (0.30/2.50 USD
  per 1M) so the per-tenant ledger books real cost from the first call.

**Completion plan (gate-clearing).**
- Next Gemini quota window (daily reset ~07:00 UTC): dispatch `eval-t2` with
  `candidates=gemini:gemini-2.5-flash` alone, `delay=8` — a full fresh
  50-prompt run for the single surviving candidate (single-candidate load
  fits the observed daily cap; thinking-off shortens calls).
- Judge the fresh 50 (same strictness). If qa_safety and overall quality
  pass, a follow-up amendment flips this ADR to **accepted** and MODEL_T2
  is set to `gemini-2.5-flash` in the Coolify UI (us leg) — value never in
  code (rule 4 config pattern).
- Regardless of outcome: free-tier quota (~dozens of calls/day) is a pilot
  ceiling, not a production budget — go paid-tier or top-up DeepSeek and
  re-run the comparison for a cost/latency decision.
- Re-eval triggers after acceptance: DeepSeek balance available · Gemini
  free-tier policy change · production p95 latency over 20s.
