"""Integration tests for safe system metadata endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_system_info_endpoint(app_client: AsyncClient) -> None:
    """Verify that /api/v1/system/info returns valid metadata and no confidential attributes."""
    response = await app_client.get("/api/v1/system/info")
    assert response.status_code == 200
    data = response.json()

    # Required public safe fields
    assert "app_name" in data
    assert "version" in data
    assert "environment" in data
    assert data["api_version"] == "v1"
    assert "drunix_adapter_type" in data

    # Strictly forbidden sensitive information checks
    raw_text = response.text.lower()
    assert "password" not in raw_text
    assert "secret" not in raw_text
    assert "token" not in raw_text
    assert "private_key" not in raw_text
    assert "database_url" not in raw_text
    assert "connection_string" not in raw_text
