"""Recovery-request orchestration data models for synthetic inter-bank response."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RecoveryStatus(enum.StrEnum):
    """Lifecycle statuses for controlled recovery requests."""

    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    SETTLED = "SETTLED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


class RecoveryActionType(enum.StrEnum):
    """Types of inter-bank recovery actions requested."""

    FUNDS_RECALL = "FUNDS_RECALL"
    PAYMENT_REVERSAL = "PAYMENT_REVERSAL"
    ACCOUNT_FREEZE_REQUEST = "ACCOUNT_FREEZE_REQUEST"
    TRANSACTION_HOLD_REQUEST = "TRANSACTION_HOLD_REQUEST"


VALID_RECOVERY_TRANSITIONS: dict[RecoveryStatus, set[RecoveryStatus]] = {
    RecoveryStatus.DRAFT: {
        RecoveryStatus.PENDING_APPROVAL,
        RecoveryStatus.REJECTED,
    },
    RecoveryStatus.PENDING_APPROVAL: {
        RecoveryStatus.APPROVED,
        RecoveryStatus.REJECTED,
    },
    RecoveryStatus.APPROVED: {
        RecoveryStatus.SUBMITTED,
        RecoveryStatus.REJECTED,
    },
    RecoveryStatus.SUBMITTED: {
        RecoveryStatus.ACKNOWLEDGED,
        RecoveryStatus.REJECTED,
        RecoveryStatus.OUTCOME_UNKNOWN,
    },
    RecoveryStatus.ACKNOWLEDGED: {
        RecoveryStatus.SETTLED,
        RecoveryStatus.REJECTED,
        RecoveryStatus.OUTCOME_UNKNOWN,
    },
    RecoveryStatus.OUTCOME_UNKNOWN: {
        RecoveryStatus.SETTLED,
        RecoveryStatus.REJECTED,
        RecoveryStatus.ACKNOWLEDGED,
    },
    RecoveryStatus.SETTLED: set(),
    RecoveryStatus.REJECTED: set(),
}

TERMINAL_RECOVERY_STATUSES: set[RecoveryStatus] = {
    RecoveryStatus.SETTLED,
    RecoveryStatus.REJECTED,
}


class RecoveryRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Controlled inter-bank recovery request orchestration record.

    Explicit Guardrail: All recovery requests are simulated prototype workflows.
    Sentinel Chain Drive does NOT possess direct legal authority or live rails
    to unilaterally debit or freeze external bank accounts.
    """

    __tablename__ = "recovery_requests"
    __table_args__ = (
        UniqueConstraint("request_number", name="uq_recovery_requests_number"),
        UniqueConstraint(
            "requesting_institution_id",
            "idempotency_key",
            name="uq_recovery_requests_institution_idempotency",
        ),
        Index("ix_recovery_requests_case_id", "case_id"),
        Index("ix_recovery_requests_transaction_id", "transaction_id"),
        Index("ix_recovery_requests_status", "status"),
        Index("ix_recovery_requests_requester", "requester_id"),
    )

    request_number: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Human-readable unique recovery identifier, e.g. REC-2026-0001",
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    requesting_institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )
    action_type: Mapped[RecoveryActionType] = mapped_column(
        Enum(RecoveryActionType, name="recovery_action_type_enum", native_enum=False),
        nullable=False,
        default=RecoveryActionType.FUNDS_RECALL,
    )
    status: Mapped[RecoveryStatus] = mapped_column(
        Enum(RecoveryStatus, name="recovery_status_enum", native_enum=False),
        nullable=False,
        default=RecoveryStatus.PENDING_APPROVAL,
    )
    rationale: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Detailed fraud or incident rationale justifying recovery attempt",
    )
    requester_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Investigator who prepared the recovery request",
    )
    requester_role: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="INVESTIGATOR",
    )
    approver_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="Supervisor who approved recovery (must differ from requester under dual control)",
    )
    approver_role: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    approval_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rejected_by: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )
    submission_attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    external_reference: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="Counterparty institution or mock rail tracking reference",
    )
    reconciliation_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="Reconciliation outcome: FULL_RECOVERY, PARTIAL_RECOVERY, UNRECOVERABLE",
    )
    reconciliation_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reconciled_by: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    is_simulated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Explicit safeguard: True indicates simulated banking rails",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    # Relationships
    case = relationship("Case", back_populates="recovery_requests")
    transaction = relationship("Transaction", lazy="selectin")
    requesting_institution = relationship(
        "Institution", foreign_keys=[requesting_institution_id], lazy="selectin"
    )
    target_institution = relationship(
        "Institution", foreign_keys=[target_institution_id], lazy="selectin"
    )
    history_records = relationship(
        "RecoveryStatusHistory",
        back_populates="recovery_request",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class RecoveryStatusHistory(Base, UUIDPrimaryKeyMixin):
    """Immutable transition history tracking recovery state changes and approvals."""

    __tablename__ = "recovery_status_history"
    __table_args__ = (
        Index("ix_recovery_status_history_request_id", "recovery_request_id"),
        Index("ix_recovery_status_history_created_at", "created_at"),
    )

    recovery_request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("recovery_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="CREATE, APPROVE, REJECT, SUBMIT, ACKNOWLEDGE, RECONCILE",
    )
    from_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    to_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    recovery_request = relationship("RecoveryRequest", back_populates="history_records")
