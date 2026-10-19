"""Policy decision outcomes, evaluation audit records, step-up challenges,
holds, and spending reservations.
"""

import enum
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PolicyOutcome(enum.StrEnum):
    """The four deterministic outcomes produced by the policy engine."""

    ALLOW = "ALLOW"
    STEP_UP = "STEP_UP"
    HOLD = "HOLD"
    DECLINE = "DECLINE"


class SpendingReservationStatus(enum.StrEnum):
    """Lifecycle states for capability velocity spending reservations."""

    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class StepUpStatus(enum.StrEnum):
    """Lifecycle status of step-up verification challenges."""

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class HoldStatus(enum.StrEnum):
    """Lifecycle status of transaction review holds."""

    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CONFIRMED_DECLINE = "CONFIRMED_DECLINE"


class SpendingReservation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Pending-spend reservation to prevent concurrent double-spend exceeding daily limits."""

    __tablename__ = "spending_reservations"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    policy_evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
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
    status: Mapped[SpendingReservationStatus] = mapped_column(
        Enum(SpendingReservationStatus, name="spending_res_status_enum", native_enum=False),
        nullable=False,
        default=SpendingReservationStatus.ACTIVE,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # Relationships
    agent = relationship("Agent", lazy="selectin")
    institution = relationship("Institution", lazy="selectin")

    def __init__(
        self,
        *,
        agent_id: uuid.UUID,
        institution_id: uuid.UUID,
        amount: Decimal,
        currency: str,
        status: SpendingReservationStatus = SpendingReservationStatus.ACTIVE,
        expires_at: datetime | None = None,
        transaction_id: uuid.UUID | None = None,
        policy_evaluation_id: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.agent_id = agent_id
        self.institution_id = institution_id
        self.amount = amount
        self.currency = currency
        self.status = status
        self.expires_at = expires_at or (datetime.now(UTC) + timedelta(minutes=15))
        self.transaction_id = transaction_id
        self.policy_evaluation_id = policy_evaluation_id


class StepUpChallenge(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Step-up dual-control or supervisor approval challenge record."""

    __tablename__ = "step_up_challenges"

    policy_evaluation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    transaction_intent_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("policies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    policy_version: Mapped[int] = mapped_column(
        nullable=False,
    )
    initiating_agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    verification_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="SUPERVISOR_APPROVAL",
    )
    required_role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="SUPERVISOR",
    )
    status: Mapped[StepUpStatus] = mapped_column(
        Enum(StepUpStatus, name="step_up_status_enum", native_enum=False),
        nullable=False,
        default=StepUpStatus.PENDING,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    approver_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    decision_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    agent = relationship("Agent", lazy="selectin")
    institution = relationship("Institution", lazy="selectin")
    policy = relationship("Policy", lazy="selectin")

    def __init__(
        self,
        *,
        policy_evaluation_id: uuid.UUID,
        transaction_intent_hash: str,
        policy_id: uuid.UUID,
        policy_version: int,
        initiating_agent_id: uuid.UUID,
        institution_id: uuid.UUID,
        verification_type: str = "SUPERVISOR_APPROVAL",
        required_role: str = "SUPERVISOR",
        status: StepUpStatus = StepUpStatus.PENDING,
        expires_at: datetime | None = None,
        transaction_id: uuid.UUID | None = None,
        approver_id: str | None = None,
        decision_reason: str | None = None,
        completed_at: datetime | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.policy_evaluation_id = policy_evaluation_id
        self.transaction_intent_hash = transaction_intent_hash
        self.policy_id = policy_id
        self.policy_version = policy_version
        self.initiating_agent_id = initiating_agent_id
        self.institution_id = institution_id
        self.verification_type = verification_type
        self.required_role = required_role
        self.status = status
        self.expires_at = expires_at or (datetime.now(UTC) + timedelta(minutes=30))
        self.transaction_id = transaction_id
        self.approver_id = approver_id
        self.decision_reason = decision_reason
        self.completed_at = completed_at


class TransactionHold(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Institutional hold record awaiting manual fraud/compliance review."""

    __tablename__ = "transaction_holds"

    policy_evaluation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    transaction_intent_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hold_reason: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )
    review_workflow: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="FRAUD_INVESTIGATION",
    )
    status: Mapped[HoldStatus] = mapped_column(
        Enum(HoldStatus, name="hold_status_enum", native_enum=False),
        nullable=False,
        default=HoldStatus.ACTIVE,
        index=True,
    )
    resolved_by: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    resolution_notes: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    institution = relationship("Institution", lazy="selectin")

    def __init__(
        self,
        *,
        policy_evaluation_id: uuid.UUID,
        transaction_intent_hash: str,
        institution_id: uuid.UUID,
        hold_reason: str,
        review_workflow: str = "FRAUD_INVESTIGATION",
        status: HoldStatus = HoldStatus.ACTIVE,
        transaction_id: uuid.UUID | None = None,
        resolved_by: str | None = None,
        resolution_notes: str | None = None,
        resolved_at: datetime | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.policy_evaluation_id = policy_evaluation_id
        self.transaction_intent_hash = transaction_intent_hash
        self.institution_id = institution_id
        self.hold_reason = hold_reason
        self.review_workflow = review_workflow
        self.status = status
        self.transaction_id = transaction_id
        self.resolved_by = resolved_by
        self.resolution_notes = resolution_notes
        self.resolved_at = resolved_at


class PolicyEvaluationRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Immutable audit record generated on every transaction policy evaluation."""

    __tablename__ = "policy_evaluations"

    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        comment="Client-supplied idempotency key for request deduplication",
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    transaction_intent_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="SHA-256 digest of canonical transaction intent",
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("policies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    policy_version: Mapped[int] = mapped_column(
        nullable=False,
    )
    decision: Mapped[PolicyOutcome] = mapped_column(
        Enum(PolicyOutcome, name="policy_outcome_enum", native_enum=False),
        nullable=False,
        index=True,
        comment="Authoritative outcome: ALLOW, STEP_UP, HOLD, or DECLINE",
    )
    reason_codes: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Stable machine-readable reason codes",
    )
    applicable_rule_ids: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Identifiers of internal policy rules triggered during evaluation",
    )
    evaluation_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Internal audit evidence, thresholds, and risk inputs for investigators",
    )
    step_up_challenge_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("step_up_challenges.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    hold_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("transaction_holds.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    spending_reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("spending_reservations.id", ondelete="SET NULL"),
        nullable=True,
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
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    # Relationships
    policy = relationship("Policy", lazy="selectin")
    agent = relationship("Agent", lazy="selectin")
    institution = relationship("Institution", lazy="selectin")
    step_up_challenge = relationship(
        "StepUpChallenge", foreign_keys=[step_up_challenge_id], lazy="selectin"
    )
    hold = relationship("TransactionHold", foreign_keys=[hold_id], lazy="selectin")
    spending_reservation = relationship(
        "SpendingReservation", foreign_keys=[spending_reservation_id], lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint(
            "institution_id",
            "idempotency_key",
            name="uq_policy_evaluations_institution_idempotency",
        ),
    )
