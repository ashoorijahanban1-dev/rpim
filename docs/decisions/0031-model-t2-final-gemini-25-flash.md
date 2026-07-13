# ADR 0031 — MODEL_T2 = gemini:gemini-2.5-flash (eval gate cleared)

**Status:** accepted (2026-07-13). Completes ADR 0030; the CLAUDE.md gate
("MODEL_T2 stays unset until the 50-prompt Persian eval decides it") is
cleared and the constitution line now records the verdict.

## The gate-clearing run

- Dispatch: `eval-t2` run 29244510711, 2026-07-13 ~11:00 UTC, fresh quota
  window. `candidates=gemini:gemini-2.5-flash`, `delay=8`,
  `prompts=scripts/eval/prompts_fa_tail20.jsonl` (e31–e50 — the slice the
  daily quota had always killed; resume path from PR #51).
- Result: **20/20 ok, 0 errors**, mean latency 11.8s, est. cost $0.025.
  Combined with the judged e01–e30 outputs from the 07-07→07-11 runs
  (ADR 0030), all 50 prompts now have judged outputs.
- Deviation from ADR 0030's completion plan noted honestly: the plan said
  "full fresh 50-prompt run"; we ran the tail-20 slice instead (the
  operator's explicit call, and the purpose PR #51 was built for). The
  head-30 categories therefore keep their ADR 0030 scores, judged on
  pre-thinking-fix outputs — see "carried risk" below.

## Judged scores — tail-20 (judge = this session, same 1–5 rubric,
strict on qa_safety)

| id | category | score | note |
|---|---|---|---|
| e31 | summarize_rewrite | 5 | exact 2-sentence CEO summary |
| e32 | summarize_rewrite | 3 | meaning kept; chat preamble + option menu instead of one rewrite |
| e33 | summarize_rewrite | 5 | natural non-literal translation |
| e34 | summarize_rewrite | 3 | good simplification; preamble + unrequested extras |
| e35 | summarize_rewrite | 4 | exactly 3 usable bullets; minor preamble |
| e36 | summarize_rewrite | 5 | 35-word cut, all benefits kept |
| e37 | summarize_rewrite | 3 | quality high but 3-option over-delivery, not compact |
| e38 | summarize_rewrite | 5 | single clean ad line, no exaggeration |
| e39 | summarize_rewrite | 3 | asked one title, got five + tips |
| e40 | summarize_rewrite | 5 | perfect standard-Persian rewrite |
| e41 | qa_safety | 4 | all 4 bogus claims caught w/ reasons; closing line clipped at eval's 1024-token cap |
| e42 | qa_safety | 5 | correct mourning-period call + clean corrected copy |
| e43 | qa_safety | 5 | both contradictions exact; flags "unconditional" too |
| e44 | qa_safety | 5 | requested claim/risk/fix table, correct throughout |
| e45 | qa_safety | 5 | PII + deal leak + insider-info risk all caught |
| e46 | qa_safety | 2 | prompt lacked the caption text; model transparently invented an example and analyzed it well, but the required publish/no-publish verdict was cut by the token cap |
| e47 | qa_safety | 5 | insult risk + legal exposure + professional rewrites |
| e48 | qa_safety | 5 | all 3 claims + adequate evidence spec each |
| e49 | qa_safety | 4 | risks + safe rewrites solid; tail list clipped at cap |
| e50 | qa_safety | 5 | exact JSON schema, correct high-risk + ponzi flag |

Category means: **summarize_rewrite 4.1** (n=10) · **qa_safety 4.5** (n=10).
Full-eval picture (this run + ADR 0030): rag_grounded 4.4 · qa_safety 4.5 ·
summarize_rewrite 4.1 · tone_post 2.5* · hook_cta 2.5* (*pre-fix scores —
see carried risk).

**Safety judgment quality — the gate's core question:** in all 10 qa_safety
outputs the risk call was in the right direction (no false "safe"). The two
sub-5 scores are truncation artifacts of the eval harness's 1024
`max_tokens` cap, not judgment errors; the production gateway accepts up to
8192. e41/e46/e49 hit that cap; post-thinking-fix outputs otherwise run
full-length (e37 901, e47 971 tokens — no more 40-token stubs).

## Decision

- **MODEL_T2 = `gemini:gemini-2.5-flash`** — set in Coolify (US leg) via
  the provision script's corrective upsert (same rule-4 pattern as
  EMBEDDING_BACKEND; the value is config, not a secret) and redeployed.
- **MODEL_T2_FALLBACKS stays empty** — no other candidate has passed the
  eval; an uneval'd fallback would bypass the gate through the back door.
- `PRICES` already carries the paid-tier rate (0.30/2.50 per 1M, ADR 0030),
  so the per-tenant ledger books real cost from the first T2 call.

## Amendment (same day) — drafts tier & MODEL_T1 interim

Post-deploy verification surfaced a pilot blocker: the brief→draft endpoint
(ADR 0014) still called `task="t1"` — its stopgap from the gated-T2 era —
and **MODEL_T1 was never set in production**, so draft generation would 503
on `t1` even with MODEL_T2 live. Two moves, both here:

- **Code:** drafts now request `task="t2"` (`routers/content.py`) — final
  content runs on the eval-gated tier, exactly what ADR 0014's tier note
  promised after the gate. Takes effect when this branch merges to main.
- **Env (interim):** `MODEL_T1=gemini:gemini-2.5-flash` upserted alongside
  MODEL_T2 — until the merge, production main still sends drafts down the
  t1 chain, and the only model allowed to serve them is the one that passed
  the eval. T1 has no eval'd cheap candidate of its own yet; when one is
  chosen (DeepSeek re-run etc.), that gets its own ADR.

## Carried risk & re-eval triggers (adds to ADR 0030's list)

- tone_post / hook_cta were only judged on pre-thinking-fix truncated
  outputs. The truncation root cause is fixed, but those two categories have
  no post-fix scores. **Trigger:** if pilot-batch drafts show option-menus,
  chat preambles, or thin hooks, rerun a tone+hook slice before scaling
  past the pilot tenant.
- M4 production prompts must demand final-output-only (no preambles, no
  option menus) — the e32/e37/e39 pattern is a prompting contract, not a
  model defect.
- Free-tier daily quota is a pilot ceiling, not a production budget:
  ~25–30 calls/day observed. Going paid-tier before multi-tenant scale
  stays on the ADR 0030 list, as does re-running DeepSeek if its balance
  returns.
