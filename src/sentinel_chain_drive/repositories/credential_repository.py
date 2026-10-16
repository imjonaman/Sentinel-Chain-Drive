"""Data-access repository for AgentCredential entities."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.agent_credential import AgentCredential
from sentinel_chain_drive.repositories.base import BaseRepository


class CredentialRepository(BaseRepository[AgentCredential]):
    """Encapsulates database operations for cryptographic credentials."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(AgentCredential, session)

    async def get_by_credential_id(self, credential_id: str) -> AgentCredential | None:
        """Find a credential by its unique public credential identifier."""
        stmt = select(AgentCredential).where(AgentCredential.credential_id == credential_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        limit: int = 50,
        offset: int = 0,
        agent_id: uuid.UUID | None = None,
        institution_id: uuid.UUID | None = None,
        is_revoked: bool | None = None,
    ) -> tuple[Sequence[AgentCredential], int]:
        """Fetch a paginated list of credentials with filters."""
        base_query = select(AgentCredential)
        count_query = select(func.count()).select_from(AgentCredential)

        if agent_id is not None:
            base_query = base_query.where(AgentCredential.agent_id == agent_id)
            count_query = count_query.where(AgentCredential.agent_id == agent_id)

        if institution_id is not None:
            base_query = base_query.where(AgentCredential.institution_id == institution_id)
            count_query = count_query.where(AgentCredential.institution_id == institution_id)

        if is_revoked is not None:
            base_query = base_query.where(AgentCredential.is_revoked == is_revoked)
            count_query = count_query.where(AgentCredential.is_revoked == is_revoked)

        base_query = (
            base_query.order_by(AgentCredential.created_at.desc()).limit(limit).offset(offset)
        )

        items_result = await self.session.execute(base_query)
        total_result = await self.session.execute(count_query)

        items = items_result.scalars().all()
        total = total_result.scalar_one()

        return items, total
