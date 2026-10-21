"""Event processing reliability, stream ordering, and consumer idempotency schema

Revision ID: 20261021_0008
Revises: 20261020_0007
Create Date: 2026-10-21 10:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261021_0008"
down_revision: str | None = "20261020_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Extend drunix_outbox_events table with Phase 8 reliability and ordering columns
    with op.batch_alter_table("drunix_outbox_events") as batch_op:
        batch_op.add_column(
            sa.Column(
                "event_category",
                sa.String(length=32),
                nullable=False,
                server_default="DRUNIX_DELIVERY",
            )
        )
        batch_op.add_column(
            sa.Column(
                "causation_id",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "ordering_key",
                sa.String(length=128),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "sequence_number",
                sa.Integer(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "replay_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "last_replayed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "replayed_by",
                sa.String(length=128),
                nullable=True,
            )
        )
        batch_op.create_unique_constraint(
            "uq_drunix_outbox_ordering_seq",
            ["ordering_key", "sequence_number"],
        )

    # Indexes on drunix_outbox_events
    op.create_index(
        "ix_drunix_outbox_events_event_category",
        "drunix_outbox_events",
        ["event_category"],
    )
    op.create_index(
        "ix_drunix_outbox_events_causation_id",
        "drunix_outbox_events",
        ["causation_id"],
    )
    op.create_index(
        "ix_drunix_outbox_events_ordering_key",
        "drunix_outbox_events",
        ["ordering_key"],
    )
    op.create_index(
        "ix_drunix_outbox_events_ordering_seq",
        "drunix_outbox_events",
        ["ordering_key", "sequence_number"],
    )
    op.create_index(
        "ix_drunix_outbox_events_status_next_attempt",
        "drunix_outbox_events",
        ["status", "next_attempt_at"],
    )

    # 2. Create processed_events table for consumer idempotency tracking
    op.create_table(
        "processed_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "consumer_name",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "correlation_id",
            sa.String(length=64),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_processed_events_institutions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_processed_events"),
        sa.UniqueConstraint(
            "consumer_name",
            "event_id",
            name="uq_processed_events_consumer_event",
        ),
    )
    op.create_index(
        "ix_processed_events_consumer_name",
        "processed_events",
        ["consumer_name"],
    )
    op.create_index(
        "ix_processed_events_institution_id",
        "processed_events",
        ["institution_id"],
    )
    op.create_index(
        "ix_processed_events_event_id",
        "processed_events",
        ["event_id"],
    )


def downgrade() -> None:
    # Drop processed_events table and its indexes
    op.drop_index("ix_processed_events_event_id", table_name="processed_events")
    op.drop_index("ix_processed_events_institution_id", table_name="processed_events")
    op.drop_index("ix_processed_events_consumer_name", table_name="processed_events")
    op.drop_table("processed_events")

    # Drop indexes from drunix_outbox_events
    op.drop_index(
        "ix_drunix_outbox_events_status_next_attempt",
        table_name="drunix_outbox_events",
    )
    op.drop_index(
        "ix_drunix_outbox_events_ordering_seq",
        table_name="drunix_outbox_events",
    )
    op.drop_index(
        "ix_drunix_outbox_events_ordering_key",
        table_name="drunix_outbox_events",
    )
    op.drop_index(
        "ix_drunix_outbox_events_causation_id",
        table_name="drunix_outbox_events",
    )
    op.drop_index(
        "ix_drunix_outbox_events_event_category",
        table_name="drunix_outbox_events",
    )

    # Drop columns and constraints from drunix_outbox_events
    with op.batch_alter_table("drunix_outbox_events") as batch_op:
        batch_op.drop_constraint("uq_drunix_outbox_ordering_seq", type_="unique")
        batch_op.drop_column("replayed_by")
        batch_op.drop_column("last_replayed_at")
        batch_op.drop_column("replay_count")
        batch_op.drop_column("sequence_number")
        batch_op.drop_column("ordering_key")
        batch_op.drop_column("causation_id")
        batch_op.drop_column("event_category")
