"""Application middlewares: request correlation ID tracking, body size limits, and headers."""

import re
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from sentinel_chain_drive.core.errors import build_error_response
from sentinel_chain_drive.core.logging import set_correlation_id

# Regex to validate correlation ID formats and prevent header injection
CORRELATION_ID_REGEX = re.compile(r"^[a-zA-Z0-9\-_]{8,64}$")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Assigns or propagates a request correlation ID across log contexts and response headers."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        header_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")
        if header_id and CORRELATION_ID_REGEX.match(header_id):
            correlation_id = header_id
        else:
            correlation_id = str(uuid.uuid4())

        set_correlation_id(correlation_id)
        request.state.correlation_id = correlation_id

        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Enforces maximum allowed request body size to prevent memory exhaustion and DoS."""

    def __init__(self, app: ASGIApp, max_size_bytes: int) -> None:
        super().__init__(app)
        self.max_size_bytes = max_size_bytes

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        content_length_header = request.headers.get("content-length")
        if content_length_header is not None:
            try:
                content_length = int(content_length_header)
                if content_length > self.max_size_bytes:
                    err_msg = (
                        f"Request payload exceeds the maximum allowed size of "
                        f"{self.max_size_bytes} bytes."
                    )
                    return build_error_response(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        error_code="PAYLOAD_TOO_LARGE",
                        message=err_msg,
                    )
            except ValueError:
                pass

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Applies defensive HTTP security headers to all outbound responses."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permit CDN assets and inline initialization scripts on interactive API doc paths
        if request.url.path in ("/docs", "/redoc", "/openapi.json"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.jsdelivr.net;"
            )
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'"

        return response
