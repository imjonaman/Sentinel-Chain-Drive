"""AgentID and capability registry schema

Revision ID: 20261016_0003
Revises: 20261016_0002
Create Date: 2026-10-16 19:40:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261016_0003"
down_revision: str | None = "20261016_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Agents table
    op.create_table(
        "agents",
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
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=256), nullable=True),
        sa.Column("owner_contact", sa.String(length=128), nullable=False),
        sa.Column(
            "agent_type",
            sa.String(length=32),
            nullable=False,
            server_default="AUTONOMOUS_PAYMENT_AGENT",
        ),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("key_algorithm", sa.String(length=16), nullable=False, server_default="Ed25519"),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="PENDING_APPROVAL",
        ),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_agents_institution_id_institutions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agents"),
    )
    op.create_index("ix_agents_institution_id", "agents", ["institution_id"])
    op.create_index("ix_agents_status", "agents", ["status"])

    # 2. Capabilities table
    op.create_table(
        "capabilities",
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
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=256), nullable=True),
        sa.Column("permitted_transaction_types", sa.JSON(), nullable=False),
        sa.Column("permitted_currencies", sa.JSON(), nullable=False),
        sa.Column("max_amount_per_transaction", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("max_daily_cumulative_amount", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("allowed_origin_accounts", sa.JSON(), nullable=True),
        sa.Column("allowed_destination_accounts", sa.JSON(), nullable=True),
        sa.Column("purpose_codes", sa.JSON(), nullable=True),
        sa.Column("operating_start_hour_utc", sa.Integer(), nullable=True),
        sa.Column("operating_end_hour_utc", sa.Integer(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_capabilities_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_capabilities_institution_id_institutions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_capabilities"),
    )
    op.create_index("ix_capabilities_agent_id", "capabilities", ["agent_id"])
    op.create_index("ix_capabilities_institution_id", "capabilities", ["institution_id"])
    op.create_index("ix_capabilities_is_active", "capabilities", ["is_active"])

    # 3. Agent Credentials table
    op.create_table(
        "agent_credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("credential_id", sa.String(length=64), nullable=False),
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
        sa.Column("issuer_id", sa.String(length=128), nullable=False),
        sa.Column("audience", sa.String(length=128), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("algorithm", sa.String(length=16), nullable=False, server_default="Ed25519"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=256), nullable=True),
        sa.Column("claims", sa.JSON(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_agent_credentials_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_agent_credentials_institution_id_institutions",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_agent_credentials"),
        sa.UniqueConstraint("credential_id", name="uq_agent_credentials_credential_id"),
    )
    op.create_index("ix_agent_credentials_credential_id", "agent_credentials", ["credential_id"])
    op.create_index("ix_agent_credentials_agent_id", "agent_credentials", ["agent_id"])
    op.create_index("ix_agent_credentials_institution_id", "agent_credentials", ["institution_id"])
    op.create_index("ix_agent_credentials_expires_at", "agent_credentials", ["expires_at"])
    op.create_index("ix_agent_credentials_is_revoked", "agent_credentials", ["is_revoked"])

    # 4. Processed Nonces table
    op.create_table(
        "processed_nonces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("request_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_processed_nonces_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_processed_nonces"),
        sa.UniqueConstraint("nonce", name="uq_processed_nonces_nonce"),
    )
    op.create_index("ix_processed_nonces_nonce", "processed_nonces", ["nonce"])
    op.create_index("ix_processed_nonces_agent_id", "processed_nonces", ["agent_id"])
    op.create_index("ix_processed_nonces_expires_at", "processed_nonces", ["expires_at"])

    # 5. Authorization Records table
    op.create_table(
        "authorization_records",
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
        sa.Column("credential_id", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("decision_reasons", sa.JSON(), nullable=False),
        sa.Column("transaction_hash", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "capability_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=True,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_authorization_records_agent_id_agents",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_authorization_records_institution_id_institutions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["capability_id"],
            ["capabilities.id"],
            name="fk_authorization_records_capability_id_capabilities",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_authorization_records"),
    )
    op.create_index("ix_authorization_records_agent_id", "authorization_records", ["agent_id"])
    op.create_index(
        "ix_authorization_records_institution_id", "authorization_records", ["institution_id"]
    )
    op.create_index(
        "ix_authorization_records_credential_id", "authorization_records", ["credential_id"]
    )
    op.create_index(
        "ix_authorization_records_evaluated_at", "authorization_records", ["evaluated_at"]
    )


def downgrade() -> None:
    op.drop_table("authorization_records")
    op.drop_table("processed_nonces")
    op.drop_table("agent_credentials")
    op.drop_table("capabilities")
    op.drop_table("agents")
