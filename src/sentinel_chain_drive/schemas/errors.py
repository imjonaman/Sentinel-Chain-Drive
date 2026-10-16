"""Error response schema definitions."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    """Detailed structure of an API error payload."""

    code: str = Field(
        description="Machine-readable error code string.",
    )
    message: str = Field(
        description="Human-readable safe explanation of the error.",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Associated request correlation ID for tracing and log correlation.",
    )
    timestamp: datetime = Field(
        description="UTC timestamp when the error occurred.",
    )
    details: Any = Field(
        default=None,
        description="Optional sanitized error details, such as validation field constraints.",
    )


class ErrorResponse(BaseModel):
    """Uniform root envelope for API error responses."""

    error: ErrorBody = Field(
        description="Encapsulated error details.",
    )
