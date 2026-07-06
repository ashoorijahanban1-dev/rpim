#!/usr/bin/env bash
# M10: restore drill — decrypt a pg-backup.sh artifact and pipe it into a
# CLEAN target database. Never point DATABASE_URL at production while
# drilling. Env var NAMES only (rule 4): DATABASE_URL, BACKUP_PASSPHRASE.
# Usage: pg-restore-drill.sh <artifact.sql.gpg>
set -euo pipefail

fail() { echo "pg-restore-drill: $1" >&2; exit 1; }

artifact="${1:-}"
[ -n "$artifact" ] || fail "usage: pg-restore-drill.sh <artifact.sql.gpg>"
[ -f "$artifact" ] || fail "artifact not found: $artifact"
[ -n "${DATABASE_URL:-}" ] || fail "env var DATABASE_URL is not set"
[ -n "${BACKUP_PASSPHRASE:-}" ] || fail "env var BACKUP_PASSPHRASE is not set"
command -v gpg >/dev/null 2>&1 || fail "gpg not found on PATH"
command -v psql >/dev/null 2>&1 || fail "psql not found on PATH"

# pipefail: a decryption failure (wrong passphrase, corrupt artifact) fails
# the whole drill even though psql would exit 0 on empty input.
gpg --batch --decrypt --pinentry-mode loopback --passphrase-fd 3 \
    3<<<"$BACKUP_PASSPHRASE" "$artifact" \
  | psql "$DATABASE_URL"

echo "pg-restore-drill: restore completed into target database" >&2
