"""Data-access repository for Transaction domain entities and lifecycle status history."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sentinel_chain_drive.db.models.transaction import (
    Transaction,
    TransactionStatus,
    TransactionStatusHistory,
)
from sentinel_chain_drive.repositories.base import BaseRepository


class TransactionRepository(BaseRepository[Transaction]):
    """Encapsulates database operations for transactions and atomic status audit trails."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Transaction, session)

    async def get_by_idempotency_key(self, idempotency_key: str) -> Transaction | None:
        """Find an existing transaction by client idempotency key."""
        stmt = (
            select(Transaction)
            .options(selectinload(Transaction.status_history))
            .where(Transaction.idempotency_key == idempotency_key)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_history(self, transaction_id: uuid.UUID) -> Transaction | None:
        """Fetch a transaction along with its complete chronological status history."""
        stmt = (
            select(Transaction)
            .options(selectinload(Transaction.status_history))
            .where(Transaction.id == transaction_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_with_initial_history(
        self,
        transaction: Transaction,
        reason: str | None = None,
        actor: str = "system",
        correlation_id: str | None = None,
    ) -> Transaction:
        """Atomically persist a new transaction along with its initial status history entry."""
        self.session.add(transaction)
        await self.session.flush()

        history_entry = TransactionStatusHistory(
            transaction_id=transaction.id,
            previous_status=None,
            new_status=transaction.status.value
            if hasattr(transaction.status, "value")
            else str(transaction.status),
            reason=reason or "Initial transaction submission",
            actor=actor,
            correlation_id=correlation_id,
        )
        self.session.add(history_entry)
        await self.session.flush()
        return transaction

    async def update_status_with_history(
        self,
        transaction: Transaction,
        new_status: TransactionStatus,
        reason: str | None = None,
        actor: str = "system",
        correlation_id: str | None = None,
        settled_at: datetime | None = None,
    ) -> Transaction:
        """Atomically transition a transaction's status and append an audit history record."""
        previous_status = (
            transaction.status.value
            if hasattr(transaction.status, "value")
            else str(transaction.status)
        )
        transaction.status = new_status
        if settled_at is not None:
            transaction.settled_at = settled_at

        history_entry = TransactionStatusHistory(
            transaction_id=transaction.id,
            previous_status=previous_status,
            new_status=new_status.value if hasattr(new_status, "value") else str(new_status),
            reason=reason,
            actor=actor,
            correlation_id=correlation_id,
        )
        self.session.add(history_entry)
        await self.session.flush()
        return transaction

    async def list_paginated(
        self,
        limit: int = 50,
        offset: int = 0,
        institution_id: uuid.UUID | None = None,
        status: TransactionStatus | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> tuple[Sequence[Transaction], int]:
        """Fetch a paginated list of transactions with optional filters and total count."""
        base_query = select(Transaction).options(selectinload(Transaction.status_history))
        count_query = select(func.count()).select_from(Transaction)

        filters = []
        if institution_id is not None:
            inst_filter = or_(
                Transaction.origin_institution_id == institution_id,
                Transaction.destination_institution_id == institution_id,
            )
            filters.append(inst_filter)

        if status is not None:
            filters.append(Transaction.status == status)

        if from_time is not None:
            filters.append(Transaction.created_at >= from_time)

        if to_time is not None:
            filters.append(Transaction.created_at <= to_time)

        if filters:
            for f in filters:
                base_query = base_query.where(f)
                count_query = count_query.where(f)

        base_query = base_query.order_by(Transaction.created_at.desc()).limit(limit).offset(offset)

        items_result = await self.session.execute(base_query)
        total_result = await self.session.execute(count_query)

        items = items_result.scalars().all()
        total = total_result.scalar_one()
        return items, total
