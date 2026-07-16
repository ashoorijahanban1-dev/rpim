# ADR 0033 — Per-brand channel credentials live sealed in Postgres (M16 hub)

**Status:** accepted (2026-07-15)

## Context

Until M16, channel credentials were per-leg env vars (BALE_BOT_TOKEN …) —
single-tenant by construction. The Social Media Hub lets each brand connect
its own official-API channels from the dashboard, which requires per-tenant
credential storage. Rule 4 ("secrets never in code/repo/session, env NAMES
only") governs OUR deploy secrets; tenant channel tokens are runtime DATA,
like password hashes — but they are reversible credentials, so plaintext
rows are not acceptable.

## Decision

- `channel_connections` (Alembic 0013): one row per (tenant, channel),
  unique-constrained; non-secret settings in `config` JSON; the credential
  sealed with **Fernet** (authenticated AES — the `cryptography` package,
  no hand-rolled crypto) in `secret_sealed`.
- The Fernet key is env `CHANNEL_SECRET_KEY` (name-only everywhere, value
  set once in Coolify — NOT in the provision corrective list, since
  re-upserting would rotate it and orphan every sealed secret).
- The API is **write-only for secrets**: no response shape carries a secret
  back; listings expose `secret_set` booleans only. Instagram deliberately
  has no slot (rule 5: assisted-only, never credentialed automation).
- Key rotation = decrypt-all + re-seal, a deliberate manual runbook step.

## Follow-up (next slice, NOT in this one)

The publish engine still sends with per-leg env credentials. Switching
`channels.send()` to prefer a tenant's sealed credential (falling back to
env) is the M16b slice — it touches the publish path, so it ships alone
with its own review and tests.
