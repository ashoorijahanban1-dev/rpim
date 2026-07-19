# ADR 0037 — Kind-centric Brand Brain: facade, catalog door, graceful fallback (M20)

**Status:** accepted (2026-07-18)

## Context

The M2 brain stored undifferentiated chunks: retrieval could not prefer
product facts for a product post, and the Visual Prompt Studio did no
retrieval at all. The pentarchy design (docs/design/fable5-pentarchy.md §1
0015, §3.1) chose to make the EXISTING pgvector store kind-aware instead of
adding a parallel table or a second vector DB (ChromaDB rejected).

## Decision

- **Two facts, two fields.** `brain_sources.kind` keeps provenance
  (upload|crawl|pdf|catalog); the new `brain_chunks.kind` is the retrieval
  facet (`product|tone|faq|claim|doc`), validated at the API door
  (`SourceIn.knowledge_kind` Literal), indexed `(tenant_id, kind)`
  (migration 0015, backfill `doc`).
- **Structured catalog door.** `POST /brain/catalog` turns
  `{name, sku, price, features, url}` products into a DETERMINISTIC
  canonical Persian block (golden-tested) embedded as `kind=product`
  chunks, raw structure kept in `brain_sources.meta`. The existing
  `(tenant, content_hash)` dedupe makes replays upserts — the endpoint
  reports `{ingested, skipped}` (rule 8).
- **One retrieval facade.** `BrandBrain.retrieve(query, k, kinds)` +
  `compose_context(chunks, budget)` (brain/service.py). Drafts and the
  studio go through it; `search_chunks` gains a STRICT `kinds` filter and
  returns each chunk's kind. `GET /brain/search?kinds=` stays strict — the
  **graceful fallback (widen to `doc` when the tenant has no kinded
  chunks) lives only in the facade**, so prompt-building degrades while
  explicit search stays honest.
- **Studio grounds on the brain.** `create_prompt` retrieves
  `kinds=("product","tone")`, k=3, budget 800 chars; the expander gains an
  optional `context` — empty brain ⇒ no grounding section, byte-identical
  prompts to M15.
- **compose_context budget = 6000, not the design's 3500**: k=5 × ≤700-char
  chunks + titles ≈ 3.8k, so 3500 would have silently truncated today's
  context and changed golden draft behavior. Budget drops WHOLE blocks —
  a truncated claim can never mislead the model.
- **Export contract → version 2**: sources carry `meta`, chunks carry
  `kind` (DoD: the tenant owns every byte).

## Consequences

- The M23 watchdog gets its grounding surface for free
  (`retrieve(trend, kinds=("product","claim"))` + the relevance gate).
- The m4 embed-failure test now patches the facade's embed seam — the 503
  contract is unchanged, only the seam moved (clean-architecture
  extraction).
- Kind curation is optional by construction: uncurated tenants keep
  working through the doc fallback; curation only sharpens retrieval.
