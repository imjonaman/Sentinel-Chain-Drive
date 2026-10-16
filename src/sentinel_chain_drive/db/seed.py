"""Deterministic synthetic data generator and database seed script.

Generates multi-institution, multi-account, and transaction test scenarios
for development and testing. All data is synthetic and deterministic.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.core.config import get_settings
from sentinel_chain_drive.db.models.account import Account, AccountStatus, AccountType
from sentinel_chain_drive.db.models.institution import Institution, InstitutionStatus
from sentinel_chain_drive.db.models.transaction import (
    Transaction,
    TransactionStatus,
    TransactionStatusHistory,
    TransactionType,
)
from sentinel_chain_drive.db.session import close_db, get_db_session

logger = logging.getLogger(__name__)

# Fixed deterministic UUIDs for seed records
INST_APEX_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
INST_BEACON_ID = uuid.UUID("10000000-0000-0000-0000-000000000002")
INST_CRESTLINE_ID = uuid.UUID("10000000-0000-0000-0000-000000000003")
INST_DORMANT_ID = uuid.UUID("10000000-0000-0000-0000-000000000004")

ACCT_APEX_01_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")
ACCT_APEX_02_ID = uuid.UUID("20000000-0000-0000-0000-000000000002")
ACCT_APEX_FROZEN_ID = uuid.UUID("20000000-0000-0000-0000-000000000003")

ACCT_BEACON_01_ID = uuid.UUID("20000000-0000-0000-0000-000000000011")
ACCT_BEACON_02_ID = uuid.UUID("20000000-0000-0000-0000-000000000012")
ACCT_BEACON_CLOSED_ID = uuid.UUID("20000000-0000-0000-0000-000000000013")

ACCT_CREST_01_ID = uuid.UUID("20000000-0000-0000-0000-000000000021")

TX_BENIGN_B2B_ID = uuid.UUID("30000000-0000-0000-0000-000000000001")
TX_HELD_REVIEW_ID = uuid.UUID("30000000-0000-0000-0000-000000000002")
TX_SETTLED_INTERNAL_ID = uuid.UUID("30000000-0000-0000-0000-000000000003")
TX_REJECTED_ID = uuid.UUID("30000000-0000-0000-0000-000000000004")


async def seed_database(session: AsyncSession) -> dict[str, int]:
    """Populate database with synthetic simulation fixtures in an idempotent manner."""
    created_institutions = 0
    created_accounts = 0
    created_transactions = 0

    # 1. Institutions
    institutions_data: list[dict[str, Any]] = [
        {
            "id": INST_APEX_ID,
            "institution_code": "APEX_BANK",
            "name": "Apex Commercial Bank",
            "routing_identifier": "11100001",
            "status": InstitutionStatus.ACTIVE,
            "settings": {"synthetic": True, "jurisdiction": "US", "tier": 1},
        },
        {
            "id": INST_BEACON_ID,
            "institution_code": "BEACON_TRUST",
            "name": "Beacon Trust & Savings",
            "routing_identifier": "11100002",
            "status": InstitutionStatus.ACTIVE,
            "settings": {"synthetic": True, "jurisdiction": "US", "tier": 2},
        },
        {
            "id": INST_CRESTLINE_ID,
            "institution_code": "CRESTLINE_BANK",
            "name": "Crestline State Bank",
            "routing_identifier": "11100003",
            "status": InstitutionStatus.SUSPENDED,
            "settings": {"synthetic": True, "jurisdiction": "US", "notes": "Regulatory audit hold"},
        },
        {
            "id": INST_DORMANT_ID,
            "institution_code": "DORMANT_MUTUAL",
            "name": "Dormant Mutual Credit",
            "routing_identifier": "11100004",
            "status": InstitutionStatus.INACTIVE,
            "settings": {"synthetic": True, "jurisdiction": "US", "notes": "Decommissioned"},
        },
    ]

    for item in institutions_data:
        existing = await session.scalar(select(Institution).where(Institution.id == item["id"]))
        if not existing:
            by_code = await session.scalar(
                select(Institution).where(Institution.institution_code == item["institution_code"])
            )
            if not by_code:
                inst = Institution(**item)
                session.add(inst)
                created_institutions += 1
    await session.flush()

    # 2. Accounts
    accounts_data: list[dict[str, Any]] = [
        # Apex accounts
        {
            "id": ACCT_APEX_01_ID,
            "institution_id": INST_APEX_ID,
            "account_number": "SYNTH-APEX-CHK-01",
            "account_type": AccountType.CHECKING,
            "status": AccountStatus.ACTIVE,
            "currency": "USD",
            "balance": Decimal("150000.0000"),
            "risk_flags": ["PRIMARY_TREASURY"],
        },
        {
            "id": ACCT_APEX_02_ID,
            "institution_id": INST_APEX_ID,
            "account_number": "SYNTH-APEX-SAV-02",
            "account_type": AccountType.SAVINGS,
            "status": AccountStatus.ACTIVE,
            "currency": "USD",
            "balance": Decimal("500000.0000"),
            "risk_flags": ["LIQUIDITY_RESERVE"],
        },
        {
            "id": ACCT_APEX_FROZEN_ID,
            "institution_id": INST_APEX_ID,
            "account_number": "SYNTH-APEX-FROZEN-03",
            "account_type": AccountType.CHECKING,
            "status": AccountStatus.FROZEN,
            "currency": "USD",
            "balance": Decimal("25000.0000"),
            "risk_flags": ["AML_INVESTIGATION_HOLD"],
        },
        # Beacon accounts
        {
            "id": ACCT_BEACON_01_ID,
            "institution_id": INST_BEACON_ID,
            "account_number": "SYNTH-BEACON-COMM-01",
            "account_type": AccountType.COMMERCIAL,
            "status": AccountStatus.ACTIVE,
            "currency": "USD",
            "balance": Decimal("1200000.0000"),
            "risk_flags": ["HIGH_VOLUME_COMMERCIAL"],
        },
        {
            "id": ACCT_BEACON_02_ID,
            "institution_id": INST_BEACON_ID,
            "account_number": "SYNTH-BEACON-CHK-02",
            "account_type": AccountType.CHECKING,
            "status": AccountStatus.ACTIVE,
            "currency": "USD",
            "balance": Decimal("80000.0000"),
            "risk_flags": [],
        },
        {
            "id": ACCT_BEACON_CLOSED_ID,
            "institution_id": INST_BEACON_ID,
            "account_number": "SYNTH-BEACON-CLOSED-03",
            "account_type": AccountType.CHECKING,
            "status": AccountStatus.CLOSED,
            "currency": "USD",
            "balance": Decimal("0.0000"),
            "risk_flags": ["TERMINATED_VENDOR"],
        },
        # Crestline account
        {
            "id": ACCT_CREST_01_ID,
            "institution_id": INST_CRESTLINE_ID,
            "account_number": "SYNTH-CREST-CHK-01",
            "account_type": AccountType.CHECKING,
            "status": AccountStatus.ACTIVE,
            "currency": "USD",
            "balance": Decimal("40000.0000"),
            "risk_flags": ["ESCROW_SUBACCOUNT"],
        },
    ]

    for item in accounts_data:
        existing = await session.scalar(select(Account).where(Account.id == item["id"]))
        if not existing:
            by_num = await session.scalar(
                select(Account).where(
                    Account.institution_id == item["institution_id"],
                    Account.account_number == item["account_number"],
                )
            )
            if not by_num:
                acct = Account(**item)
                session.add(acct)
                created_accounts += 1
    await session.flush()

    # 3. Transactions
    transactions_data: list[dict[str, Any]] = [
        # Benign cross-institution transfer
        {
            "id": TX_BENIGN_B2B_ID,
            "idempotency_key": "IDEMP-SEED-BENIGN-001",
            "origin_institution_id": INST_APEX_ID,
            "origin_account_id": ACCT_APEX_01_ID,
            "destination_institution_id": INST_BEACON_ID,
            "destination_account_id": ACCT_BEACON_01_ID,
            "amount": Decimal("1250.0000"),
            "currency": "USD",
            "transaction_type": TransactionType.TRANSFER,
            "status": TransactionStatus.PENDING_AUTHORIZATION,
            "purpose_code": "SUPPLIER_PAYMENT",
            "correlation_id": "CORR-SEED-001",
            "simulation_metadata": {
                "synthetic": True,
                "scenario": "benign_b2b_payment",
                "reference": "Invoice #SYNTH-9901",
                "risk_profile": "low",
            },
            "history": [
                {
                    "previous_status": None,
                    "new_status": TransactionStatus.SUBMITTED.value,
                    "reason": "Synthetic seed submission",
                },
                {
                    "previous_status": TransactionStatus.SUBMITTED.value,
                    "new_status": TransactionStatus.PENDING_AUTHORIZATION.value,
                    "reason": "Synthetic validation completed",
                },
            ],
        },
        # Held transfer for simulated fraud review
        {
            "id": TX_HELD_REVIEW_ID,
            "idempotency_key": "IDEMP-SEED-HELD-002",
            "origin_institution_id": INST_BEACON_ID,
            "origin_account_id": ACCT_BEACON_02_ID,
            "destination_institution_id": INST_APEX_ID,
            "destination_account_id": ACCT_APEX_01_ID,
            "amount": Decimal("15000.0000"),
            "currency": "USD",
            "transaction_type": TransactionType.TRANSFER,
            "status": TransactionStatus.HELD,
            "purpose_code": "EXPEDITED_TRANSFER",
            "correlation_id": "CORR-SEED-002",
            "simulation_metadata": {
                "synthetic": True,
                "scenario": "anomalous_velocity",
                "reference": "Urgent Consulting Advance",
                "risk_profile": "high",
            },
            "history": [
                {
                    "previous_status": None,
                    "new_status": TransactionStatus.SUBMITTED.value,
                    "reason": "Synthetic seed submission",
                },
                {
                    "previous_status": TransactionStatus.SUBMITTED.value,
                    "new_status": TransactionStatus.PENDING_AUTHORIZATION.value,
                    "reason": "Synthetic validation completed",
                },
                {
                    "previous_status": TransactionStatus.PENDING_AUTHORIZATION.value,
                    "new_status": TransactionStatus.HELD.value,
                    "reason": "Velocity threshold exceeded simulation trigger",
                },
            ],
        },
        # Settled internal transfer
        {
            "id": TX_SETTLED_INTERNAL_ID,
            "idempotency_key": "IDEMP-SEED-SETTLED-003",
            "origin_institution_id": INST_APEX_ID,
            "origin_account_id": ACCT_APEX_01_ID,
            "destination_institution_id": INST_APEX_ID,
            "destination_account_id": ACCT_APEX_02_ID,
            "amount": Decimal("10000.0000"),
            "currency": "USD",
            "transaction_type": TransactionType.BOOK_TRANSFER,
            "status": TransactionStatus.SETTLED,
            "purpose_code": "INTERNAL_REBALANCE",
            "correlation_id": "CORR-SEED-003",
            "simulation_metadata": {
                "synthetic": True,
                "scenario": "internal_book_transfer",
                "reference": "Synthetic liquidity rebalance",
                "risk_profile": "low",
            },
            "history": [
                {
                    "previous_status": None,
                    "new_status": TransactionStatus.SUBMITTED.value,
                    "reason": "Synthetic seed submission",
                },
                {
                    "previous_status": TransactionStatus.SUBMITTED.value,
                    "new_status": TransactionStatus.PENDING_AUTHORIZATION.value,
                    "reason": "Synthetic validation completed",
                },
                {
                    "previous_status": TransactionStatus.PENDING_AUTHORIZATION.value,
                    "new_status": TransactionStatus.SETTLED.value,
                    "reason": "Simulated pre-cleared settlement",
                },
            ],
        },
        # Rejected cross-institution transfer
        {
            "id": TX_REJECTED_ID,
            "idempotency_key": "IDEMP-SEED-REJECTED-004",
            "origin_institution_id": INST_APEX_ID,
            "origin_account_id": ACCT_APEX_01_ID,
            "destination_institution_id": INST_BEACON_ID,
            "destination_account_id": ACCT_BEACON_01_ID,
            "amount": Decimal("95000.0000"),
            "currency": "USD",
            "transaction_type": TransactionType.PAYMENT,
            "status": TransactionStatus.REJECTED,
            "purpose_code": "VENDOR_OVERSEAS",
            "correlation_id": "CORR-SEED-004",
            "simulation_metadata": {
                "synthetic": True,
                "scenario": "simulated_rejection",
                "reference": "Synthetic High Risk Wire",
                "risk_profile": "critical",
            },
            "history": [
                {
                    "previous_status": None,
                    "new_status": TransactionStatus.SUBMITTED.value,
                    "reason": "Synthetic seed submission",
                },
                {
                    "previous_status": TransactionStatus.SUBMITTED.value,
                    "new_status": TransactionStatus.PENDING_AUTHORIZATION.value,
                    "reason": "Synthetic validation completed",
                },
                {
                    "previous_status": TransactionStatus.PENDING_AUTHORIZATION.value,
                    "new_status": TransactionStatus.REJECTED.value,
                    "reason": "High-risk simulation reject",
                },
            ],
        },
    ]

    for item in transactions_data:
        existing = await session.scalar(select(Transaction).where(Transaction.id == item["id"]))
        if not existing:
            by_idemp = await session.scalar(
                select(Transaction).where(Transaction.idempotency_key == item["idempotency_key"])
            )
            if not by_idemp:
                history_list = item.pop("history")
                tx = Transaction(**item)
                session.add(tx)
                await session.flush()

                for h in history_list:
                    hist_entry = TransactionStatusHistory(
                        transaction_id=tx.id,
                        previous_status=h["previous_status"],
                        new_status=h["new_status"],
                        reason=h["reason"],
                        actor="SIMULATOR_SEED",
                        correlation_id=tx.correlation_id,
                    )
                    session.add(hist_entry)

                created_transactions += 1
    await session.flush()

    return {
        "institutions": created_institutions,
        "accounts": created_accounts,
        "transactions": created_transactions,
    }


async def async_main() -> None:
    """Async CLI runner."""
    settings = get_settings()
    logging.basicConfig(level=settings.LOG_LEVEL)
    logger.info("Starting deterministic synthetic seed...")
    try:
        async for session in get_db_session():
            counts = await seed_database(session)
            await session.commit()
            logger.info("Seed completed successfully: %s", counts)
            break
    finally:
        await close_db()


def main() -> None:
    """CLI entrypoint for database seeding."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
