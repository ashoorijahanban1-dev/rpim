from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator


class EmbeddingVector(TypeDecorator):
    """pgvector `vector(dim)` on postgresql, JSON elsewhere (sqlite tests).

    Search uses the raw `<=>` cosine-distance operator on the pg path and a
    python-side cosine fallback otherwise (see routers/brain.py, ADR 0011).
    """

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int = 1024):
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())
