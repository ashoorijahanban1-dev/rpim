# ADR 0038 — RBAC (owner/editor/observer), invites v1, Vault v2 (M24)

**Status:** accepted (2026-07-18) — amends ADR 0033

## Context

Every user was implicitly almighty (sole member of their own tenant), and
the M16 vault sealed with Fernet only: authenticated, but a sealed blob was
not BOUND to its row — copied into another tenant's connection it would
decrypt fine. Enterprise tenants need role separation and 256-bit,
row-bound sealing (pentarchy design §1 0019, §3.4).

## Decisions

### RBAC
- `users.role ∈ owner|editor|observer` (migration **0019**; backfill
  `owner` is semantically exact — every pre-M24 user founded their own
  tenant). `/auth/register` keeps minting owners.
- `require_role(minimum)` layered on `get_identity` reads the role from the
  VERIFIED user row per request — fresh, revocable, never a JWT claim
  (module singletons `require_editor` / `require_owner` per B008).
- Matrix: plain `get_identity` GETs stay observer-readable; editor+ for
  content create/approve/edit/reject, studio, publish-job compile, QA
  check, channels list; owner for brand-profile writes, channel
  secrets, export, tenant silence, onboarding writes, invites.

### Invites (multi-seat v1)
- `POST /auth/invites` (owner) → raw token shown exactly ONCE; only its
  sha256 is stored. `POST /auth/invites/accept` (the token IS the auth)
  joins the INVITING tenant with the invited role (owner is never invited).
- **Collision rule:** valid only for emails with no existing user; a
  registered email gets 409 — accounts NEVER move across tenants (rule 6).
  A membership table is explicitly out of scope (future ADR if wanted).
- Unknown/used/expired tokens all answer one uniform **410** (no probing
  oracle). TTL 7 days on the app-TZ clock (ADR 0032 lever; sqlite's naive
  round-trip is reattached from `app_timezone()`, never a hardcoded zone).

### Vault v2
- `v2:` + base64(nonce‖ct), **AES-GCM-256** keyed by env
  `CHANNEL_SECRET_KEY_V2`, **AAD = `{tenant_id}:{channel}`** — blobs are
  row-bound; v1 Fernet stays readable (prefix dispatch — Fernet tokens
  always start `gAAAA`).
- **Rollout-safe:** seal falls back to v1 only when the V2 key is MISSING
  (deploy gap); an INVALID key raises — config errors must surface, never
  silently degrade. Every v2 failure (wrong AAD, corrupt blob, bad key)
  wraps into `VaultKeyError`, preserving the engine's per-job isolation
  (a corrupt row never aborts another tenant's dispatch).
- **Lazy best-effort re-seal** in `tenant_creds.resolve`: a readable v1
  blob upgrades to v2 on the next publish when the key exists; a re-seal
  failure keeps the v1 blob and the publish succeeds — key rollout can
  never become a publish outage. The M16b invariant stands: unsealable →
  job stays queued, never the global identity.

## Consequences

- Migration numbering: the alembic chain runs 0015 → **0019** (M24 kept its
  design-assigned number; 0016–0018 stay reserved for M21–M23 whose chain
  entries will follow as 0020+ if needed — revision links, not filenames,
  define order).
- Dashboard surfaces (invite UI, role badges, Persian 403 mapping) ride the
  next dashboard-touching milestone; the API contract is final here.
- m16 vault tests updated to the AAD-bound signature; m16b publish
  invariants unchanged and still green.
