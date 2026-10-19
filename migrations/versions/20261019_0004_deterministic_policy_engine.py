"""Deterministic policy engine schema

Revision ID: 20261019_0004
Revises: 20261016_0003
Create Date: 2026-10-19 12:00:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261019_0004"
down_revision: str | None = "20261016_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Policies table
    op.create_table(
        "policies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=True,
        ),
        sa.Column("policy_code", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=256), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", sa.String(length=128), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_policies_institution_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_policies"),
        sa.UniqueConstraint(
            "institution_id",
            "policy_code",
            "version",
            name="uq_policies_institution_code_version",
        ),
    )
    op.create_index("ix_policies_institution_id", "policies", ["institution_id"])
    op.create_index("ix_policies_policy_code", "policies", ["policy_code"])
    op.create_index("ix_policies_is_active", "policies", ["is_active"])

    # 2. Spending reservations table
    op.create_table(
        "spending_reservations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=True,
        ),
        sa.Column(
            "policy_evaluation_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=True,
        ),
        sa.Column("amount", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ACTIVE"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_spending_reservations_agent_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_spending_reservations_institution_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_spending_reservations_transaction_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_spending_reservations"),
    )
    op.create_index("ix_spending_reservations_agent_id", "spending_reservations", ["agent_id"])
    op.create_index(
        "ix_spending_reservations_institution_id", "spending_reservations", ["institution_id"]
    )
    op.create_index("ix_spending_reservations_status", "spending_reservations", ["status"])
    op.create_index("ix_spending_reservations_expires_at", "spending_reservations", ["expires_at"])

    # 3. Step-up challenges table
    op.create_table(
        "step_up_challenges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "policy_evaluation_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=True,
        ),
        sa.Column("transaction_intent_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "policy_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column(
            "initiating_agent_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "verification_type",
            sa.String(length=64),
            nullable=False,
            server_default="SUPERVISOR_APPROVAL",
        ),
        sa.Column(
            "required_role",
            sa.String(length=32),
            nullable=False,
            server_default="SUPERVISOR",
        ),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="PENDING"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approver_id", sa.String(length=128), nullable=True),
        sa.Column("decision_reason", sa.String(length=500), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["policies.id"],
            name="fk_step_up_challenges_policy_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["initiating_agent_id"],
            ["agents.id"],
            name="fk_step_up_challenges_initiating_agent_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_step_up_challenges_institution_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_step_up_challenges_transaction_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_step_up_challenges"),
    )
    op.create_index(
        "ix_step_up_challenges_policy_evaluation_id",
        "step_up_challenges",
        ["policy_evaluation_id"],
    )
    op.create_index(
        "ix_step_up_challenges_initiating_agent_id",
        "step_up_challenges",
        ["initiating_agent_id"],
    )
    op.create_index(
        "ix_step_up_challenges_institution_id", "step_up_challenges", ["institution_id"]
    )
    op.create_index("ix_step_up_challenges_status", "step_up_challenges", ["status"])
    op.create_index("ix_step_up_challenges_expires_at", "step_up_challenges", ["expires_at"])

    # 4. Transaction holds table
    op.create_table(
        "transaction_holds",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "policy_evaluation_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=True,
        ),
        sa.Column("transaction_intent_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("hold_reason", sa.String(length=256), nullable=False),
        sa.Column(
            "review_workflow",
            sa.String(length=64),
            nullable=False,
            server_default="FRAUD_INVESTIGATION",
        ),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="ACTIVE"),
        sa.Column("resolved_by", sa.String(length=128), nullable=True),
        sa.Column("resolution_notes", sa.String(length=500), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_transaction_holds_institution_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_transaction_holds_transaction_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transaction_holds"),
    )
    op.create_index(
        "ix_transaction_holds_policy_evaluation_id",
        "transaction_holds",
        ["policy_evaluation_id"],
    )
    op.create_index("ix_transaction_holds_institution_id", "transaction_holds", ["institution_id"])
    op.create_index("ix_transaction_holds_status", "transaction_holds", ["status"])

    # 5. Policy evaluations table
    op.create_table(
        "policy_evaluations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=True,
        ),
        sa.Column("transaction_intent_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "policy_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("applicable_rule_ids", sa.JSON(), nullable=False),
        sa.Column("evaluation_evidence", sa.JSON(), nullable=False),
        sa.Column(
            "step_up_challenge_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=True,
        ),
        sa.Column(
            "hold_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=True,
        ),
        sa.Column(
            "spending_reservation_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=True,
        ),
        sa.Column("amount", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_policy_evaluations_institution_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_policy_evaluations_agent_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["policies.id"],
            name="fk_policy_evaluations_policy_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name="fk_policy_evaluations_transaction_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["step_up_challenge_id"],
            ["step_up_challenges.id"],
            name="fk_policy_evaluations_step_up_challenge_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["hold_id"],
            ["transaction_holds.id"],
            name="fk_policy_evaluations_hold_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["spending_reservation_id"],
            ["spending_reservations.id"],
            name="fk_policy_evaluations_spending_reservation_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_policy_evaluations"),
        sa.UniqueConstraint(
            "institution_id",
            "idempotency_key",
            name="uq_policy_evaluations_institution_idempotency",
        ),
    )
    op.create_index(
        "ix_policy_evaluations_idempotency_key", "policy_evaluations", ["idempotency_key"]
    )
    op.create_index(
        "ix_policy_evaluations_institution_id", "policy_evaluations", ["institution_id"]
    )
    op.create_index("ix_policy_evaluations_agent_id", "policy_evaluations", ["agent_id"])
    op.create_index(
        "ix_policy_evaluations_transaction_id", "policy_evaluations", ["transaction_id"]
    )
    op.create_index("ix_policy_evaluations_decision", "policy_evaluations", ["decision"])
    op.create_index("ix_policy_evaluations_evaluated_at", "policy_evaluations", ["evaluated_at"])


def downgrade() -> None:
    op.drop_table("policy_evaluations")
    op.drop_table("transaction_holds")
    op.drop_table("step_up_challenges")
    op.drop_table("spending_reservations")
    op.drop_table("policies")
