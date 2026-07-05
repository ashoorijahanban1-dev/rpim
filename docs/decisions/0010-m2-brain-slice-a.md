# ADR 0010 — M2 slice A: brand-brain ingestion core

**Status:** accepted (M2, slice A)

**Decisions.**
- **Embeddings are a gateway task (T3)**: core-api never talks to a model
  provider — `EMBED_MODE=remote` posts to `{GATEWAY_URL}/embed` with the
  cross-leg `X-Internal-Token`; `EMBED_MODE=fake` (tests/CI) uses the shared
  deterministic `rpim_shared.fake_embed`. The gateway's fake backend uses the
  same function, so contracts match end to end.
- **Ledger, minimal form**: every /embed call records tenant/task/model/units
  to Redis (`rpim:ledger:{tenant}`), in-memory fallback keeps the call path
  alive. M3 upgrades this to the full tokens+cost ledger — recorded here so
  the constitution's "every call writes to the ledger" is satisfied from the
  first model-shaped endpoint, not retrofitted.
- **Vectors stored as JSON in slice A** (works on sqlite tests AND pg; search
  is python-side cosine, tenant-scoped). Slice B — with the real bge-m3
  service — migrates the column to pgvector `vector(1024)` + `<=>` ANN
  search; the <2s acceptance target is measured on THAT path. Fine for
  MVP-scale tenants; the upgrade is a single additive migration.
- **Chunker**: paragraph-packing up to 700 chars with 100-char windowed
  overlap for oversized paragraphs; hazm/parsivar normalization deferred to
  M3 trend-engine needs.
- New tables `brain_sources`/`brain_chunks` ship with migration 0003 and a
  black-box cross-tenant isolation test (rule 6).

**Slice B (next):** real bge-m3 service on the US leg (optional-extra deps so
the workspace hook stays light), pgvector column migration, site crawl
ingestion via workers, PDF extraction.
