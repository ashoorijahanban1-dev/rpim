#!/usr/bin/env bash
# M10: nightly encrypted off-site Postgres backup.
# Reads env var NAMES only (rule 4): DATABASE_URL, BACKUP_PASSPHRASE,
# BACKUP_REMOTE. Never prints a secret value. Artifacts are gpg AES256
# symmetric, timestamped, and never overwrite a prior artifact (safe re-run).
set -euo pipefail

fail() { echo "pg-backup: $1" >&2; exit 1; }

[ -n "${DATABASE_URL:-}" ] || fail "env var DATABASE_URL is not set"
[ -n "${BACKUP_PASSPHRASE:-}" ] || fail "env var BACKUP_PASSPHRASE is not set"
[ -n "${BACKUP_REMOTE:-}" ] || fail "env var BACKUP_REMOTE is not set"
command -v pg_dump >/dev/null 2>&1 || fail "pg_dump not found on PATH"
command -v gpg >/dev/null 2>&1 || fail "gpg not found on PATH"

# BACKUP_REMOTE: a local directory (optionally file://-prefixed) or an
# rclone remote ("remote:path"). Off-site means NOT the database host.
remote="${BACKUP_REMOTE#file://}"

stamp="$(date -u +%Y%m%d_%H%M%S)"
name="rpim-backup-${stamp}.sql.gpg"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
artifact="$workdir/$name"

# Dump and encrypt in one stream — plaintext never touches disk.
# Passphrase over fd 3 (never argv, never logged).
pg_dump "$DATABASE_URL" \
  | gpg --batch --yes --symmetric --cipher-algo AES256 \
        --pinentry-mode loopback --passphrase-fd 3 \
        --output "$artifact" 3<<<"$BACKUP_PASSPHRASE"

case "$remote" in
  *:*)
    command -v rclone >/dev/null 2>&1 || fail "BACKUP_REMOTE looks like an rclone remote but rclone is not on PATH"
    rclone copyto "$artifact" "${remote%/}/$name"
    ;;
  *)
    mkdir -p "$remote"
    dest="$remote/$name"
    n=1
    while [ -e "$dest" ]; do   # never clobber a prior artifact
      dest="$remote/rpim-backup-${stamp}-${n}.sql.gpg"
      n=$((n + 1))
    done
    cp "$artifact" "$dest.part"
    mv "$dest.part" "$dest"
    ;;
esac

echo "pg-backup: wrote encrypted artifact $name to BACKUP_REMOTE" >&2
