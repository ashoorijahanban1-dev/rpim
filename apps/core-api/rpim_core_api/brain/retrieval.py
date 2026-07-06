import math

from sqlalchemy import Float, select
from sqlalchemy.orm import Session

from rpim_core_api.models import BrainChunk, BrainSource


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def search_chunks(
    session: Session, tenant_id: str, query_vector: list[float], k: int
) -> list[dict]:
    """Tenant-scoped semantic retrieval — shared by /brain/search and the M4
    content generator. pgvector ANN on postgres, python cosine on sqlite."""
    base = (
        select(BrainChunk, BrainSource.title)
        .join(BrainSource, BrainChunk.source_id == BrainSource.id)
        .where(
            BrainChunk.tenant_id == tenant_id,
            BrainSource.tenant_id == tenant_id,
        )
    )

    if session.get_bind().dialect.name == "postgresql":
        # Explicit Float return type — otherwise SQLAlchemy inherits the
        # vector column type and runs the vector result-processor on the
        # scalar distance.
        distance = BrainChunk.embedding.op("<=>", return_type=Float)(query_vector)
        rows = session.execute(
            base.add_columns(distance.label("d")).order_by("d").limit(k)
        ).all()
        return [
            {
                "text": chunk.text,
                "source_id": chunk.source_id,
                "source_title": title,
                "score": 1.0 - float(dist),
            }
            for chunk, title, dist in rows
        ]

    rows = session.execute(base).all()
    scored = sorted(
        (
            {
                "text": chunk.text,
                "source_id": chunk.source_id,
                "source_title": title,
                "score": _cosine(query_vector, chunk.embedding),
            }
            for chunk, title in rows
        ),
        key=lambda r: r["score"],
        reverse=True,
    )
    return scored[:k]
