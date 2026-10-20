"""Pydantic schemas for DRUNIX integration monitoring and operational status."""

from pydantic import BaseModel, ConfigDict, Field


class DrunixCircuitBreakerStatus(BaseModel):
    """Sanitized circuit breaker telemetry."""

    model_config = ConfigDict(from_attributes=True)

    state: str = Field(description="Circuit breaker state: CLOSED, OPEN, or HALF_OPEN")
    consecutive_failures: int = Field(description="Current count of consecutive failures")
    failure_threshold: int = Field(description="Configured failure threshold")
    recovery_timeout_seconds: float = Field(description="Recovery timeout in seconds")
    last_failure_timestamp: float | None = Field(
        default=None, description="Unix timestamp of last failure"
    )
    last_state_change: float = Field(description="Unix timestamp of last state transition")


class DrunixOutboxMetrics(BaseModel):
    """Sanitized outbox delivery status counts and pending queue latency."""

    model_config = ConfigDict(from_attributes=True)

    counts_by_status: dict[str, int] = Field(description="Event counts keyed by status")
    total_pending: int = Field(description="Total events pending or in retryable backoff")
    total_processing: int = Field(description="Total events currently claimed by workers")
    total_delivered: int = Field(description="Total events successfully acknowledged by DRUNIX")
    total_terminal_failure: int = Field(description="Total events permanently rejected")
    total_reconciliation_required: int = Field(
        description="Total events requiring external node reconciliation"
    )
    oldest_pending_age_seconds: float = Field(
        description="Age in seconds of the oldest pending event"
    )


class DrunixStatusResponse(BaseModel):
    """Safe operational overview of DRUNIX integration health and outbox queues."""

    model_config = ConfigDict(from_attributes=True)

    worker_id: str = Field(description="Active worker identifier")
    adapter_type: str = Field(description="Adapter implementation: simulator or live")
    node_available: bool = Field(description="Liveness probe status of DRUNIX gateway node")
    circuit_breaker: DrunixCircuitBreakerStatus = Field(
        description="Circuit breaker operational status"
    )
    outbox: DrunixOutboxMetrics = Field(description="Transactional outbox queue metrics")
    last_successful_processing_time: str | None = Field(
        default=None, description="ISO timestamp of last successful delivery"
    )
