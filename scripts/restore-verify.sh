#!/usr/bin/env bash
# Clean-environment restore drill (M10 acceptance): decrypt the newest backup,
# restore it into a FRESH throwaway postgres container, and verify the schema
# version table plus the core tenants table. CI runs this on every merge, so
# recoverability is proven continuously — not assumed.
#
# Usage: BACKUP_PASSPHRASE=... [BACKUP_FILE=<path>] bash scripts/restore-verify.sh
set -euo pipefail

: "${BACKUP_PASSPHRASE:?set BACKUP_PASSPHRASE in the environment}"
BACKUP_DIR="${BACKUP_DIR:-infra/backup}"
BACKUP_FILE="${BACKUP_FILE:-$(ls -1t "${BACKUP_DIR}"/rpim-*.sql.enc | head -1)}"
CONTAINER="rpim-restore-drill-$$"

echo "restore drill: ${BACKUP_FILE} -> fresh container ${CONTAINER}"
docker run -d --name "${CONTAINER}" \
  -e POSTGRES_PASSWORD=restoredrill -e POSTGRES_DB=rpim \
  pgvector/pgvector:pg16 >/dev/null
trap 'docker rm -f "${CONTAINER}" >/dev/null 2>&1' EXIT

# pg_isready is NOT enough here: the postgres entrypoint answers pings from
# its temporary init server BEFORE POSTGRES_DB exists (and briefly restarts),
# so a psql against the target DB must be the readiness probe — anything less
# raced in CI ("database \"rpim\" does not exist", main run 29257318831).
for _ in $(seq 1 30); do
  if docker exec "${CONTAINER}" psql -U postgres -d rpim -tAc "SELECT 1" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE -in "${BACKUP_FILE}" \
  | docker exec -i "${CONTAINER}" psql -U postgres -d rpim -v ON_ERROR_STOP=1 >/dev/null

# Schema present (migrations ran on the source) and core table restored:
docker exec "${CONTAINER}" psql -U postgres -d rpim -tAc \
  "SELECT version_num FROM alembic_version" | grep -q .
docker exec "${CONTAINER}" psql -U postgres -d rpim -tAc \
  "SELECT count(*) FROM tenants" >/dev/null

echo "restore drill PASSED: alembic_version + tenants verified on a clean database"
