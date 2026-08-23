"""Alembic environment — reads the URL from .env, not from alembic.ini."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.db import Base

# Import every model so that Base.metadata is complete.
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.planner import models as _planner_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(
        url=settings.absolute_db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite has no ALTER COLUMN
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(settings.absolute_db_url)
    async with engine.connect() as connection:
        await connection.run_sync(_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
