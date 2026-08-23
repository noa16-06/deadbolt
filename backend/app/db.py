"""Database engine, session factory and declarative base."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.absolute_db_url, echo=False)


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_pragmas(dbapi_connection, _):
    """Without these three lines SQLite behaves differently than the code assumes.

    - foreign_keys: otherwise `ondelete="CASCADE"` does nothing at all.
    - WAL: readers no longer block the writer.
    - busy_timeout: wait briefly instead of failing with "database is locked".
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Common base for every table — Alembic reads the metadata through this."""


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, closed afterwards."""
    async with SessionFactory() as session:
        yield session
