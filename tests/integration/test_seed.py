"""Integration tests for deterministic synthetic seed script."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.account import Account
from sentinel_chain_drive.db.models.institution import Institution
from sentinel_chain_drive.db.models.transaction import Transaction, TransactionStatusHistory
from sentinel_chain_drive.db.seed import seed_database


@pytest.mark.asyncio
async def test_seed_database_execution_and_idempotency(db_session: AsyncSession) -> None:
    """Verify seed populates expected fixtures and is fully idempotent."""
    # First seed run
    counts_1 = await seed_database(db_session)
    await db_session.commit()

    assert counts_1["institutions"] == 4
    assert counts_1["accounts"] == 7
    assert counts_1["transactions"] == 4

    # Verify institutions exist
    insts = (await db_session.scalars(select(Institution))).all()
    assert len(insts) == 4
    for inst in insts:
        assert inst.settings is not None
        assert inst.settings.get("synthetic") is True

    # Verify accounts exist and relate to institutions
    accounts = (await db_session.scalars(select(Account))).all()
    assert len(accounts) == 7
    for acct in accounts:
        assert acct.institution_id in [i.id for i in insts]

    # Verify transactions exist and have status history
    txs = (await db_session.scalars(select(Transaction))).all()
    assert len(txs) == 4
    for tx in txs:
        assert tx.simulation_metadata is not None
        assert tx.simulation_metadata.get("synthetic") is True
        hist = (
            await db_session.scalars(
                select(TransactionStatusHistory).where(
                    TransactionStatusHistory.transaction_id == tx.id
                )
            )
        ).all()
        assert len(hist) >= 2

    # Second seed run should be idempotent (0 new records created)
    counts_2 = await seed_database(db_session)
    await db_session.commit()

    assert counts_2["institutions"] == 0
    assert counts_2["accounts"] == 0
    assert counts_2["transactions"] == 0
