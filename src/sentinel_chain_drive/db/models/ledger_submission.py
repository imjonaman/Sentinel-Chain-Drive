"""Historical ledger submissions and external attestation receipts.

Maintains immutable audit records of all DRUNIX submission attempts, external transaction
hashes, receipts, and reconciliation outcomes.
"""

import enum
import uuid
from typing import Any

from sqlalchemy import (
    JSON,
    Enum,
    ForeignKey,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from sentinel_chain_drive.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DrunixSubmissionStatus(enum.StrEnum):
    """External status for ledger submissions."""

    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"


class DrunixLedgerSubmission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Audit and tracking record for individual external DRUNIX ledger attempts."""

    __tablename__ = "drunix_ledger_submissions"

    outbox_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("drunix_outbox_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    institution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("institutions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    submission_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    commitment_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    status: Mapped[DrunixSubmissionStatus] = mapped_column(
        Enum(
            DrunixSubmissionStatus,
            name="drunix_submission_status_enum",
            native_enum=False,
        ),
        nullable=False,
        default=DrunixSubmissionStatus.SUBMITTED,
        index=True,
    )
    tx_hash: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    receipt_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    error_category: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )
