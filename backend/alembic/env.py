"""Alembic environment, async.

The migration context itself is synchronous - Alembic drives it with ordinary
blocking calls - so an async engine cannot run it directly. `connection.run_sync`
is the bridge: it hands a sync-style Connection to Alembic while the underlying
driver stays async.

The database URL comes from app.core.config and never from alembic.ini, so a
credential has exactly one home and that home is gitignored.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.core.eventloop import configure_event_loop
from app.db.base import Base

import app.models  # noqa: F401  - registers every table on Base.metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata

# Celery's SQLAlchemy result backend and Kombu's SQLAlchemy broker transport
# (app/core/celery_app.py) create these four tables themselves on first
# connection, in the same database, outside Base.metadata entirely. Without
# this filter autogenerate would see them as unmanaged and propose dropping
# them on every future revision.
_CELERY_OWNED_TABLES = {
    "kombu_message",
    "kombu_queue",
    "celery_taskmeta",
    "celery_tasksetmeta",
}


def _include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and name in _CELERY_OWNED_TABLES:
        return False
    return True


def do_run_migrations(connection: Connection) -> None:
    # pgvector must exist before any table declaring a Vector column is created.
    # Idempotent, so it is safe on every upgrade rather than only the first.
    connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    connection.commit()

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting. Useful for reviewing a migration."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    configure_event_loop()
    asyncio.run(run_async_migrations())
