import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    pass


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (env only — never hardcoded)")
    # SQLAlchemy 2 + psycopg3: normalize the plain scheme used in env files.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


engine = None  # tests may inject their own engine before init_db()


def _ensure_engine():
    global engine
    if engine is None:
        engine = create_engine(_database_url(), pool_pre_ping=True)
    return engine


def init_db() -> None:
    """Create tables from metadata — TESTS ONLY (sqlite in-memory).

    Production schema changes go through Alembic exclusively (CLAUDE.md);
    the core-api container runs `alembic upgrade head` on start.
    """
    from rpim_core_api import models  # noqa: F401  (register tables on Base)

    _ensure_engine()
    Base.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    _ensure_engine()
    with Session(engine) as session:
        yield session
