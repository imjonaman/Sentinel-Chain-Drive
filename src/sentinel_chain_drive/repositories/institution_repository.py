"""Data-access repository for Institution domain entities."""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.institution import Institution, InstitutionStatus
from sentinel_chain_drive.repositories.base import BaseRepository


class InstitutionRepository(BaseRepository[Institution]):
    """Encapsulates database operations for financial institutions."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Institution, session)

    async def get_by_code(self, institution_code: str) -> Institution | None:
        """Find an institution by unique institution code."""
        stmt = select(Institution).where(Institution.institution_code == institution_code.upper())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_routing(self, routing_identifier: str) -> Institution | None:
        """Find an institution by synthetic routing identifier."""
        stmt = select(Institution).where(Institution.routing_identifier == routing_identifier)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        limit: int = 50,
        offset: int = 0,
        status: InstitutionStatus | None = None,
    ) -> tuple[Sequence[Institution], int]:
        """Fetch a paginated list of institutions and total matching count."""
        base_query = select(Institution)
        count_query = select(func.count()).select_from(Institution)

        if status is not None:
            base_query = base_query.where(Institution.status == status)
            count_query = count_query.where(Institution.status == status)

        base_query = (
            base_query.order_by(Institution.institution_code.asc()).limit(limit).offset(offset)
        )

        items_result = await self.session.execute(base_query)
        total_result = await self.session.execute(count_query)

        items = items_result.scalars().all()
        total = total_result.scalar_one()
        return items, total
