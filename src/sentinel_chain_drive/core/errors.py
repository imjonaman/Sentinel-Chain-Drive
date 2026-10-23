"""Standardized API exception classes and global exception handlers.

Ensures no internal paths, database connection strings, or stack traces are leaked to clients.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from sentinel_chain_drive.core.logging import get_correlation_id

logger = logging.getLogger(__name__)


class AppException(Exception):
    """Base application exception for domain-level errors."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        error_code: str = "BAD_REQUEST",
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details


class EntityNotFoundException(AppException):
    """Raised when a requested resource is not found."""

    def __init__(self, entity_name: str, identifier: str) -> None:
        super().__init__(
            message=f"{entity_name} with identifier '{identifier}' was not found.",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="NOT_FOUND",
        )


class DatabaseConnectionException(AppException):
    """Raised when the database connection or readiness check fails."""

    def __init__(self, message: str = "Database service is unavailable.") -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="SERVICE_UNAVAILABLE",
        )


class PayloadTooLargeException(AppException):
    """Raised when client request body exceeds maximum allowed size."""

    def __init__(self, max_size_bytes: int) -> None:
        super().__init__(
            message=f"Request payload exceeds the maximum allowed size of {max_size_bytes} bytes.",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            error_code="PAYLOAD_TOO_LARGE",
        )


def build_error_response(
    status_code: int,
    error_code: str,
    message: str,
    details: Any = None,
) -> JSONResponse:
    """Construct a uniform, sanitized JSON error response."""
    correlation_id = get_correlation_id()
    content: dict[str, Any] = {
        "error": {
            "code": error_code,
            "message": message,
            "correlation_id": correlation_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    }
    if details is not None:
        content["error"]["details"] = details

    return JSONResponse(
        status_code=status_code,
        content=content,
        headers={"X-Correlation-ID": correlation_id} if correlation_id else {},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all global exception handlers on the FastAPI application."""

    @app.exception_handler(AppException)
    async def app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
        logger.warning(
            "Application error [%s]: %s (details: %s)",
            exc.error_code,
            exc.message,
            exc.details,
        )
        return build_error_response(
            status_code=exc.status_code,
            error_code=exc.error_code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        error_code = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            413: "PAYLOAD_TOO_LARGE",
            422: "UNPROCESSABLE_ENTITY",
            500: "INTERNAL_SERVER_ERROR",
            503: "SERVICE_UNAVAILABLE",
        }.get(exc.status_code, "HTTP_ERROR")

        logger.warning("HTTP %d error: %s", exc.status_code, exc.detail)
        return build_error_response(
            status_code=exc.status_code,
            error_code=error_code,
            message=exc.detail,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Sanitize validation details to avoid leaking internal structures
        sanitized_errors = []
        for err in exc.errors():
            sanitized_errors.append(
                {
                    "loc": [str(loc_item) for loc_item in err.get("loc", [])],
                    "msg": err.get("msg", "Invalid value"),
                    "type": err.get("type", "value_error"),
                }
            )
        logger.info("Request validation failed: %s", sanitized_errors)
        return build_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            error_code="VALIDATION_ERROR",
            message="Input validation failed for the submitted request.",
            details=sanitized_errors,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        # Log the full stack trace internally, but strictly shield client from details
        logger.error("Unhandled server exception: %s", exc, exc_info=True)
        return build_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal server error occurred. Please contact system support.",
        )
