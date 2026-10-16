"""Data-access repository for Account domain entities."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.account import Account, AccountStatus
from sentinel_chain_drive.repositories.base import BaseRepository


class AccountRepository(BaseRepository[Account]):
    """Encapsulates database operations for simulated accounts."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Account, session)

    async def get_by_number(self, account_number: str) -> Account | None:
        """Find an account by unique account number."""
        stmt = select(Account).where(Account.account_number == account_number)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_institution_and_id(
        self, institution_id: uuid.UUID, account_id: uuid.UUID
    ) -> Account | None:
        """Find an account scoped to an owning institution."""
        stmt = select(Account).where(
            Account.id == account_id,
            Account.institution_id == institution_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        limit: int = 50,
        offset: int = 0,
        institution_id: uuid.UUID | None = None,
        status: AccountStatus | None = None,
    ) -> tuple[Sequence[Account], int]:
        """Fetch a paginated list of accounts and total matching count."""
        base_query = select(Account)
        count_query = select(func.count()).select_from(Account)

        if institution_id is not None:
            base_query = base_query.where(Account.institution_id == institution_id)
            count_query = count_query.where(Account.institution_id == institution_id)

        if status is not None:
            base_query = base_query.where(Account.status == status)
            count_query = count_query.where(Account.status == status)

        base_query = base_query.order_by(Account.created_at.desc()).limit(limit).offset(offset)

        items_result = await self.session.execute(base_query)
        total_result = await self.session.execute(count_query)

        items = items_result.scalars().all()
        total = total_result.scalar_one()
        return items, total
