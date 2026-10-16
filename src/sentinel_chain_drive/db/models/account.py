"""Account domain model representing simulated customer and business bank accounts."""

import enum
import uuid
from decimal import Decimal

from sqlalchemy import JSON, CheckConstraint, Enum, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AccountStatus(enum.StrEnum):
    """Operational status of a simulated account."""

    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class AccountType(enum.StrEnum):
    """Classification of the simulated account."""

    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    COMMERCIAL = "COMMERCIAL"
    SETTLEMENT = "SETTLEMENT"


# Permitted lifecycle status transitions for accounts
VALID_ACCOUNT_TRANSITIONS: dict[AccountStatus, set[AccountStatus]] = {
    AccountStatus.ACTIVE: {AccountStatus.FROZEN, AccountStatus.CLOSED},
    AccountStatus.FROZEN: {AccountStatus.ACTIVE, AccountStatus.CLOSED},
    AccountStatus.CLOSED: set(),  # Terminal state: closed accounts cannot be reopened
}


class Account(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Simulated account owned by an institution."""

    __tablename__ = "accounts"

    institution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Owning institution identifier",
    )
    account_number: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        comment="Synthetic unique account identifier",
    )
    account_type: Mapped[AccountType] = mapped_column(
        Enum(AccountType, name="account_type_enum", native_enum=False),
        nullable=False,
        default=AccountType.CHECKING,
        comment="Account category",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
        comment="ISO 4217 three-letter currency code",
    )
    balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0.0000"),
        comment="Current ledger balance using exact decimal precision",
    )
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus, name="account_status_enum", native_enum=False),
        nullable=False,
        default=AccountStatus.ACTIVE,
        index=True,
        comment="Account operational status",
    )
    risk_flags: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="List of synthetic behavioral or operational risk tags",
    )

    # Relationships
    institution: Mapped["Institution"] = relationship(  # type: ignore[name-defined] # noqa: F821
        "Institution",
        back_populates="accounts",
    )

    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_accounts_balance_non_negative"),
        UniqueConstraint("institution_id", "account_number", name="uq_accounts_inst_acct_num"),
    )
