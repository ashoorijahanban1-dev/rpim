"""
M2B acceptance tests — EmbeddingVector SQLAlchemy TypeDecorator.

Contract for rpim_core_api.brain.vector_type.EmbeddingVector:
  - On PostgreSQL dialect: load_dialect_impl returns a pgvector Vector(1024) type
    (impl class name contains "VECTOR", or the type is pgvector.sqlalchemy.Vector).
  - On SQLite dialect: load_dialect_impl returns a JSON type.

No database connection is required; only SQLAlchemy dialect objects are used.
"""

from __future__ import annotations


def test_m2b_vector_type_postgresql_impl():
    """PostgreSQL dialect → impl class name contains 'VECTOR' or is pgvector Vector."""
    from sqlalchemy.dialects.postgresql import dialect as pg_dialect  # noqa: PLC0415

    from rpim_core_api.brain.vector_type import EmbeddingVector  # noqa: PLC0415

    instance = EmbeddingVector()
    impl = instance.load_dialect_impl(pg_dialect())
    impl_class_name = type(impl).__name__
    assert "VECTOR" in impl_class_name.upper() or "vector" in impl_class_name.lower(), (
        f"Expected a VECTOR/pgvector impl on PostgreSQL dialect, "
        f"got {impl_class_name!r} ({type(impl)})"
    )


def test_m2b_vector_type_sqlite_impl_is_json():
    """SQLite dialect → impl is a SQLAlchemy JSON type."""
    from sqlalchemy import JSON  # noqa: PLC0415
    from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect  # noqa: PLC0415

    from rpim_core_api.brain.vector_type import EmbeddingVector  # noqa: PLC0415

    instance = EmbeddingVector()
    impl = instance.load_dialect_impl(sqlite_dialect())
    assert isinstance(impl, JSON), (
        f"Expected JSON impl on SQLite dialect, got {type(impl).__name__!r}"
    )
