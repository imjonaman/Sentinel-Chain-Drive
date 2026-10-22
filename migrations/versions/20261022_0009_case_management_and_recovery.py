"""Case management and recovery orchestration schema

Revision ID: 20261022_0009
Revises: 20261021_0008
Create Date: 2026-10-22 10:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261022_0009"
down_revision: str | None = "20261021_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. cases
    op.create_table(
        "cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_number", sa.String(length=32), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("assigned_analyst_id", sa.String(length=128), nullable=True),
        sa.Column("assigned_role", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("resolution_category", sa.String(length=64), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by", sa.String(length=128), nullable=True),
        sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopened_by", sa.String(length=128), nullable=True),
        sa.Column("reopen_reason", sa.Text(), nullable=True),
        sa.Column("notes_log", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
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
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_number", name="uq_cases_case_number"),
        sa.UniqueConstraint(
            "institution_id",
            "source_type",
            "source_id",
            name="uq_cases_institution_source",
        ),
    )
    op.create_index("ix_cases_case_number", "cases", ["case_number"], unique=True)
    op.create_index("ix_cases_institution_id", "cases", ["institution_id"])
    op.create_index("ix_cases_institution_status", "cases", ["institution_id", "status"])
    op.create_index("ix_cases_category", "cases", ["category"])
    op.create_index("ix_cases_source_type", "cases", ["source_type"])
    op.create_index("ix_cases_source_id", "cases", ["source_id"])
    op.create_index("ix_cases_status", "cases", ["status"])
    op.create_index("ix_cases_priority", "cases", ["priority"])
    op.create_index("ix_cases_assigned_analyst", "cases", ["assigned_analyst_id"])
    op.create_index("ix_cases_correlation_id", "cases", ["correlation_id"])

    # 2. case_transactions
    op.create_table(
        "case_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False, server_default="PRIMARY"),
        sa.Column("added_by", sa.String(length=128), nullable=False, server_default="system"),
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
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "transaction_id", name="uq_case_transactions_case_tx"),
    )
    op.create_index("ix_case_transactions_case_id", "case_transactions", ["case_id"])
    op.create_index("ix_case_transactions_transaction_id", "case_transactions", ["transaction_id"])

    # 3. case_alerts
    op.create_table(
        "case_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False, server_default="PRIMARY"),
        sa.Column("added_by", sa.String(length=128), nullable=False, server_default="system"),
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
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["alert_id"], ["fraud_alerts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "alert_id", name="uq_case_alerts_case_alert"),
    )
    op.create_index("ix_case_alerts_case_id", "case_alerts", ["case_id"])
    op.create_index("ix_case_alerts_alert_id", "case_alerts", ["alert_id"])

    # 4. case_accounts
    op.create_table(
        "case_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="MULE_SUSPECT"),
        sa.Column("added_by", sa.String(length=128), nullable=False, server_default="system"),
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
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "account_id", name="uq_case_accounts_case_account"),
    )
    op.create_index("ix_case_accounts_case_id", "case_accounts", ["case_id"])
    op.create_index("ix_case_accounts_account_id", "case_accounts", ["account_id"])

    # 5. case_evidence
    op.create_table(
        "case_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reference_uri", sa.String(length=256), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("added_by", sa.String(length=128), nullable=False),
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
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_case_evidence_case_id", "case_evidence", ["case_id"])
    op.create_index("ix_case_evidence_type", "case_evidence", ["evidence_type"])

    # 6. case_status_history
    op.create_table(
        "case_status_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=False),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column(
            "transition_type", sa.String(length=32), nullable=False, server_default="STATUS_CHANGE"
        ),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_case_status_history_case_id", "case_status_history", ["case_id"])
    op.create_index("ix_case_status_history_created_at", "case_status_history", ["created_at"])

    # 7. recovery_requests
    op.create_table(
        "recovery_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_number", sa.String(length=32), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("requesting_institution_id", sa.Uuid(), nullable=False),
        sa.Column("target_institution_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("requester_id", sa.String(length=128), nullable=False),
        sa.Column(
            "requester_role", sa.String(length=64), nullable=False, server_default="INVESTIGATOR"
        ),
        sa.Column("approver_id", sa.String(length=128), nullable=True),
        sa.Column("approver_role", sa.String(length=64), nullable=True),
        sa.Column("approval_notes", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", sa.String(length=128), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("submission_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_reference", sa.String(length=128), nullable=True),
        sa.Column("reconciliation_status", sa.String(length=32), nullable=True),
        sa.Column("reconciliation_notes", sa.Text(), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_by", sa.String(length=128), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
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
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["requesting_institution_id"], ["institutions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_institution_id"], ["institutions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_number", name="uq_recovery_requests_number"),
        sa.UniqueConstraint(
            "requesting_institution_id",
            "idempotency_key",
            name="uq_recovery_requests_institution_idempotency",
        ),
    )
    op.create_index(
        "ix_recovery_requests_request_number", "recovery_requests", ["request_number"], unique=True
    )
    op.create_index("ix_recovery_requests_case_id", "recovery_requests", ["case_id"])
    op.create_index("ix_recovery_requests_transaction_id", "recovery_requests", ["transaction_id"])
    op.create_index(
        "ix_recovery_requests_requesting_inst", "recovery_requests", ["requesting_institution_id"]
    )
    op.create_index(
        "ix_recovery_requests_target_inst", "recovery_requests", ["target_institution_id"]
    )
    op.create_index("ix_recovery_requests_status", "recovery_requests", ["status"])
    op.create_index("ix_recovery_requests_requester", "recovery_requests", ["requester_id"])
    op.create_index("ix_recovery_requests_idempotency", "recovery_requests", ["idempotency_key"])

    # 8. recovery_status_history
    op.create_table(
        "recovery_status_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recovery_request_id", sa.Uuid(), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=False),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["recovery_request_id"], ["recovery_requests.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recovery_status_history_request_id",
        "recovery_status_history",
        ["recovery_request_id"],
    )
    op.create_index(
        "ix_recovery_status_history_created_at", "recovery_status_history", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("recovery_status_history")
    op.drop_table("recovery_requests")
    op.drop_table("case_status_history")
    op.drop_table("case_evidence")
    op.drop_table("case_accounts")
    op.drop_table("case_alerts")
    op.drop_table("case_transactions")
    op.drop_table("cases")
