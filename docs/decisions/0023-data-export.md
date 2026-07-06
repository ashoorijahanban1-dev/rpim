# ADR 0023 — one-click full data export (closes §13.1 DoD)

**Status:** accepted

**Decisions.**
- **`GET /export` returns the tenant's complete data as one JSON document**
  with `Content-Disposition: attachment` (one click, one file): tenant
  record, brand profile, onboarding answers, brain sources WITH chunk texts,
  all drafts (every status, with QA results and briefs), the full A0
  apprentice log (rule 8 — those signals are the tenant's property), and all
  publish jobs (with UTM/landing links). `export_version: 1` future-proofs
  the format.
- **Embeddings are NOT exported**: they are derived data — re-ingesting the
  exported texts regenerates them on any embedding backend; exporting 1024-d
  vectors would bloat the file with data the tenant cannot use elsewhere.
- **Tables deliberately excluded** (do not "fix" this without a new ADR):
  `users` — credential data (`password_hash`); an export must never become a
  credential-exfiltration vector (rule 4), and account identity is not brand
  data. `governance_flags` — operational kill-switch/silence state owned by
  ops, not tenant content; exporting it adds no portability value.
- **Publish jobs export the frozen dispatched `text` and `last_error`** —
  the canonical record of what actually shipped (distinct from the draft)
  and the tenant's own delivery-error history.
- **Dashboard `/export` page**: one Persian button (all strings from
  `locales/fa.json` `export.*`, enforced by the same static-scan test
  pattern as `/reports`) that streams the JSON to a local file download.
- **Test-infra fix folded in**: `test_m5_qa.py` now uses the
  `os.environ.setdefault` pattern for `INTERNAL_TOKEN` like every other
  module — its forced overwrite during collection staled the token copies
  captured by earlier-collected modules (m10/m11), breaking dispatch calls
  in their e2e tests.

**Consequences.** Every §13.1 Definition-of-Done item that is CODE is now
built, tested, and gated: approval queue, 3-messenger publish, cost ledger
+ monthly report, kill switch <5s (drill-tested), silence-mode acceptance,
encrypted backup with CI-drilled clean restore, one-click export. The two
remaining DoD lines (onboard a real brand <48h; first 7-asset batch <24h)
are Concierge-phase field tests with a real brand, not code.
