"""Privacy Gateway shared indicators and audit schema

Revision ID: 20261019_0006
Revises: 20261019_0005
Create Date: 2026-10-19 16:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261019_0006"
down_revision: str | None = "20261019_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. shared_indicators table
    op.create_table(
        "shared_indicators",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("indicator_code", sa.String(length=64), nullable=False),
        sa.Column(
            "schema_version",
            sa.String(length=16),
            nullable=False,
            server_default="v1.0",
        ),
        sa.Column("pseudonymous_mesh_id", sa.String(length=64), nullable=False),
        sa.Column(
            "originating_institution_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "target_institution_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=True,
        ),
        sa.Column("indicator_type", sa.String(length=32), nullable=False),
        sa.Column(
            "severity",
            sa.String(length=16),
            nullable=False,
            server_default="MEDIUM",
        ),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("pattern_category", sa.String(length=64), nullable=False),
        sa.Column("evidence_summary", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column(
            "sharing_policy_version",
            sa.String(length=32),
            nullable=False,
            server_default="v1.0",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("revocation_reason", sa.String(length=256), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["originating_institution_id"],
            ["institutions.id"],
            name="fk_shared_indicators_originating_institution_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_institution_id"],
            ["institutions.id"],
            name="fk_shared_indicators_target_institution_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shared_indicators"),
        sa.UniqueConstraint(
            "originating_institution_id",
            "pseudonymous_mesh_id",
            "indicator_type",
            "sharing_policy_version",
            name="uq_shared_indicators_origin_mesh_type_policy",
        ),
    )
    op.create_index(
        "ix_shared_indicators_indicator_code",
        "shared_indicators",
        ["indicator_code"],
        unique=True,
    )
    op.create_index(
        "ix_shared_indicators_pseudonymous_mesh_id",
        "shared_indicators",
        ["pseudonymous_mesh_id"],
    )
    op.create_index(
        "ix_shared_indicators_originating_institution_id",
        "shared_indicators",
        ["originating_institution_id"],
    )
    op.create_index(
        "ix_shared_indicators_target_institution_id",
        "shared_indicators",
        ["target_institution_id"],
    )
    op.create_index(
        "ix_shared_indicators_indicator_type",
        "shared_indicators",
        ["indicator_type"],
    )
    op.create_index("ix_shared_indicators_severity", "shared_indicators", ["severity"])
    op.create_index(
        "ix_shared_indicators_pattern_category",
        "shared_indicators",
        ["pattern_category"],
    )
    op.create_index("ix_shared_indicators_status", "shared_indicators", ["status"])
    op.create_index("ix_shared_indicators_expires_at", "shared_indicators", ["expires_at"])
    op.create_index("ix_shared_indicators_created_at", "shared_indicators", ["created_at"])

    # 2. privacy_audit_logs table
    op.create_table(
        "privacy_audit_logs",
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
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("pseudonymous_mesh_id", sa.String(length=64), nullable=True),
        sa.Column(
            "indicator_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=True,
        ),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_privacy_audit_logs_institution_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["indicator_id"],
            ["shared_indicators.id"],
            name="fk_privacy_audit_logs_indicator_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_privacy_audit_logs"),
    )
    op.create_index(
        "ix_privacy_audit_logs_institution_id",
        "privacy_audit_logs",
        ["institution_id"],
    )
    op.create_index("ix_privacy_audit_logs_action", "privacy_audit_logs", ["action"])
    op.create_index(
        "ix_privacy_audit_logs_pseudonymous_mesh_id",
        "privacy_audit_logs",
        ["pseudonymous_mesh_id"],
    )
    op.create_index(
        "ix_privacy_audit_logs_indicator_id",
        "privacy_audit_logs",
        ["indicator_id"],
    )
    op.create_index(
        "ix_privacy_audit_logs_created_at",
        "privacy_audit_logs",
        ["created_at"],
    )


def downgrade() -> None:
    # 2. privacy_audit_logs
    op.drop_index("ix_privacy_audit_logs_created_at", table_name="privacy_audit_logs")
    op.drop_index("ix_privacy_audit_logs_indicator_id", table_name="privacy_audit_logs")
    op.drop_index("ix_privacy_audit_logs_pseudonymous_mesh_id", table_name="privacy_audit_logs")
    op.drop_index("ix_privacy_audit_logs_action", table_name="privacy_audit_logs")
    op.drop_index("ix_privacy_audit_logs_institution_id", table_name="privacy_audit_logs")
    op.drop_table("privacy_audit_logs")

    # 1. shared_indicators
    op.drop_index("ix_shared_indicators_created_at", table_name="shared_indicators")
    op.drop_index("ix_shared_indicators_expires_at", table_name="shared_indicators")
    op.drop_index("ix_shared_indicators_status", table_name="shared_indicators")
    op.drop_index("ix_shared_indicators_pattern_category", table_name="shared_indicators")
    op.drop_index("ix_shared_indicators_severity", table_name="shared_indicators")
    op.drop_index("ix_shared_indicators_indicator_type", table_name="shared_indicators")
    op.drop_index("ix_shared_indicators_target_institution_id", table_name="shared_indicators")
    op.drop_index("ix_shared_indicators_originating_institution_id", table_name="shared_indicators")
    op.drop_index("ix_shared_indicators_pseudonymous_mesh_id", table_name="shared_indicators")
    op.drop_index("ix_shared_indicators_indicator_code", table_name="shared_indicators")
    op.drop_table("shared_indicators")
