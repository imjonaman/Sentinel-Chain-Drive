"""Processed event tracking model for consumer-side idempotency and duplicate elimination."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from sentinel_chain_drive.db.base import Base, UUIDPrimaryKeyMixin


class ProcessedEvent(Base, UUIDPrimaryKeyMixin):
    """Consumer idempotency tracking record.

    Records successfully processed event IDs per consumer to ensure duplicate deliveries
    are safely acknowledged and discarded without re-execution.
    """

    __tablename__ = "processed_events"
    __table_args__ = (
        UniqueConstraint(
            "consumer_name",
            "event_id",
            name="uq_processed_events_consumer_event",
        ),
        Index("ix_processed_events_consumer_name", "consumer_name"),
        Index("ix_processed_events_institution_id", "institution_id"),
        Index("ix_processed_events_event_id", "event_id"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
    )
    consumer_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
    )
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
