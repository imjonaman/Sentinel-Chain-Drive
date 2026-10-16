"""Initial audit log schema

Revision ID: 20261016_0001
Revises:
Create Date: 2026-10-16 12:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261016_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "event_type",
            sa.String(length=64),
            nullable=False,
            comment="Categorical classification of the audit event",
        ),
        sa.Column(
            "severity",
            sa.String(length=16),
            nullable=False,
            comment="Log severity: INFO, WARNING, ERROR, CRITICAL",
        ),
        sa.Column(
            "actor",
            sa.String(length=128),
            nullable=False,
            comment="Entity or identifier responsible for initiating the event",
        ),
        sa.Column(
            "correlation_id",
            sa.String(length=64),
            nullable=True,
            comment="Associated HTTP request correlation ID",
        ),
        sa.Column(
            "description",
            sa.String(length=500),
            nullable=False,
            comment="Human-readable event summary",
        ),
        sa.Column("details", sa.JSON(), nullable=True, comment="Structured diagnostic context"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_event_type"), "audit_logs", ["event_type"], unique=False)
    op.create_index(op.f("ix_audit_logs_severity"), "audit_logs", ["severity"], unique=False)
    op.create_index(
        op.f("ix_audit_logs_correlation_id"), "audit_logs", ["correlation_id"], unique=False
    )
    op.create_index("ix_audit_logs_created_at_desc", "audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at_desc", table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_correlation_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_severity"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_event_type"), table_name="audit_logs")
    op.drop_table("audit_logs")
