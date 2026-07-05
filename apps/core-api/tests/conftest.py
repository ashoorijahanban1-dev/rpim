"""
conftest.py for core-api tests.

Sets DATABASE_URL and JWT_SECRET environment variables BEFORE any app module
is imported (conftest.py is loaded by pytest before test modules), then
provides a `client` fixture that:
  - creates a fresh SQLAlchemy engine backed by SQLite in-memory with StaticPool
    so all connections share the exact same in-memory database
  - injects that engine into rpim_core_api.db so init_db() targets the same store
  - calls rpim_core_api.db.init_db() to build the schema from metadata
  - overrides the rpim_core_api.db.get_session FastAPI dependency
  - tears everything down after each test
"""

import os
import secrets

# Must be set before ANY import of rpim_core_api so the app bootstraps with them.
# The JWT secret is GENERATED per test run — no secret literal in the repo
# (CLAUDE.md rule 4); tests only need consistency within one process.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["JWT_SECRET"] = secrets.token_hex(32)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def client():
    """
    Return a TestClient wired to a fresh in-memory SQLite database.

    The import of rpim_core_api.db is intentionally lazy (inside the fixture
    body) so that collection of M0 tests is not disrupted by the missing module.
    Once the module exists, this fixture will:
      1. Create a StaticPool engine (single connection shared across the session).
      2. Inject it as db_module.engine so init_db() writes to the same store.
      3. Call db_module.init_db() to create all tables.
      4. Override the get_session dependency for the FastAPI app.
    """
    import rpim_core_api.db as db_module  # noqa: PLC0415
    from rpim_core_api.main import app  # noqa: PLC0415

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Inject the engine before calling init_db so metadata.create_all targets
    # our StaticPool connection rather than a separate in-memory database.
    db_module.engine = engine
    db_module.init_db()

    def override_get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[db_module.get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
