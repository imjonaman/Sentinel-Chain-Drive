"""Institution domain model for simulating independent financial institutions."""

import enum
from typing import Any

from sqlalchemy import JSON, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class InstitutionStatus(enum.StrEnum):
    """Lifecycle status for a simulated institution."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


# Allowed lifecycle status transitions for institutions
VALID_INSTITUTION_TRANSITIONS: dict[InstitutionStatus, set[InstitutionStatus]] = {
    InstitutionStatus.ACTIVE: {InstitutionStatus.SUSPENDED, InstitutionStatus.INACTIVE},
    InstitutionStatus.SUSPENDED: {InstitutionStatus.ACTIVE, InstitutionStatus.INACTIVE},
    # Terminal state: deactivated institutions cannot be reactivated
    InstitutionStatus.INACTIVE: set(),
}


class Institution(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Simulated financial institution boundary."""

    __tablename__ = "institutions"

    institution_code: Mapped[str] = mapped_column(
        String(16),
        unique=True,
        nullable=False,
        index=True,
        comment="Unique uppercase business identifier for the institution (e.g. APEX_BANK)",
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Human-readable organization display name",
    )
    routing_identifier: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
        index=True,
        comment="Synthetic routing transit or BIC code",
    )
    status: Mapped[InstitutionStatus] = mapped_column(
        Enum(InstitutionStatus, name="institution_status_enum", native_enum=False),
        nullable=False,
        default=InstitutionStatus.ACTIVE,
        index=True,
        comment="Operational lifecycle status",
    )
    settings: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Institution-specific simulation configuration and policy thresholds",
    )

    # Relationships
    accounts: Mapped[list["Account"]] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Account",
        back_populates="institution",
        cascade="all, delete-orphan",
    )
