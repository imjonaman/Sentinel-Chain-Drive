"""Integration tests for health probe endpoints (/health/live and /health/ready)."""

import pytest
from httpx import ASGITransport, AsyncClient

from sentinel_chain_drive.api.deps import get_system_service
from sentinel_chain_drive.api.main import create_app
from sentinel_chain_drive.core.config import Settings
from tests.conftest import MockHealthySystemService, MockUnhealthySystemService


@pytest.mark.asyncio
async def test_health_live_endpoint(app_client: AsyncClient) -> None:
    """Verify that /health/live returns HTTP 200 with status 'ok'."""
    response = await app_client.get("/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_health_ready_healthy_database(test_settings: Settings) -> None:
    """Verify that /health/ready returns HTTP 200 when database connectivity is healthy."""
    test_app = create_app(settings=test_settings)
    test_app.dependency_overrides[get_system_service] = lambda: MockHealthySystemService()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert "database" in data["dependencies"]
        assert data["dependencies"]["database"]["status"] == "healthy"
        assert data["dependencies"]["database"]["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_health_ready_failing_database(test_settings: Settings) -> None:
    """Verify that /health/ready returns HTTP 503 when database connectivity fails."""
    test_app = create_app(settings=test_settings)
    test_app.dependency_overrides[get_system_service] = lambda: MockUnhealthySystemService()

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert "database" in data["dependencies"]
        assert data["dependencies"]["database"]["status"] == "unhealthy"
        assert "failed" in data["dependencies"]["database"]["message"].lower()
