"""Case management models for investigation workflows and evidentiary tracking."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CaseStatus(enum.StrEnum):
    """Investigation lifecycle statuses for a fraud case."""

    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    IN_REVIEW = "IN_REVIEW"
    ESCALATED = "ESCALATED"
    PENDING_RECOVERY = "PENDING_RECOVERY"
    RESOLVED = "RESOLVED"
    CLOSED_FRAUD = "CLOSED_FRAUD"
    CLOSED_BENIGN = "CLOSED_BENIGN"
    REOPENED = "REOPENED"


class CasePriority(enum.StrEnum):
    """Priority and severity levels for cases."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CaseCategory(enum.StrEnum):
    """Categorical classification of originating source."""

    FRAUD_ALERT = "FRAUD_ALERT"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    SUSPICIOUS_TRANSACTION = "SUSPICIOUS_TRANSACTION"
    MANUAL = "MANUAL"


class EvidenceType(enum.StrEnum):
    """Type of evidentiary artifacts attached to an investigation."""

    TRANSACTION_RECORD = "TRANSACTION_RECORD"
    GRAPH_SUBGRAPH = "GRAPH_SUBGRAPH"
    AGENT_SIGNATURE = "AGENT_SIGNATURE"
    POLICY_EVALUATION = "POLICY_EVALUATION"
    LEDGER_RECEIPT = "LEDGER_RECEIPT"
    EXTERNAL_DOCUMENT = "EXTERNAL_DOCUMENT"
    DOSSIER_PACKAGE = "DOSSIER_PACKAGE"


VALID_CASE_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.OPEN: {
        CaseStatus.UNDER_INVESTIGATION,
        CaseStatus.IN_REVIEW,
        CaseStatus.ESCALATED,
        CaseStatus.CLOSED_BENIGN,
    },
    CaseStatus.UNDER_INVESTIGATION: {
        CaseStatus.IN_REVIEW,
        CaseStatus.ESCALATED,
        CaseStatus.PENDING_RECOVERY,
        CaseStatus.CLOSED_BENIGN,
        CaseStatus.CLOSED_FRAUD,
        CaseStatus.RESOLVED,
    },
    CaseStatus.IN_REVIEW: {
        CaseStatus.UNDER_INVESTIGATION,
        CaseStatus.ESCALATED,
        CaseStatus.PENDING_RECOVERY,
        CaseStatus.CLOSED_BENIGN,
        CaseStatus.CLOSED_FRAUD,
        CaseStatus.RESOLVED,
    },
    CaseStatus.ESCALATED: {
        CaseStatus.UNDER_INVESTIGATION,
        CaseStatus.IN_REVIEW,
        CaseStatus.PENDING_RECOVERY,
        CaseStatus.CLOSED_BENIGN,
        CaseStatus.CLOSED_FRAUD,
        CaseStatus.RESOLVED,
    },
    CaseStatus.PENDING_RECOVERY: {
        CaseStatus.UNDER_INVESTIGATION,
        CaseStatus.IN_REVIEW,
        CaseStatus.CLOSED_BENIGN,
        CaseStatus.CLOSED_FRAUD,
        CaseStatus.RESOLVED,
    },
    CaseStatus.CLOSED_BENIGN: {
        CaseStatus.REOPENED,
    },
    CaseStatus.CLOSED_FRAUD: {
        CaseStatus.REOPENED,
    },
    CaseStatus.RESOLVED: {
        CaseStatus.REOPENED,
    },
    CaseStatus.REOPENED: {
        CaseStatus.UNDER_INVESTIGATION,
        CaseStatus.IN_REVIEW,
        CaseStatus.ESCALATED,
        CaseStatus.CLOSED_BENIGN,
        CaseStatus.CLOSED_FRAUD,
        CaseStatus.RESOLVED,
    },
}

TERMINAL_CASE_STATUSES: set[CaseStatus] = {
    CaseStatus.CLOSED_BENIGN,
    CaseStatus.CLOSED_FRAUD,
    CaseStatus.RESOLVED,
}


class Case(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Investigation case compiling alerts, transactions, and evidence for analysts."""

    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("case_number", name="uq_cases_case_number"),
        UniqueConstraint(
            "institution_id",
            "source_type",
            "source_id",
            name="uq_cases_institution_source",
        ),
        Index("ix_cases_institution_status", "institution_id", "status"),
        Index("ix_cases_priority", "priority"),
        Index("ix_cases_assigned_analyst", "assigned_analyst_id"),
        Index("ix_cases_correlation_id", "correlation_id"),
    )

    case_number: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Human-readable unique case identifier, e.g. CASE-2026-0001",
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Owning financial institution",
    )
    category: Mapped[CaseCategory] = mapped_column(
        Enum(CaseCategory, name="case_category_enum", native_enum=False),
        nullable=False,
        default=CaseCategory.MANUAL,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="MANUAL",
        index=True,
        comment="Originating source type: FRAUD_ALERT, POLICY_EVALUATION, TRANSACTION, MANUAL",
    )
    source_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        comment="Identifier of originating source entity for idempotency",
    )
    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, name="case_status_enum", native_enum=False),
        nullable=False,
        default=CaseStatus.OPEN,
    )
    priority: Mapped[CasePriority] = mapped_column(
        Enum(CasePriority, name="case_priority_enum", native_enum=False),
        nullable=False,
        default=CasePriority.MEDIUM,
    )
    risk_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Calculated or assigned risk score (0-100)",
    )
    summary: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Concise summary of suspicious pattern or investigation reason",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Detailed investigation narrative or background",
    )
    assigned_analyst_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="Identifier of assigned human investigator or analyst",
    )
    assigned_role: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Role tier of assigned investigator (e.g. INVESTIGATOR, SUPERVISOR)",
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Tracing correlation ID associated with originating event",
    )
    resolution_category: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="Closure resolution: CONFIRMED_FRAUD, FALSE_POSITIVE, POLICY_EXCUSED, INCONCLUSIVE",
    )
    resolution_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Mandatory closure notes explaining conclusion rationale",
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when case was resolved or closed",
    )
    closed_by: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="Actor who closed the case",
    )
    reopened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of latest reopening",
    )
    reopened_by: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="Actor who authorized reopening",
    )
    reopen_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Audited reason for reopening a closed case",
    )
    notes_log: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Chronological list of investigation comments and notes",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Structured metadata and external indicators",
    )

    # Relationships
    institution = relationship("Institution", lazy="selectin")
    case_transactions = relationship(
        "CaseTransaction", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )
    case_alerts = relationship(
        "CaseAlert", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )
    case_accounts = relationship(
        "CaseAccount", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )
    evidence_items = relationship(
        "CaseEvidence", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )
    history_records = relationship(
        "CaseStatusHistory", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )
    recovery_requests = relationship(
        "RecoveryRequest", back_populates="case", cascade="all, delete-orphan", lazy="selectin"
    )


class CaseTransaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Junction entity associating a transaction with an investigation case."""

    __tablename__ = "case_transactions"
    __table_args__ = (
        UniqueConstraint("case_id", "transaction_id", name="uq_case_transactions_case_tx"),
        Index("ix_case_transactions_case_id", "case_id"),
        Index("ix_case_transactions_transaction_id", "transaction_id"),
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
    relation_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="PRIMARY",
        comment="Role in case: PRIMARY, RELATED, SUSPICIOUS_BURST, RECOVERY_TARGET",
    )
    added_by: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="system",
    )

    case = relationship("Case", back_populates="case_transactions")
    transaction = relationship("Transaction", lazy="selectin")


class CaseAlert(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Junction entity associating a fraud alert with an investigation case."""

    __tablename__ = "case_alerts"
    __table_args__ = (
        UniqueConstraint("case_id", "alert_id", name="uq_case_alerts_case_alert"),
        Index("ix_case_alerts_case_id", "case_id"),
        Index("ix_case_alerts_alert_id", "alert_id"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("fraud_alerts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="PRIMARY",
        comment="Role in case: PRIMARY, CORRELATED, HISTORICAL",
    )
    added_by: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="system",
    )

    case = relationship("Case", back_populates="case_alerts")
    alert = relationship("FraudAlert", lazy="selectin")


class CaseAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Junction entity associating an account with an investigation case."""

    __tablename__ = "case_accounts"
    __table_args__ = (
        UniqueConstraint("case_id", "account_id", name="uq_case_accounts_case_account"),
        Index("ix_case_accounts_case_id", "case_id"),
        Index("ix_case_accounts_account_id", "account_id"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="MULE_SUSPECT",
        comment="Role: SOURCE, DESTINATION, MULE_SUSPECT, INTERMEDIARY, VICTIM",
    )
    added_by: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="system",
    )

    case = relationship("Case", back_populates="case_accounts")
    account = relationship("Account", lazy="selectin")


class CaseEvidence(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Evidentiary record attached to an investigation case."""

    __tablename__ = "case_evidence"
    __table_args__ = (
        Index("ix_case_evidence_case_id", "case_id"),
        Index("ix_case_evidence_type", "evidence_type"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(
        Enum(EvidenceType, name="evidence_type_enum", native_enum=False),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    reference_uri: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment="Safe non-executable URI or internal system reference ID",
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Structured evidence attributes (sanitized, non-sensitive)",
    )
    checksum_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="SHA-256 digest of payload for tamper evidence",
    )
    added_by: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    case = relationship("Case", back_populates="evidence_items")


class CaseStatusHistory(Base, UUIDPrimaryKeyMixin):
    """Immutable transition history tracking all case state changes."""

    __tablename__ = "case_status_history"
    __table_args__ = (
        Index("ix_case_status_history_case_id", "case_id"),
        Index("ix_case_status_history_created_at", "created_at"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Investigator, supervisor, or system process initiating change",
    )
    from_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    to_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    transition_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="STATUS_CHANGE",
        comment="STATUS_CHANGE, ASSIGNMENT, ESCALATION, CLOSURE, REOPEN",
    )
    reason: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Mandatory reason justifying the transition",
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

    case = relationship("Case", back_populates="history_records")
