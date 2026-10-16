"""Integration tests for uniform error responses and security shielding."""

import pytest
from httpx import ASGITransport, AsyncClient

from sentinel_chain_drive.api.main import create_app
from sentinel_chain_drive.core.config import Settings


@pytest.mark.asyncio
async def test_not_found_error_format(app_client: AsyncClient) -> None:
    """Verify that 404 responses conform to the uniform ErrorResponse schema."""
    response = await app_client.get("/nonexistent/endpoint/path")
    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    error = body["error"]
    assert error["code"] == "NOT_FOUND"
    assert "message" in error
    assert "correlation_id" in error
    assert "timestamp" in error


@pytest.mark.asyncio
async def test_unhandled_exception_does_not_leak_traces(test_settings: Settings) -> None:
    """Verify that unhandled server exceptions shield stack traces and sensitive error internals."""
    test_app = create_app(settings=test_settings)

    # Attach an intentionally broken route to trigger an unexpected exception
    @test_app.get("/trigger-unhandled-error")
    async def broken_route() -> None:
        # Simulate an internal database error with dummy connection details in exception message
        raise RuntimeError("Fatal internal error: postgres://user:secret123@db.internal:5432/core")

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/trigger-unhandled-error")
        assert response.status_code == 500
        body = response.json()
        assert "error" in body
        error = body["error"]
        assert error["code"] == "INTERNAL_SERVER_ERROR"
        # Verify the sensitive message and stack trace are completely hidden
        assert "secret123" not in response.text
        assert "db.internal" not in response.text
        assert "Traceback" not in response.text
        assert "message" in error
        assert "unexpected internal server error" in error["message"].lower()
