# RPIM Operations Runbook (M10)

Single-server topology per ADR 0022: both legs run as separate Coolify
Docker Compose resources (`rpim-iran-leg`, `rpim-us-leg`) on the US server.
All commands below assume shell access to that server unless noted.
Secrets are env var NAMES only — values live in the Coolify UI (rule 4).

## Kill switch

Stops ALL publish queues, all tenants, in under 5 seconds (rule 7). The halt
check runs inside the publisher send path (`publisher/engine.py`), so jobs
already queued stop too (rule 2).

Activate (ops action, internal token — never a tenant JWT):

    curl -X POST "$CORE_API_URL/governance/kill" \
      -H "X-Internal-Token: $INTERNAL_TOKEN" -H "Content-Type: application/json" \
      -d '{"active": true, "reason": "<why>"}'

Verify it is active system-wide:

    curl "$CORE_API_URL/governance/global/status" -H "X-Internal-Token: $INTERNAL_TOKEN"

Resume is MANUAL-ONLY: repeat the call with `"active": false` once the
incident is over. Nothing auto-releases the flag.

## Silence mode

A national-event feed signal auto-sets GLOBAL silence — every tenant's
publishing halts:

    curl -X POST "$CORE_API_URL/governance/national-event" \
      -H "X-Internal-Token: $INTERNAL_TOKEN" -H "Content-Type: application/json" \
      -d '{"event_type": "national_mourning", "active": true, "reason": "<event>"}'

The feed CANNOT lift silence — `active=false` on that endpoint is rejected
(manual-only resume, rule 7). An operator resumes explicitly:

    curl -X POST "$CORE_API_URL/governance/global/silence" \
      -H "X-Internal-Token: $INTERNAL_TOKEN" -H "Content-Type: application/json" \
      -d '{"active": false, "reason": "<operator sign-off>"}'

Per-tenant silence stays available to tenants via `POST /governance/silence`
with their own JWT.

## Backup

Nightly encrypted off-site dump via `scripts/backup/pg-backup.sh`. Required
env: `DATABASE_URL`, `BACKUP_PASSPHRASE`, `BACKUP_REMOTE` (a mounted off-site
directory or an rclone remote like `s3:bucket/rpim`). Artifacts are gpg
AES256, timestamped `rpim-backup-YYYYMMDD_HHMMSS.sql.gpg`, never overwritten
on re-run.

Schedule it nightly on the server (host cron or a Coolify Scheduled Task):

    0 3 * * * cd /path/to/rpim && DATABASE_URL=... BACKUP_PASSPHRASE=... BACKUP_REMOTE=... scripts/backup/pg-backup.sh

Keep `BACKUP_PASSPHRASE` in the Coolify UI / a server-side secret store —
losing it makes every artifact unrecoverable; leaking it defeats encryption.

## Restore

Drill on a CLEAN database (never production) with
`scripts/backup/pg-restore-drill.sh`:

    export DRILL_DB_PASSWORD="$(openssl rand -hex 16)"   # throwaway, never reused
    docker run -d --name rpim-restore-drill -e POSTGRES_PASSWORD="$DRILL_DB_PASSWORD" -p 127.0.0.1:55432:5432 pgvector/pgvector:pg16
    DATABASE_URL="postgresql://postgres:${DRILL_DB_PASSWORD}@127.0.0.1:55432/postgres" \
      BACKUP_PASSPHRASE=... scripts/backup/pg-restore-drill.sh <artifact.sql.gpg>
    # verify: psql "$DATABASE_URL" -c 'select count(*) from tenants;'
    docker rm -f rpim-restore-drill

A wrong passphrase or corrupt artifact exits non-zero before psql sees any
data. Rehearse this quarterly — a backup that has never been restored is not
a backup.

## Deploy

Production deploys go through Coolify (ADR 0007). CI's `deploy` job triggers
redeploys of both legs after the smoke gate on `main`, using the
`COOLIFY_TOKEN` GitHub secret and the resource UUIDs in
`infra/coolify-uuids.conf`. Manual redeploy:

    curl "$COOLIFY_URL/api/v1/deploy?uuid=<resource-uuid>" -H "Authorization: Bearer $COOLIFY_TOKEN"

Re-provision from scratch (idempotent): run the "Coolify provision" GitHub
Actions workflow, which executes `scripts/coolify-provision.sh` and commits a
token-redacted report back to `docs/ops/`. Serve the Coolify panel over
HTTPS before creating tokens.

Rollback: redeploy the previous commit from the Coolify UI (each resource
keeps its deployment history), or revert the commit on `main` and let CI
redeploy.
