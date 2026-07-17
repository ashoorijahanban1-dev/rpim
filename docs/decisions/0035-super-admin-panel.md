# ADR 0035 — Super Admin panel: the one gated cross-tenant read (M18)

**Status:** accepted (2026-07-17)

## Context

Rule 6 makes tenant scoping absolute for every tenant-facing query, and all
existing routes derive `tenant_id` from the verified JWT only. But the
platform operator needs SaaS oversight: which brands exist, what each one
spends on models, and whether their channel connections are healthy. That is
by definition a cross-tenant read, so it needs an explicit, gated exception —
not a quiet loophole.

## Decision

- **Allowlist, not a role column.** Admins are named by env `ADMIN_EMAILS`
  (comma-separated, case-insensitive). No schema change, no privileged flag a
  compromised tenant request could flip; revocation is one env edit. An
  empty/unset list means NOBODY is admin — the safe default. The check runs
  against the verified `users` row at request time (`get_admin_identity` in
  `deps.py`), never against a client-supplied claim.
- **One router, status-only.** `/admin/tenants` is the single cross-tenant
  surface: per-tenant user counts, ledger cost/token totals, and channel
  connection **status + secret_set only**. Channel `config` (chat ids, site
  URLs) and all secret material are excluded by construction — the response
  never touches `secret_sealed` content, and tests assert both exclusions.
- **Direct-URL page.** `apps/dashboard/app/admin/page.tsx` is deliberately
  absent from the tenant sidebar; non-admins who guess the URL get the API's
  403 mapped to a Persian `fa.admin.denied` message.

## Consequences

- Auditing is simple: grep for `get_admin_identity` — every cross-tenant
  read must hang off it. Any new admin route without it is a review reject.
- The admin view can rank tenants by spend once ledger entries carry
  timestamps; the current totals are running sums (same limit as reports).
