"""brain_chunks.embedding: JSON → pgvector vector(1024) + HNSW index

Postgres-only; sqlite test databases build from metadata (EmbeddingVector
compiles to JSON there). Existing rows are dropped with the column — brain
chunks are re-ingestable derivatives, and production tables are empty at
this point (slice A shipped hours before slice B).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-05

"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE brain_chunks DROP COLUMN embedding")
    op.execute("ALTER TABLE brain_chunks ADD COLUMN embedding vector(1024)")
    op.execute(
        "CREATE INDEX ix_brain_chunks_embedding_hnsw ON brain_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_brain_chunks_embedding_hnsw")
    op.execute("ALTER TABLE brain_chunks DROP COLUMN embedding")
    op.execute("ALTER TABLE brain_chunks ADD COLUMN embedding json")
