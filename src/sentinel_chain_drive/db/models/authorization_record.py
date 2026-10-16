"""Authorization evidence and replay-protection models for AgentID."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProcessedNonce(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Persisted request nonce guaranteeing single-use replay protection."""

    __tablename__ = "processed_nonces"

    nonce: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        comment="Unique request nonce, e.g. UUID4 or high-entropy string",
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Claimed timestamp from the signed request",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="Pruning horizon after which the timestamp window has permanently lapsed",
    )


class AuthorizationRecord(Base, UUIDPrimaryKeyMixin):
    """Immutable audit record generated on every agent authorization evaluation."""

    __tablename__ = "authorization_records"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    credential_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    nonce: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    decision: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="Evaluation outcome: AUTHORIZED or REJECTED",
    )
    decision_reasons: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Machine-readable decision explanations or violation codes",
    )
    transaction_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA-256 digest of canonical transaction intent",
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )
    capability_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("capabilities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )

    # Relationships
    agent = relationship("Agent", lazy="selectin")
    institution = relationship("Institution", lazy="selectin")
    capability = relationship("Capability", lazy="selectin")
