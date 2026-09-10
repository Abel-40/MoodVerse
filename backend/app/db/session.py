"""Async engine and session factory.

psycopg3 is async-capable through the same `postgresql+psycopg://` URL the
sync driver uses, so there is one connection string for the application, for
Alembic and for ingestion rather than three that can drift apart.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_settings = get_settings()

engine: AsyncEngine = create_async_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    echo=False,
)

# expire_on_commit=False so a response model can still read an ORM object after
# the session commits; otherwise every attribute access would trigger a lazy
# refresh against a closed session.
SessionLocal = async_sessionmaker(
    bind=engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. One session per request, always closed."""
    async with SessionLocal() as session:
        yield session


async def dispose_engine() -> None:
    """Close the pool. Called on application shutdown."""
    await engine.dispose()
