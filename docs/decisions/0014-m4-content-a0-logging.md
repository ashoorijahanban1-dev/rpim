# ADR 0014 — M4 content generation + A0 apprentice logging

**Status:** accepted (M4, slice A)

**Decisions.**
- **Brief → draft**: RAG context = top-5 tenant-scoped brain chunks retrieved
  for the brief (shared `brain/retrieval.py`, same code as /brain/search);
  brand profile (tone + forbidden claims) forms the system prompt; the
  completion goes through the gateway (`COMPLETE_MODE=remote`; `fake` keeps
  tests offline and provably embeds tone+context in the output).
- **Unsourced-claim tripwire**: any multi-digit number (western or Persian)
  in the draft that is absent from the injected context sets
  `flag_unsourced` — a cheap M4-level guard; the real claim verification
  against the brand brain is M5 QA scope.
- **A0 logging is DB-backed** (`apprentice_events`: tenant_id, kind,
  schema_version, payload) rather than raw JSONL files: containers are
  ephemeral and principle 6 requires one-click export anyway — JSONL is the
  EXPORT format at the data-export boundary, the store is queryable and
  tenant-isolated. All three constitution signals recorded: approved
  (brief+context→output), edited (draft→human version), rejected
  (structured reason ∈ tone|fact|sensitivity|taste).
- Draft status machine starts here (draft→approved|edited|rejected); the
  M6 approval-queue UI sits on these primitives.

**Task tier note:** drafts currently run on T1 (`MODEL_T2` unset until the
50-prompt eval); the switch to T2 for final content is one env change.
