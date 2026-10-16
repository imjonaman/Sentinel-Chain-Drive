"""Banking and transaction domain schema

Revision ID: 20261016_0002
Revises: 20261016_0001
Create Date: 2026-10-16 12:30:00.000000+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261016_0002"
down_revision: str | None = "20261016_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Institutions
    op.create_table(
        "institutions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("institution_code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("routing_identifier", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_institutions")),
        sa.UniqueConstraint("institution_code", name=op.f("uq_institutions_institution_code")),
        sa.UniqueConstraint("routing_identifier", name=op.f("uq_institutions_routing_identifier")),
    )
    op.create_index(
        op.f("ix_institutions_institution_code"), "institutions", ["institution_code"], unique=True
    )
    op.create_index(
        op.f("ix_institutions_routing_identifier"),
        "institutions",
        ["routing_identifier"],
        unique=True,
    )
    op.create_index(op.f("ix_institutions_status"), "institutions", ["status"], unique=False)

    # 2. Accounts
    op.create_table(
        "accounts",
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
        sa.Column("account_number", sa.String(length=64), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("balance", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("risk_flags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name=op.f("fk_accounts_institution_id_institutions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.CheckConstraint("balance >= 0", name="ck_accounts_balance_non_negative"),
        sa.UniqueConstraint("institution_id", "account_number", name="uq_accounts_inst_acct_num"),
    )
    op.create_index(
        op.f("ix_accounts_institution_id"), "accounts", ["institution_id"], unique=False
    )
    op.create_index(op.f("ix_accounts_account_number"), "accounts", ["account_number"], unique=True)
    op.create_index(op.f("ix_accounts_status"), "accounts", ["status"], unique=False)

    # 3. Transactions
    op.create_table(
        "transactions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "origin_institution_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "origin_account_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "destination_institution_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "destination_account_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("transaction_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("purpose_code", sa.String(length=32), nullable=False),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=True,
        ),
        sa.Column("rejection_reason", sa.String(length=256), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("simulation_metadata", sa.JSON(), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["origin_institution_id"],
            ["institutions.id"],
            name=op.f("fk_transactions_origin_institution_id_institutions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["destination_institution_id"],
            ["institutions.id"],
            name=op.f("fk_transactions_destination_institution_id_institutions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["origin_account_id"],
            ["accounts.id"],
            name=op.f("fk_transactions_origin_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["destination_account_id"],
            ["accounts.id"],
            name=op.f("fk_transactions_destination_account_id_accounts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
    )
    op.create_index(
        op.f("ix_transactions_idempotency_key"), "transactions", ["idempotency_key"], unique=True
    )
    op.create_index(
        op.f("ix_transactions_origin_institution_id"),
        "transactions",
        ["origin_institution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transactions_destination_institution_id"),
        "transactions",
        ["destination_institution_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transactions_origin_account_id"),
        "transactions",
        ["origin_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transactions_destination_account_id"),
        "transactions",
        ["destination_account_id"],
        unique=False,
    )
    op.create_index(op.f("ix_transactions_status"), "transactions", ["status"], unique=False)
    op.create_index(op.f("ix_transactions_agent_id"), "transactions", ["agent_id"], unique=False)
    op.create_index(
        op.f("ix_transactions_correlation_id"), "transactions", ["correlation_id"], unique=False
    )

    # 4. Transaction Status History
    op.create_table(
        "transaction_status_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True).with_variant(sa.String(36), "sqlite"),
            nullable=False,
        ),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=256), nullable=True),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_transaction_status_history_transaction_id_transactions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transaction_status_history")),
    )
    op.create_index(
        op.f("ix_transaction_status_history_transaction_id"),
        "transaction_status_history",
        ["transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("transaction_status_history")
    op.drop_table("transactions")
    op.drop_table("accounts")
    op.drop_table("institutions")
