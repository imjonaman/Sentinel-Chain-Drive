"""Cross-institution shared fraud intelligence indicator models."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IndicatorSeverity(enum.StrEnum):
    """Severity classification for shared intelligence indicators."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IndicatorStatus(enum.StrEnum):
    """Lifecycle status for shared intelligence indicators."""

    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class IndicatorType(enum.StrEnum):
    """Topological indicator pattern classifications."""

    MULE_BURST_INGRESS = "MULE_BURST_INGRESS"
    MULE_RAPID_PASSTHROUGH = "MULE_RAPID_PASSTHROUGH"
    MULE_FAN_OUT = "MULE_FAN_OUT"
    MULE_CIRCULAR_LAYERING = "MULE_CIRCULAR_LAYERING"
    SUSPICIOUS_MULE_ACCOUNT = "SUSPICIOUS_MULE_ACCOUNT"


class SharedIndicator(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Cross-institution shared fraud indicator with privacy-preserving MeshID."""

    __tablename__ = "shared_indicators"

    indicator_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        comment="Unique tracking code for the shared indicator, e.g. IND-20261019-XXXX",
    )
    schema_version: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="v1.0",
        comment="Indicator schema format version",
    )
    pseudonymous_mesh_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="Keyed HMAC-SHA256 pseudonym (MeshID) representing focal account",
    )
    originating_institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Authoritative financial institution that published the indicator",
    )
    target_institution_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Targeted recipient institution, or NULL for authorized network broadcast",
    )
    indicator_type: Mapped[IndicatorType] = mapped_column(
        Enum(IndicatorType, name="indicator_type_enum", native_enum=False),
        nullable=False,
        index=True,
        comment="Pattern classification type",
    )
    severity: Mapped[IndicatorSeverity] = mapped_column(
        Enum(IndicatorSeverity, name="indicator_severity_enum", native_enum=False),
        nullable=False,
        default=IndicatorSeverity.MEDIUM,
        index=True,
        comment="Assessed threat severity level",
    )
    confidence_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Confidence metric from 0.0 (unconfirmed) to 1.0 (verified anomaly)",
    )
    pattern_category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="High-level typology: TOPOLOGICAL_FAN_IN, TOPOLOGICAL_TRANSIT, etc.",
    )
    evidence_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Sanitized, non-sensitive evidence attributes conforming to disclosure allowlist",
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Detection source reliability, engine versions, and timestamps",
    )
    sharing_policy_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="v1.0",
        comment="Governing disclosure policy version",
    )
    status: Mapped[IndicatorStatus] = mapped_column(
        Enum(IndicatorStatus, name="indicator_status_enum", native_enum=False),
        nullable=False,
        default=IndicatorStatus.ACTIVE,
        index=True,
        comment="Indicator validity status",
    )
    revocation_reason: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment="Reason for voluntary indicator withdrawal or revocation",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when the indicator was revoked",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="Indicator time-to-live expiration timestamp",
    )

    originating_institution = relationship(
        "Institution",
        foreign_keys=[originating_institution_id],
        lazy="selectin",
    )
    target_institution = relationship(
        "Institution",
        foreign_keys=[target_institution_id],
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint(
            "originating_institution_id",
            "pseudonymous_mesh_id",
            "indicator_type",
            "sharing_policy_version",
            name="uq_shared_indicators_origin_mesh_type_policy",
        ),
    )
