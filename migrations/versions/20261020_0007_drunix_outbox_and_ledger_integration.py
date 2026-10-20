"""DRUNIX outbox and ledger submissions schema

Revision ID: 20261020_0007
Revises: 20261019_0006
Create Date: 2026-10-20 10:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261020_0007"
down_revision: str | None = "20261019_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. drunix_outbox_events table
    op.create_table(
        "drunix_outbox_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column(
            "schema_version",
            sa.String(length=16),
            nullable=False,
            server_default="v1.0",
        ),
        sa.Column("aggregate_type", sa.String(length=32), nullable=False),
        sa.Column(
            "aggregate_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("commitment_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("receipt_reference", sa.String(length=128), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_drunix_outbox_institution_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_drunix_outbox_events"),
        sa.UniqueConstraint(
            "institution_id",
            "idempotency_key",
            name="uq_drunix_outbox_institution_idempotency",
        ),
    )
    op.create_index(
        "ix_drunix_outbox_events_institution_id",
        "drunix_outbox_events",
        ["institution_id"],
        unique=False,
    )
    op.create_index(
        "ix_drunix_outbox_events_event_type",
        "drunix_outbox_events",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_drunix_outbox_events_aggregate_type",
        "drunix_outbox_events",
        ["aggregate_type"],
        unique=False,
    )
    op.create_index(
        "ix_drunix_outbox_events_aggregate_id",
        "drunix_outbox_events",
        ["aggregate_id"],
        unique=False,
    )
    op.create_index(
        "ix_drunix_outbox_events_idempotency_key",
        "drunix_outbox_events",
        ["idempotency_key"],
        unique=False,
    )
    op.create_index(
        "ix_drunix_outbox_events_commitment_hash",
        "drunix_outbox_events",
        ["commitment_hash"],
        unique=False,
    )
    op.create_index(
        "ix_drunix_outbox_events_status",
        "drunix_outbox_events",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_drunix_outbox_events_next_attempt_at",
        "drunix_outbox_events",
        ["next_attempt_at"],
        unique=False,
    )
    op.create_index(
        "ix_drunix_outbox_events_locked_by",
        "drunix_outbox_events",
        ["locked_by"],
        unique=False,
    )
    op.create_index(
        "ix_drunix_outbox_events_correlation_id",
        "drunix_outbox_events",
        ["correlation_id"],
        unique=False,
    )

    # 2. drunix_ledger_submissions table
    op.create_table(
        "drunix_ledger_submissions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "outbox_event_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("submission_type", sa.String(length=32), nullable=False),
        sa.Column("commitment_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="SUBMITTED",
        ),
        sa.Column("tx_hash", sa.String(length=128), nullable=True),
        sa.Column(
            "attempt_number",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("receipt_data", sa.JSON(), nullable=True),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["outbox_event_id"],
            ["drunix_outbox_events.id"],
            name="fk_drunix_submissions_outbox_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_drunix_submissions_institution_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_drunix_ledger_submissions"),
    )
    op.create_index(
        "ix_drunix_ledger_submissions_outbox_event_id",
        "drunix_ledger_submissions",
        ["outbox_event_id"],
        unique=False,
    )
    op.create_index(
        "ix_drunix_ledger_submissions_institution_id",
        "drunix_ledger_submissions",
        ["institution_id"],
        unique=False,
    )
    op.create_index(
        "ix_drunix_ledger_submissions_submission_type",
        "drunix_ledger_submissions",
        ["submission_type"],
        unique=False,
    )
    op.create_index(
        "ix_drunix_ledger_submissions_commitment_hash",
        "drunix_ledger_submissions",
        ["commitment_hash"],
        unique=False,
    )
    op.create_index(
        "ix_drunix_ledger_submissions_status",
        "drunix_ledger_submissions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_drunix_ledger_submissions_tx_hash",
        "drunix_ledger_submissions",
        ["tx_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_drunix_ledger_submissions_tx_hash",
        table_name="drunix_ledger_submissions",
    )
    op.drop_index(
        "ix_drunix_ledger_submissions_status",
        table_name="drunix_ledger_submissions",
    )
    op.drop_index(
        "ix_drunix_ledger_submissions_commitment_hash",
        table_name="drunix_ledger_submissions",
    )
    op.drop_index(
        "ix_drunix_ledger_submissions_submission_type",
        table_name="drunix_ledger_submissions",
    )
    op.drop_index(
        "ix_drunix_ledger_submissions_institution_id",
        table_name="drunix_ledger_submissions",
    )
    op.drop_index(
        "ix_drunix_ledger_submissions_outbox_event_id",
        table_name="drunix_ledger_submissions",
    )
    op.drop_table("drunix_ledger_submissions")

    op.drop_index(
        "ix_drunix_outbox_events_correlation_id",
        table_name="drunix_outbox_events",
    )
    op.drop_index(
        "ix_drunix_outbox_events_locked_by",
        table_name="drunix_outbox_events",
    )
    op.drop_index(
        "ix_drunix_outbox_events_next_attempt_at",
        table_name="drunix_outbox_events",
    )
    op.drop_index(
        "ix_drunix_outbox_events_status",
        table_name="drunix_outbox_events",
    )
    op.drop_index(
        "ix_drunix_outbox_events_commitment_hash",
        table_name="drunix_outbox_events",
    )
    op.drop_index(
        "ix_drunix_outbox_events_idempotency_key",
        table_name="drunix_outbox_events",
    )
    op.drop_index(
        "ix_drunix_outbox_events_aggregate_id",
        table_name="drunix_outbox_events",
    )
    op.drop_index(
        "ix_drunix_outbox_events_aggregate_type",
        table_name="drunix_outbox_events",
    )
    op.drop_index(
        "ix_drunix_outbox_events_event_type",
        table_name="drunix_outbox_events",
    )
    op.drop_index(
        "ix_drunix_outbox_events_institution_id",
        table_name="drunix_outbox_events",
    )
    op.drop_table("drunix_outbox_events")
