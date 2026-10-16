"""Data-access repository for Capability domain entities."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.capability import Capability
from sentinel_chain_drive.repositories.base import BaseRepository


class CapabilityRepository(BaseRepository[Capability]):
    """Encapsulates database operations for agent capabilities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Capability, session)

    async def get_active_by_agent(self, agent_id: uuid.UUID) -> Sequence[Capability]:
        """Fetch all currently active capabilities assigned to an agent."""
        stmt = (
            select(Capability)
            .where(
                Capability.agent_id == agent_id,
                Capability.is_active.is_(True),
            )
            .order_by(Capability.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_paginated(
        self,
        limit: int = 50,
        offset: int = 0,
        agent_id: uuid.UUID | None = None,
        institution_id: uuid.UUID | None = None,
        is_active: bool | None = None,
    ) -> tuple[Sequence[Capability], int]:
        """Fetch a paginated list of capabilities with filters."""
        base_query = select(Capability)
        count_query = select(func.count()).select_from(Capability)

        if agent_id is not None:
            base_query = base_query.where(Capability.agent_id == agent_id)
            count_query = count_query.where(Capability.agent_id == agent_id)

        if institution_id is not None:
            base_query = base_query.where(Capability.institution_id == institution_id)
            count_query = count_query.where(Capability.institution_id == institution_id)

        if is_active is not None:
            base_query = base_query.where(Capability.is_active == is_active)
            count_query = count_query.where(Capability.is_active == is_active)

        base_query = base_query.order_by(Capability.created_at.desc()).limit(limit).offset(offset)

        items_result = await self.session.execute(base_query)
        total_result = await self.session.execute(count_query)

        items = items_result.scalars().all()
        total = total_result.scalar_one()

        return items, total
