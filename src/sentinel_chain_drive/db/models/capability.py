"""Capability domain model defining granular authorization limits for AI agents."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Capability(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Granular authorization boundary assigned to an AI agent by an institution."""

    __tablename__ = "capabilities"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Permitted transaction scope
    permitted_transaction_types: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Allowed transaction types, e.g. ['DOMESTIC_TRANSFER', 'INTERNAL_TRANSFER']",
    )
    permitted_currencies: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="Allowed 3-letter currency codes, e.g. ['USD', 'EUR']",
    )

    # Monetary limits
    max_amount_per_transaction: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        comment="Upper bound for a single transaction amount",
    )
    max_daily_cumulative_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        comment="Rolling 24-hour cumulative spending ceiling",
    )

    # Whitelists / Restrictions (None implies unconstrained within institution)
    allowed_origin_accounts: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Optional whitelist of source account numbers",
    )
    allowed_destination_accounts: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Optional whitelist of destination account numbers",
    )
    purpose_codes: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Permitted business purpose codes, e.g. ['SUPPLIER_PAYMENT', 'PAYROLL']",
    )

    # Time restrictions (UTC hours 0-23)
    operating_start_hour_utc: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Inclusive start hour in UTC (0-23)",
    )
    operating_end_hour_utc: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Inclusive end hour in UTC (0-23)",
    )

    # Validity window
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    valid_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Lifecycle & Administrative Attribution
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Relationships
    agent = relationship("Agent", back_populates="capabilities")
    institution = relationship("Institution", lazy="selectin")
