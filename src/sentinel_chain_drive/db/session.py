"""Database connection and session lifecycle management using SQLAlchemy AsyncIO."""

import logging
import time
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sentinel_chain_drive.core.config import get_settings

logger = logging.getLogger(__name__)

_async_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Obtain or initialize the singleton AsyncEngine."""
    global _async_engine
    if _async_engine is None:
        settings = get_settings()
        connect_args: dict[str, int | float | str] = {}
        # Only pass timeout to asyncpg
        if "asyncpg" in settings.async_database_url:
            connect_args["timeout"] = settings.POSTGRES_POOL_TIMEOUT_SECONDS

        _async_engine = create_async_engine(
            settings.async_database_url,
            pool_size=settings.POSTGRES_POOL_SIZE,
            max_overflow=settings.POSTGRES_MAX_OVERFLOW,
            pool_timeout=settings.POSTGRES_POOL_TIMEOUT_SECONDS,
            pool_pre_ping=True,  # Proactively test connection liveliness before checkout
            echo=False,  # Do not echo raw SQL queries containing potentially sensitive values
            connect_args=connect_args,
        )
    return _async_engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Obtain or initialize the singleton async session maker."""
    global _async_session_factory
    if _async_session_factory is None:
        engine = get_engine()
        _async_session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _async_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    """Yield an async database session with automatic transaction commit/rollback."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_database_connectivity(
    engine: AsyncEngine | None = None,
    timeout_seconds: float = 3.0,
) -> tuple[bool, float, str | None]:
    """Execute a lightweight probe ('SELECT 1') to confirm database responsiveness.

    Returns:
        (is_healthy, latency_ms, error_message_if_any)
    """
    eng = engine or get_engine()
    start_time = time.perf_counter()
    try:
        async with eng.connect() as conn:
            # Enforce execution timeout via connection execution options
            await conn.execute(
                text("SELECT 1"),
                execution_options={"timeout": timeout_seconds},
            )
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return True, latency_ms, None
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        # Never log database connection string or passwords
        logger.warning("Database connectivity probe failed after %sms: %s", latency_ms, str(exc))
        return False, latency_ms, "Database connection failed or timed out."


async def close_db() -> None:
    """Gracefully dispose and close all connections in the connection pool."""
    global _async_engine, _async_session_factory
    if _async_engine is not None:
        await _async_engine.dispose()
        _async_engine = None
        _async_session_factory = None
        logger.info("Database connection engine disposed.")
