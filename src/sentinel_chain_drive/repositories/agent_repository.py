"""Data-access repository for Agent entities."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.agent import Agent, AgentStatus
from sentinel_chain_drive.repositories.base import BaseRepository


class AgentRepository(BaseRepository[Agent]):
    """Encapsulates database operations for registered AI agents."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Agent, session)

    async def get_by_id(self, agent_id: uuid.UUID, for_update: bool = False) -> Agent | None:
        """Fetch an agent by primary key with optional pessimistic row locking."""
        stmt = select(Agent).where(Agent.id == agent_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_institution_and_id(
        self, institution_id: uuid.UUID, agent_id: uuid.UUID, for_update: bool = False
    ) -> Agent | None:
        """Find an agent scoped to an institution with optional row locking."""
        stmt = select(Agent).where(
            Agent.id == agent_id,
            Agent.institution_id == institution_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        limit: int = 50,
        offset: int = 0,
        institution_id: uuid.UUID | None = None,
        status: AgentStatus | None = None,
    ) -> tuple[Sequence[Agent], int]:
        """Fetch a paginated list of agents and total count."""
        base_query = select(Agent)
        count_query = select(func.count()).select_from(Agent)

        if institution_id is not None:
            base_query = base_query.where(Agent.institution_id == institution_id)
            count_query = count_query.where(Agent.institution_id == institution_id)

        if status is not None:
            base_query = base_query.where(Agent.status == status)
            count_query = count_query.where(Agent.status == status)

        base_query = base_query.order_by(Agent.created_at.desc()).limit(limit).offset(offset)

        items_result = await self.session.execute(base_query)
        total_result = await self.session.execute(count_query)

        items = items_result.scalars().all()
        total = total_result.scalar_one()

        return items, total
