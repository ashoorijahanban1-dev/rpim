#!/usr/bin/env bash
# Encrypted DB backup (M10). Runs on the iran server (or CI) against the
# compose postgres. The passphrase comes ONLY from the environment (rule 4)
# and must never be stored next to the backups; offsite sync of the .enc
# files (rclone/scp) is the operator's nightly cron — see docs/ops/runbook.md.
#
# Usage: BACKUP_PASSPHRASE=... [BACKUP_DIR=infra/backup] bash scripts/backup.sh
set -euo pipefail

: "${BACKUP_PASSPHRASE:?set BACKUP_PASSPHRASE in the environment — never in the repo}"
BACKUP_DIR="${BACKUP_DIR:-infra/backup}"
COMPOSE="${COMPOSE:-docker compose -f docker-compose.iran.yml -p rpim-iran}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${BACKUP_DIR}/rpim-${STAMP}.sql.enc"

mkdir -p "${BACKUP_DIR}"

# pg_dump inside the container: DB credentials never leave the compose env.
# --no-owner/--no-privileges so the dump restores onto a clean drill database
# whose roles differ from production.
${COMPOSE} exec -T postgres sh -c \
  'pg_dump --no-owner --no-privileges -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE -out "${OUT}"

echo "backup written: ${OUT} ($(wc -c < "${OUT}") bytes)"
