from alembic import context
from sqlalchemy import create_engine

from rpim_core_api import models  # noqa: F401  (register tables on Base)
from rpim_core_api.db import Base
from rpim_core_api.db import _database_url as _database_url  # normalized psycopg3 URL

target_metadata = Base.metadata


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
