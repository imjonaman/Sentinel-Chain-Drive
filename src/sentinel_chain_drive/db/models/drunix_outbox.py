"""Transactional outbox data model for asynchronous DRUNIX ledger delivery.

Guarantees at-least-once, durable delivery of authorized ledger attestations and indicators
without blocking the deterministic synchronous authorization pipeline.
"""

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DrunixOutboxStatus(enum.StrEnum):
    """Lifecycle statuses for outbox delivery events."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DELIVERED = "DELIVERED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class DrunixEventType(enum.StrEnum):
    """Explicit event types handled by the DRUNIX integration outbox."""

    AUTH_ATTESTATION = "AUTH_ATTESTATION"
    FRAUD_INDICATOR = "FRAUD_INDICATOR"
    SETTLEMENT_RECORD = "SETTLEMENT_RECORD"


class DrunixOutboxEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Durable transactional outbox event record.

    Persisted in the same ACID transaction as the domain state change that requires
    external DRUNIX ledger attestation.
    """

    __tablename__ = "drunix_outbox_events"
    __table_args__ = (
        UniqueConstraint(
            "institution_id",
            "idempotency_key",
            name="uq_drunix_outbox_institution_idempotency",
        ),
    )

    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[DrunixEventType] = mapped_column(
        Enum(DrunixEventType, name="drunix_event_type_enum", native_enum=False),
        nullable=False,
        index=True,
    )
    schema_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="v1.0",
    )
    aggregate_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    aggregate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )
    commitment_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    status: Mapped[DrunixOutboxStatus] = mapped_column(
        Enum(DrunixOutboxStatus, name="drunix_outbox_status_enum", native_enum=False),
        nullable=False,
        default=DrunixOutboxStatus.PENDING,
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )
    locked_by: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_category: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    receipt_reference: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
