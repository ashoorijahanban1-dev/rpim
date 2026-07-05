import os

from alembic import context
from sqlalchemy import create_engine

# M0: no tables yet. M1 sets this to the SQLAlchemy metadata object, and its
# first migration must include `CREATE EXTENSION IF NOT EXISTS vector`
# (see docs/decisions/ — pgvector init boundary).
target_metadata = None


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (env only — never hardcoded)")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_database_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
