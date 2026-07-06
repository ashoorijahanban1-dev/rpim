# ADR 0028 — SMS provider: SMS.ir

**Status:** accepted — provider decision recorded ahead of the phase-2 SMS
wiring; no SMS code exists yet.

**Context.** The env template reserved `KAVENEGAR_API_KEY` as a phase-2
placeholder. The operator's actual SMS service is SMS.ir, and the domain/edge
stack is standardizing (Cloudflare, ADR docs/ops/cloudflare-ssl.md), so the
placeholder should name the real provider before any code grows around it.

**Decision.**
- SMS.ir is the SMS provider. Integration (when phase 2 lands) uses its
  official REST API only — rule 5 applies to SMS exactly as to messengers;
  no unofficial gateways or scraping.
- Env var NAMES (values only in the Coolify UI, rule 4): `SMSIR_API_KEY`,
  `SMSIR_LINE_NUMBER`. The `KAVENEGAR_API_KEY` placeholder is removed.
- Like every channel adapter, future SMS sends go through the publisher's
  halt check (rule 2) and are tenant-scoped (rule 6).

**Consequences.** Purely a naming/urls decision today; the phase-2 milestone
that implements SMS (transactional notifications / OTP per blueprint) builds
against SMS.ir's API from the start. The runbook token-rotation table gains
an SMS.ir row.
