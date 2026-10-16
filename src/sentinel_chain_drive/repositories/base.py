"""Generic base repository defining standard parameterized query primitives."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.base import Base


class BaseRepository[ModelType: Base]:
    """Encapsulates common data-access methods with parameterized query execution."""

    def __init__(self, model: type[ModelType], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    async def get_by_id(self, entity_id: Any) -> ModelType | None:
        """Fetch a single record by primary key."""
        stmt = select(self.model).where(self.model.id == entity_id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self, limit: int = 100, offset: int = 0) -> Sequence[ModelType]:
        """Fetch a paginated list of records."""
        stmt = select(self.model).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def add(self, instance: ModelType) -> ModelType:
        """Stage an entity instance in the current session."""
        self.session.add(instance)
        await self.session.flush()
        return instance
