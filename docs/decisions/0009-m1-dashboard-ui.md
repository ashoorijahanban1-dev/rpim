# ADR 0009 — M1 dashboard UI (auth + onboarding interview)

**Status:** accepted (M1)

**Decisions.**
- Register/Login/Onboarding are Next.js client components; ALL user-facing
  strings come from `locales/fa.json` (rule: nothing hardcoded in components);
  layout is `lang=fa dir=rtl`; email/password inputs render `dir=ltr`.
- The browser reaches core-api through `NEXT_PUBLIC_API_BASE` (default
  `/api`, which the local-profile Caddy prefix-strips to core-api). In
  production the base is set per deployment in the Coolify UI.
- Access token lives in `localStorage` for M1 simplicity; httpOnly-cookie
  hardening is an M10 item, recorded here so it is not forgotten.
- List/pairs answers are edited as plain textareas (one item per line /
  `term: description` per line) and converted client-side to the API shape —
  mobile-first, no widget dependencies.

**Closes ADR 0008's open items** together with the onboarding API slice;
M1 scope (§6.4) is complete: register/login, Tenant model, brand profile,
conversational onboarding interview, isolation proven by test.
