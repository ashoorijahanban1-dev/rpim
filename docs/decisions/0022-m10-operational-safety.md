# ADR 0022 — M10: operational safety (kill drill, encrypted backup, runbook)

**Status:** accepted (M10 — final MVP milestone)

**Decisions.**
- **Kill-switch drill is a timing test, run anywhere** (`make kill-drill`):
  the full activate→dispatch→blocked round-trip is asserted < 5s end-to-end
  (in practice milliseconds — one flag write + one indexed read), plus
  proofs that release is manual-only and that both tenants' queued jobs
  freeze mid-queue. The production drill is two curl commands documented in
  the runbook; the guarantee itself lives in the M5/M7 architecture (halt
  check inside the send path), which is why the drill tests passed the
  moment they were written.
- **Backups are encrypted pg_dump streams** (`scripts/backup.sh`):
  AES-256-CBC with PBKDF2 via openssl, passphrase ONLY from
  `BACKUP_PASSPHRASE` (rule 4); `--no-owner --no-privileges` so dumps
  restore onto clean databases with different roles. Offsite transfer of
  the already-encrypted files is an operator cron (rclone/scp) — the
  destination need not be trusted.
- **Restore is proven continuously, not assumed**
  (`scripts/restore-verify.sh` + a CI smoke step): every merge decrypts the
  fresh backup into a brand-new postgres container and verifies
  `alembic_version` and `tenants`. A random per-run passphrase in CI also
  proves the encrypt/decrypt path itself.
- **Runbook in Persian** (`docs/ops/runbook.md`) — the operator is the
  founder: kill switch, silence mode, backup/restore, token-rotation table
  (which env, where, in what order), tunnel-outage behavior, deploy paths,
  and an incident checklist. A static test pins the six required sections
  and scans the doc for token-like literals.

**Consequences.** All §13.1 Definition-of-Done items that are code are now
built and gated: approval queue, 3-messenger scheduled publish, per-tenant
cost ledger + report, kill switch < 5s (tested), silence-mode acceptance
(tested), encrypted backup with clean-environment restore (CI-drilled),
one-click data export remains the only unbuilt DoD line — queued as the
next slice. Remaining non-code DoD items (onboard a real brand < 48h,
first 7-asset batch < 24h) are Concierge-phase field tests, not code.
