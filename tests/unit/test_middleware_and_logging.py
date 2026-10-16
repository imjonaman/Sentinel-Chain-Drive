"""Unit tests for middleware behavior and log data sanitization."""

import pytest
from httpx import AsyncClient

from sentinel_chain_drive.core.logging import sanitize_sensitive_data


def test_sanitize_sensitive_data_redacts_keys() -> None:
    """Verify that credentials, tokens, and secrets are sanitized from payloads."""
    raw_data = {
        "user_id": "usr_123",
        "password": "super_secret_password",
        "auth_token": "bearer xyz123456",
        "api_key": "sk_live_987654321",
        "nested": {
            "private_key": "-----BEGIN PRIVATE KEY-----",
            "safe_counter": 42,
        },
    }
    sanitized = sanitize_sensitive_data(raw_data)
    assert sanitized["user_id"] == "usr_123"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["auth_token"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["private_key"] == "[REDACTED]"
    assert sanitized["nested"]["safe_counter"] == 42


@pytest.mark.asyncio
async def test_correlation_id_generated_when_absent(app_client: AsyncClient) -> None:
    """Check that a missing correlation ID is generated and returned in headers."""
    response = await app_client.get("/health/live")
    assert response.status_code == 200
    cid = response.headers.get("X-Correlation-ID")
    assert cid is not None
    assert len(cid) >= 8


@pytest.mark.asyncio
async def test_correlation_id_propagated_when_valid(app_client: AsyncClient) -> None:
    """Check that a valid client-supplied correlation ID is propagated."""
    client_cid = "corr-test-12345678-abc"
    response = await app_client.get("/health/live", headers={"X-Correlation-ID": client_cid})
    assert response.status_code == 200
    assert response.headers.get("X-Correlation-ID") == client_cid


@pytest.mark.asyncio
async def test_security_headers_present(app_client: AsyncClient) -> None:
    """Check that defensive security headers are attached to responses."""
    response = await app_client.get("/health/live")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


@pytest.mark.asyncio
async def test_request_size_limit_exceeded(app_client: AsyncClient) -> None:
    """Verify that payloads exceeding MAX_REQUEST_SIZE_BYTES are rejected with HTTP 413."""
    # test_settings configures MAX_REQUEST_SIZE_BYTES = 10_000
    oversized_body = "x" * 20_000
    response = await app_client.post(
        "/health/live",  # Any endpoint
        content=oversized_body,
        headers={"Content-Length": str(len(oversized_body))},
    )
    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "PAYLOAD_TOO_LARGE"
