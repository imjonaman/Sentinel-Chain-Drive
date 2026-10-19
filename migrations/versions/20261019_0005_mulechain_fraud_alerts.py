"""MuleChain fraud intelligence alerts schema

Revision ID: 20261019_0005
Revises: 20261019_0004
Create Date: 2026-10-19 14:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261019_0005"
down_revision: str | None = "20261019_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fraud_alerts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("alert_code", sa.String(length=64), nullable=False),
        sa.Column("detector_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="MEDIUM"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="NEW"),
        sa.Column("risk_score", sa.Integer(), nullable=False),
        sa.Column(
            "primary_institution_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "primary_account_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=True,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("analysis_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analysis_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "detection_rule_version",
            sa.String(length=32),
            nullable=False,
            server_default="v1.0",
        ),
        sa.Column(
            "scoring_model_version",
            sa.String(length=32),
            nullable=False,
            server_default="v1.0",
        ),
        sa.Column("evidence_data", sa.JSON(), nullable=False),
        sa.Column("dedup_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["primary_institution_id"],
            ["institutions.id"],
            name="fk_fraud_alerts_primary_institution_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["primary_account_id"],
            ["accounts.id"],
            name="fk_fraud_alerts_primary_account_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_fraud_alerts"),
        sa.UniqueConstraint(
            "primary_institution_id",
            "dedup_fingerprint",
            name="uq_fraud_alerts_institution_fingerprint",
        ),
    )
    op.create_index("ix_fraud_alerts_alert_code", "fraud_alerts", ["alert_code"])
    op.create_index("ix_fraud_alerts_detector_type", "fraud_alerts", ["detector_type"])
    op.create_index("ix_fraud_alerts_severity", "fraud_alerts", ["severity"])
    op.create_index("ix_fraud_alerts_status", "fraud_alerts", ["status"])
    op.create_index("ix_fraud_alerts_risk_score", "fraud_alerts", ["risk_score"])
    op.create_index(
        "ix_fraud_alerts_primary_institution_id",
        "fraud_alerts",
        ["primary_institution_id"],
    )
    op.create_index("ix_fraud_alerts_primary_account_id", "fraud_alerts", ["primary_account_id"])
    op.create_index("ix_fraud_alerts_dedup_fingerprint", "fraud_alerts", ["dedup_fingerprint"])
    op.create_index("ix_fraud_alerts_created_at", "fraud_alerts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_fraud_alerts_created_at", table_name="fraud_alerts")
    op.drop_index("ix_fraud_alerts_dedup_fingerprint", table_name="fraud_alerts")
    op.drop_index("ix_fraud_alerts_primary_account_id", table_name="fraud_alerts")
    op.drop_index("ix_fraud_alerts_primary_institution_id", table_name="fraud_alerts")
    op.drop_index("ix_fraud_alerts_risk_score", table_name="fraud_alerts")
    op.drop_index("ix_fraud_alerts_status", table_name="fraud_alerts")
    op.drop_index("ix_fraud_alerts_severity", table_name="fraud_alerts")
    op.drop_index("ix_fraud_alerts_detector_type", table_name="fraud_alerts")
    op.drop_index("ix_fraud_alerts_alert_code", table_name="fraud_alerts")
    op.drop_table("fraud_alerts")
