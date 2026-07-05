# ADR 0011 — M2 slice B: real embeddings + pgvector search

**Status:** accepted (M2, slice B)

**Decisions.**
- **Dedicated embeddings service** (`apps/embeddings`, us leg) per blueprint
  §2 placement; the gateway keeps owning the T3 task and forwards non-fake
  backends to it — services still never talk to a model host directly.
- **Heavy ML deps are an optional extra** (`rpim-embeddings[model]`): the
  workspace default sync (and the PostToolUse test hook) never installs
  torch. The Docker image opts in via build arg `INSTALL_MODEL`
  (`EMBEDDINGS_INSTALL_MODEL=true` set in Coolify; CI/local build light
  images and use the fake backend). Model weights download once into the
  `model-cache` volume, surviving redeploys.
- **`EmbeddingVector` TypeDecorator**: pgvector `vector(1024)` on postgres,
  JSON on sqlite — one model, both worlds. Migration 0004 (pg-only) converts
  the column (drop+add; brain chunks are re-ingestable derivatives and prod
  tables were empty) and adds an HNSW cosine index.
- **Search paths**: postgres → `<=>` ANN with HNSW (the <2s §6.4 acceptance
  target is measured here); sqlite tests → python cosine fallback.
- Server enablement: set `EMBEDDING_BACKEND=bge-m3` +
  `EMBEDDINGS_INSTALL_MODEL=true` in the Coolify UI and redeploy the us leg.

**Still open in M2:** site-crawl ingestion (workers), PDF extraction, and an
end-to-end pg-path check in CI smoke.
