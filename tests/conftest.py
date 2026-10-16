"""Pytest fixtures and configuration for Sentinel Chain Drive test suite."""

import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

# Ensure test environment variable defaults before settings load
os.environ["ENVIRONMENT"] = "testing"
os.environ["POSTGRES_PASSWORD"] = "test_only_mock_password"

from pydantic import SecretStr

from sentinel_chain_drive.api.main import create_app
from sentinel_chain_drive.core.config import Settings
from sentinel_chain_drive.db.base import Base
from sentinel_chain_drive.services.system_service import SystemService


@pytest.fixture
def test_settings() -> Settings:
    """Provide isolated testing settings with strict boundaries."""
    return Settings(
        ENVIRONMENT="testing",
        DEBUG=False,
        APP_NAME="Sentinel Chain Drive Test",
        APP_VERSION="0.1.0-test",
        CORS_ORIGINS=["http://testserver", "http://localhost:3000"],
        MAX_REQUEST_SIZE_BYTES=10_000,  # 10 KB for testing size limit middleware
        POSTGRES_HOST="test-host",
        POSTGRES_PORT=5432,
        POSTGRES_DB="test_db",
        POSTGRES_USER="test_user",
        POSTGRES_PASSWORD=SecretStr("test_only_mock_password"),
        DRUNIX_ADAPTER_TYPE="mock",
    )


@pytest.fixture
async def sqlite_engine() -> AsyncGenerator[AsyncEngine]:
    """In-memory SQLite async engine for isolated repository tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def app_client(test_settings: Settings) -> AsyncGenerator[AsyncClient]:
    """Async HTTP client bound to the test application."""
    test_app = create_app(settings=test_settings)
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


class MockHealthySystemService(SystemService):
    """Stub SystemService reporting healthy dependencies."""

    def __init__(self) -> None:
        super().__init__()

    async def check_readiness(self):  # type: ignore[no-untyped-def]
        resp, _ = await super().check_readiness()
        resp.status = "ready"
        resp.dependencies["database"].status = "healthy"
        resp.dependencies["database"].latency_ms = 1.2
        resp.dependencies["database"].message = None
        return resp, True


class MockUnhealthySystemService(SystemService):
    """Stub SystemService reporting failing dependencies."""

    def __init__(self) -> None:
        super().__init__()

    async def check_readiness(self):  # type: ignore[no-untyped-def]
        resp, _ = await super().check_readiness()
        resp.status = "not_ready"
        resp.dependencies["database"].status = "unhealthy"
        resp.dependencies["database"].latency_ms = 50.0
        resp.dependencies["database"].message = "Database connection failed or timed out."
        return resp, False
