# ADR 0048 — MVP DoD §13.1 audit closure

**Status:** accepted (2026-07-22)

## Context

With all five pentarchy pillars production-green, the §13.1 Definition of
Done was audited item-by-item against the test suite (evidence-first: an
item counts as covered only when an acceptance test proves it).

## Findings

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 1 | Onboard a brand <48h | covered | `test_m1_onboarding.py` (interview → profile, isolation); the 48h clock is an operational SLA (runbook), not code |
| 2 | First 7-asset batch <24h | **gap → closed here** | was single-asset only (`test_m4_content.py`); now `test_dod_seven_asset_batch.py` ships 7 briefs → 7 human-approved drafts → 3 messengers → one dispatch (sent=7) → export carries the batch |
| 3 | Scheduled publish on 3 messengers | covered | `test_m7_publish.py` + `test_m7b_channels_live.py`; `engine.py` scheduled_at gate; 30s beat |
| 4 | Per-tenant cost ledger | covered | `test_m3_complete.py::test_m3_ledger_cross_tenant_isolation` + `/ledger/{tenant_id}` |
| 5 | Kill switch <5s | covered | `test_m10_killswitch.py` timing assertion + in-path halt (`engine.py`) |
| 6 | Silence-mode simulated event | covered | `POST /governance/national-event` (`qa_governance.py:130`) + 5 passing tests in `test_m10_silence_event.py` — the audit agent initially flagged this as missing by misreading the test file's historical red-phase docstring; verified against the live suite before acting (a false finding, corrected) |
| 7 | One-click full export | covered | `test_m11_export.py` e2e + `export/page.tsx`; contract now v5 |

## Decision

DoD §13.1 is **code-complete: 7/7 items carry passing acceptance tests.**
The two timing clocks (48h onboard, 24h batch) remain operational SLAs in
`docs/ops/runbook.md` by design — a wall-clock business promise cannot be
a unit test. Item 2's capability proof is the new end-to-end batch test.

Remaining go-live items are operator-owned (values, never in repo —
rule 4): real channel credentials in Coolify, Umami env values, GA4
service-account file, and raising the pilot tenant to autonomy L1 for
the 7-day watchdog experiment (success ≥30% agent-draft acceptance).
