"""Health probe response schemas."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class HealthLiveResponse(BaseModel):
    """Payload returned by the liveness probe endpoint."""

    status: Literal["ok"] = Field(
        default="ok",
        description="Indicates the application process is alive and responsive.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp of the liveness check.",
    )


class DependencyHealth(BaseModel):
    """Health status details for an individual backend dependency."""

    status: Literal["healthy", "unhealthy"] = Field(
        description="Operational state of the dependent subsystem.",
    )
    latency_ms: float = Field(
        description="Round-trip latency of the health probe in milliseconds.",
    )
    message: str | None = Field(
        default=None,
        description="Optional sanitized status message or error reason.",
    )


class HealthReadyResponse(BaseModel):
    """Payload returned by the readiness probe endpoint."""

    status: Literal["ready", "not_ready"] = Field(
        description="Overall readiness state of the application and its critical dependencies.",
    )
    dependencies: dict[str, DependencyHealth] = Field(
        description="Individual health metrics for each verified external dependency.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp of the readiness check.",
    )
