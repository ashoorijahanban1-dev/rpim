# ADR 0023 — M10: operational safety (kill switch ops, encrypted backup, runbook, export)

**Status:** accepted (M10).

**Context.** M0–M9 shipped the product loop; M10 closes the blueprint's last
milestone plus two Definition-of-Done gaps. The kill-switch and silence flags
existed since M5 (`governance_flags`, checked inside the publisher send path),
but there was no global-silence path, no operator-readable global status, no
backup/restore tooling, no runbook, and no one-click data export.

**Decision.**
- **Governance ops surface** (internal-token trust boundary, same as `/kill`):
  `GET /governance/global/status` (verify kill/silence without a tenant JWT);
  `POST /governance/kill` now confirms `scope: "global"` in its response;
  `POST /governance/national-event` — a feed signal AUTO-SETS global silence
  (all tenants halt); feed-driven `active=false` is rejected with 409 —
  resume is manual-only (rule 7) via the new `POST /governance/global/silence`.
  The <5 s kill guarantee needs no new machinery: the halt check is a
  synchronous read inside the dispatch loop, verified by a timing test.
- **Backup**: `scripts/backup/pg-backup.sh` — pg_dump streamed straight into
  gpg AES256 symmetric (plaintext never touches disk), timestamped artifact,
  never overwrites a prior artifact, uploads to `BACKUP_REMOTE` (local mount
  or rclone remote). Env var NAMES only: `DATABASE_URL`, `BACKUP_PASSPHRASE`,
  `BACKUP_REMOTE` (rule 4); passphrase passes over fd 3, never argv.
  Scheduling is a host cron / Coolify Scheduled Task (documented in the
  runbook), not a compose service — the single-server topology (ADR 0022)
  makes an in-stack cron container more moving parts for no isolation gain.
- **Restore drill**: `scripts/backup/pg-restore-drill.sh` decrypts and pipes
  to psql against a CLEAN `DATABASE_URL`; `pipefail` makes a wrong passphrase
  fail the drill before psql sees a byte. The drill was rehearsed end-to-end
  on a clean scratch cluster (seed → encrypted backup → restore → row-level
  verify → wrong-passphrase rejection) as part of landing this ADR.
- **Runbook**: `docs/ops/runbook.md` — kill switch, silence mode, backup,
  restore, deploy/rollback, all against the ADR 0022 single-server topology.
- **One-click export (DoD §13.1)**: `GET /export` returns the tenant's full
  data — brand profile, onboarding interview, brain sources + chunk texts
  (embeddings excluded: derived data, rebuildable), drafts with QA, publish
  jobs, apprentice A0 events (rule 8) — every query tenant-scoped with a
  cross-tenant isolation test (rule 6).

**Consequences.** All §6.4 milestones are now implemented; 33 new acceptance
tests (tests-first) cover kill timing, global silence lifecycle, backup
encryption/idempotency, restore round-trip, runbook coverage, and export
isolation. Remaining DoD items are operational, not code: the 50-prompt
Persian eval for `MODEL_T2`, real channel tokens for a 3-messenger production
publish, and putting TLS on the Coolify panel.
