"""BrandBrain — the one retrieval facade for every prompt-building call site
(M20, design §3.1). Content drafts, the Visual Prompt Studio and the M23
watchdog all ask the brain here; nobody hand-rolls search_chunks anymore.

Fallback contract: a kind-filtered retrieval DEGRADES instead of starving —
when the tenant has no chunks of the requested kinds, the filter widens to
include 'doc', so kind-aware consumers work from day one on tenants that
never curated kinds."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rpim_core_api.brain.embed_client import embed_texts
from rpim_core_api.brain.retrieval import search_chunks
from rpim_core_api.models import BrainChunk

KINDS = ("product", "tone", "faq", "claim", "doc")


class BrandBrain:
    def __init__(self, session: Session, tenant_id: str):
        self._session = session
        self._tenant_id = tenant_id

    def _has_kinded_chunks(self, kinds: Sequence[str]) -> bool:
        count = self._session.scalar(
            select(func.count())
            .select_from(BrainChunk)
            .where(
                BrainChunk.tenant_id == self._tenant_id,  # rule 6
                BrainChunk.kind.in_(tuple(kinds)),
            )
        )
        return bool(count)

    def retrieve(
        self, query: str, k: int = 5, kinds: Sequence[str] | None = None
    ) -> list[dict]:
        """Embed the query (per-tenant ledger via the gateway) and return the
        top-k chunks. httpx errors propagate — callers map them to their own
        503 contract, same as before the facade existed."""
        vector = embed_texts([query], tenant_id=self._tenant_id)[0]
        if kinds and not self._has_kinded_chunks(kinds):
            kinds = (*tuple(kinds), "doc")  # degrade, never starve
        return search_chunks(self._session, self._tenant_id, vector, k=k, kinds=kinds)

    @staticmethod
    def compose_context(chunks: list[dict], budget_chars: int = 6000) -> str:
        """Deterministic '[title] text' blocks joined by blank lines, capped
        by WHOLE blocks so a truncated claim can never mislead the model.
        6000 keeps today's k=5 × ≤700-char chunks intact (golden behavior);
        tighter callers (studio grounding) pass their own budget."""
        blocks: list[str] = []
        used = 0
        for chunk in chunks:
            block = f"[{chunk['source_title']}] {chunk['text']}"
            cost = len(block) + (2 if blocks else 0)
            if used + cost > budget_chars:
                break
            blocks.append(block)
            used += cost
        return "\n\n".join(blocks)