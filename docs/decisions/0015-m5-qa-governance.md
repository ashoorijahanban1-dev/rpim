# ADR 0015 — M5 QA layer 1 + governance flags (silence / kill)

**Status:** accepted (M5, slice A)

**Decisions.**
- **Claims verify against the WHOLE brand brain** (all tenant chunks), not
  only the generation-time slice — a number the brain knows anywhere is
  sourced; anything else is a review-level flag.
- **Sensitivity blacklist is a starter list** (5 categories, Persian terms in
  `qa/sensitive_fa.json`); any hit is level="block" → `requires_human=true`,
  no exceptions (constitution rule 1; asymmetric policy — wrong silence is
  cheap). The curated per-vertical list is a living ops asset.
- **Channel caps** data-driven (telegram/bale/eitaa 4096, instagram 2200)
  with Persian channel-name normalization; unknown channel → review flag.
- **Governance flags in DB** (`governance_flags`, unique (scope, kind)):
  silence is tenant-scoped self-serve; the global kill switch is an OPS
  action behind the internal token. Resume is MANUAL-ONLY — no code path
  auto-releases. `is_publishing_halted()` is the single helper the M7
  publisher MUST call inside the send path (rule 2) — flag checks at send
  time mean queued jobs also stop; the <5s kill guarantee is one DB read.
- QA results persist on the draft (`content_drafts.qa`) for the M6 approval
  queue to display.

**Open (M5 slice B):** the silence-mode WATCHER (national-event feed →
auto-raise flag) — the flag/stop machinery is done; the monitor that raises
it automatically lands with the M3-trend feeds it depends on.
