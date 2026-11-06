"""Alembic environment (async engine).

Only the application tables are managed here. LangGraph's checkpointer creates its own
tables at startup (AsyncPostgresSaver.setup()), so they are not part of this metadata.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
settings = get_settings()
DATABASE_URL = settings.MIGRATION_DATABASE_URL or settings.DATABASE_URL


def asyncpg_url(url: str):
    """Prepare a PostgreSQL URL and Neon TLS options for asyncpg."""
    db_url = make_url(url)
    if db_url.drivername in {"postgres", "postgresql"}:
        db_url = db_url.set(drivername="postgresql+asyncpg")
    return db_url


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    db_url = asyncpg_url(DATABASE_URL)
    db_query = dict(db_url.query)
    sslmode = db_query.pop("sslmode", None)
    db_query.pop("channel_binding", None)
    engine = create_async_engine(
        db_url.set(query=db_query),
        poolclass=pool.NullPool,
        connect_args={"ssl": sslmode} if sslmode else {},
    )
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
