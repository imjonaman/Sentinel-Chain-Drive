"""Alembic migration environment configuration."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from sentinel_chain_drive.core.config import get_settings

# Import all models to ensure metadata registration
from sentinel_chain_drive.db import models  # noqa: F401
from sentinel_chain_drive.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = get_settings()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode without an active DB connection."""
    url = settings.sync_database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Execute migrations within an active transaction."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using the async engine configuration."""
    configuration = config.get_section(config.config_ini_section) or {}
    current_settings = get_settings()
    target_url = config.get_main_option("sqlalchemy.url") or current_settings.alembic_async_url
    if target_url.startswith("postgresql+psycopg://"):
        target_url = target_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    elif target_url.startswith("postgresql://"):
        target_url = target_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif target_url.startswith("sqlite://"):
        target_url = target_url.replace("sqlite://", "sqlite+aiosqlite://", 1)

    configuration["sqlalchemy.url"] = target_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
