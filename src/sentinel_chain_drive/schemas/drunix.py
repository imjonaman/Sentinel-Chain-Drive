"""Pydantic schemas for DRUNIX integration monitoring and operational status."""

import uuid

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
    total_retries: int = Field(default=0, description="Total retry attempts across all events")
    replay_operations_total: int = Field(default=0, description="Total replay operations executed")
    stale_claims_recovered_total: int = Field(
        default=0, description="Total stale processing claims recovered"
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
    average_processing_latency_ms: float = Field(
        default=0.0, description="Average worker processing latency in milliseconds"
    )
    backpressure_active: bool = Field(
        default=False, description="Flag indicating active backpressure or throttling"
    )
    last_successful_processing_time: str | None = Field(
        default=None, description="ISO timestamp of last successful delivery"
    )


class ReplayEventRequest(BaseModel):
    """Request payload to replay an eligible failed outbox event."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        default="Manual operator replay",
        max_length=256,
        description="Audit reason for requesting event replay",
    )


class ReplayEventResponse(BaseModel):
    """Response confirming event replay rescheduling."""

    event_id: uuid.UUID = Field(description="Replayed event ID")
    status: str = Field(description="New event lifecycle status")
    replay_count: int = Field(description="Total times this event has been replayed")
    message: str = Field(description="Outcome summary message")


class ReplayBatchRequest(BaseModel):
    """Request payload to batch replay failed outbox events for an institution."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        default="Batch operator replay",
        max_length=256,
        description="Audit reason for batch replay",
    )
    event_ids: list[uuid.UUID] | None = Field(
        default=None,
        description="Optional list of specific event IDs to replay",
    )


class ReplayBatchResponse(BaseModel):
    """Response summary for batch replay operation."""

    replayed_count: int = Field(description="Number of eligible events reset to PENDING")
    message: str = Field(description="Batch replay outcome message")


class OutboxEventDetailResponse(BaseModel):
    """Sanitized inspection response for an outbox event."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(description="Outbox event ID")
    institution_id: uuid.UUID = Field(description="Institution scope")
    event_type: str = Field(description="Event type name")
    event_category: str = Field(description="Event category: DOMAIN, FRAUD_INTELLIGENCE, etc.")
    schema_version: str = Field(description="Event contract version")
    aggregate_type: str = Field(description="Aggregate domain category")
    aggregate_id: uuid.UUID = Field(description="Aggregate record ID")
    idempotency_key: str = Field(description="Idempotency key")
    commitment_hash: str = Field(description="SHA-256 commitment hash")
    status: str = Field(description="Current status")
    attempt_count: int = Field(description="Processing attempt count")
    max_attempts: int = Field(description="Maximum retry attempts")
    replay_count: int = Field(description="Replay count")
    ordering_key: str | None = Field(default=None, description="Ordering key")
    sequence_number: int | None = Field(default=None, description="Sequence number")
    correlation_id: str | None = Field(default=None, description="Tracing correlation ID")
    causation_id: str | None = Field(default=None, description="Causation ID")
    error_category: str | None = Field(default=None, description="Error category if failed")
    last_error: str | None = Field(default=None, description="Sanitized last error message")
    receipt_reference: str | None = Field(default=None, description="Ledger tx hash receipt")
    created_at: str | None = Field(default=None, description="Creation timestamp")
