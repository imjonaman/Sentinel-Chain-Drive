"""Transaction domain and status history models for the simulated banking environment."""

import enum
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TransactionStatus(enum.StrEnum):
    """Lifecycle states for financial transactions."""

    SUBMITTED = "SUBMITTED"
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"
    HELD = "HELD"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class TransactionType(enum.StrEnum):
    """Transaction categorization."""

    TRANSFER = "TRANSFER"
    PAYMENT = "PAYMENT"
    SETTLEMENT = "SETTLEMENT"
    BOOK_TRANSFER = "BOOK_TRANSFER"


# Permitted lifecycle state transitions for transactions
VALID_TRANSACTION_TRANSITIONS: dict[TransactionStatus, set[TransactionStatus]] = {
    TransactionStatus.SUBMITTED: {
        TransactionStatus.PENDING_AUTHORIZATION,
        TransactionStatus.REJECTED,
    },
    TransactionStatus.PENDING_AUTHORIZATION: {
        TransactionStatus.HELD,
        TransactionStatus.SETTLED,
        TransactionStatus.REJECTED,
        TransactionStatus.CANCELLED,
    },
    TransactionStatus.HELD: {
        TransactionStatus.PENDING_AUTHORIZATION,
        TransactionStatus.SETTLED,
        TransactionStatus.REJECTED,
        TransactionStatus.CANCELLED,
    },
    TransactionStatus.SETTLED: set(),  # Terminal state
    TransactionStatus.REJECTED: set(),  # Terminal state
    TransactionStatus.CANCELLED: set(),  # Terminal state
}


class Transaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Simulated payment transaction record."""

    __tablename__ = "transactions"

    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
        index=True,
        comment="Unique client-supplied idempotency key preventing duplicate processing",
    )
    origin_institution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Initiating financial institution",
    )
    origin_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Debited origin account",
    )
    destination_institution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Receiving financial institution",
    )
    destination_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Credited destination account",
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        comment="Transfer amount in exact decimal precision",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        comment="ISO 4217 three-letter currency code",
    )
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, name="transaction_type_enum", native_enum=False),
        nullable=False,
        default=TransactionType.TRANSFER,
        comment="Transaction classification",
    )
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus, name="transaction_status_enum", native_enum=False),
        nullable=False,
        default=TransactionStatus.SUBMITTED,
        index=True,
        comment="Current lifecycle status",
    )
    purpose_code: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="TRANSFER",
        comment="Standard payment purpose descriptor",
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        nullable=True,
        index=True,
        comment="Optional AI-agent identifier for agentic initiation (Phase 3+)",
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment="Reason code or message explaining rejection or failure",
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="Associated HTTP request correlation ID",
    )
    simulation_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Simulation scenario parameters or synthetic tracking flags",
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when transaction reached final SETTLED status",
    )

    # Relationships
    origin_institution: Mapped["Institution"] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Institution",
        foreign_keys=[origin_institution_id],
    )
    destination_institution: Mapped["Institution"] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Institution",
        foreign_keys=[destination_institution_id],
    )
    origin_account: Mapped["Account"] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Account",
        foreign_keys=[origin_account_id],
    )
    destination_account: Mapped["Account"] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Account",
        foreign_keys=[destination_account_id],
    )
    status_history: Mapped[list["TransactionStatusHistory"]] = relationship(
        "TransactionStatusHistory",
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="TransactionStatusHistory.created_at.asc()",
    )

    __table_args__ = (CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),)


class TransactionStatusHistory(Base, UUIDPrimaryKeyMixin):
    """Immutable audit trail of transaction state transitions."""

    __tablename__ = "transaction_status_history"

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Referenced transaction identifier",
    )
    previous_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="Prior transaction status (null for initial creation)",
    )
    new_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="New transaction status",
    )
    reason: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment="Operational rationale or rule identifier for transition",
    )
    actor: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="system",
        comment="Actor or service triggering the transition",
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Associated HTTP request correlation ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        comment="Timestamp of state transition",
    )

    # Relationships
    transaction: Mapped["Transaction"] = relationship(
        "Transaction",
        back_populates="status_history",
    )
