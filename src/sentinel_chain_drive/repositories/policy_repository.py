"""Data-access repository for versioned transaction authorization policies."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.policy import Policy
from sentinel_chain_drive.repositories.base import BaseRepository


class PolicyRepository(BaseRepository[Policy]):
    """Encapsulates persistence operations for policy specifications and versioning."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Policy, session)

    async def get_by_code_and_version(
        self,
        institution_id: uuid.UUID | None,
        policy_code: str,
        version: int,
    ) -> Policy | None:
        """Fetch exact policy version scoped to institution or global."""
        stmt = select(Policy).where(
            Policy.policy_code == policy_code,
            Policy.version == version,
        )
        if institution_id is None:
            stmt = stmt.where(Policy.institution_id.is_(None))
        else:
            stmt = stmt.where(Policy.institution_id == institution_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_policy(
        self,
        institution_id: uuid.UUID | None,
        policy_code: str | None = None,
    ) -> Policy | None:
        """Fetch the active policy for an institution, falling back to global baseline.

        Ordered by priority ascending (lower integer indicates higher precedence)
        and version descending.
        """
        # 1. First check institution-specific active policy
        if institution_id is not None:
            stmt = select(Policy).where(
                Policy.institution_id == institution_id,
                Policy.is_active.is_(True),
            )
            if policy_code:
                stmt = stmt.where(Policy.policy_code == policy_code)
            stmt = stmt.order_by(Policy.priority.asc(), Policy.version.desc()).limit(1)
            result = await self.session.execute(stmt)
            inst_policy = result.scalar_one_or_none()
            if inst_policy is not None:
                return inst_policy

        # 2. Fall back to global default policy (institution_id is None)
        stmt = select(Policy).where(
            Policy.institution_id.is_(None),
            Policy.is_active.is_(True),
        )
        if policy_code:
            stmt = stmt.where(Policy.policy_code == policy_code)
        stmt = stmt.order_by(Policy.priority.asc(), Policy.version.desc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_next_version(
        self,
        institution_id: uuid.UUID | None,
        policy_code: str,
    ) -> int:
        """Compute the next version number for a policy family."""
        stmt = select(func.coalesce(func.max(Policy.version), 0)).where(
            Policy.policy_code == policy_code
        )
        if institution_id is None:
            stmt = stmt.where(Policy.institution_id.is_(None))
        else:
            stmt = stmt.where(Policy.institution_id == institution_id)
        result = await self.session.execute(stmt)
        max_ver = result.scalar_one()
        return int(max_ver) + 1

    async def deactivate_previous_versions(
        self,
        institution_id: uuid.UUID | None,
        policy_code: str,
        current_active_id: uuid.UUID,
    ) -> None:
        """Deactivate all versions of a policy code except the specified newly active one."""
        stmt = select(Policy).where(
            Policy.policy_code == policy_code,
            Policy.id != current_active_id,
            Policy.is_active.is_(True),
        )
        if institution_id is None:
            stmt = stmt.where(Policy.institution_id.is_(None))
        else:
            stmt = stmt.where(Policy.institution_id == institution_id)
        result = await self.session.execute(stmt)
        for old_policy in result.scalars().all():
            old_policy.is_active = False
        await self.session.flush()

    async def list_policies(
        self,
        limit: int = 50,
        offset: int = 0,
        institution_id: uuid.UUID | None = None,
        is_active: bool | None = None,
        include_global: bool = True,
    ) -> tuple[Sequence[Policy], int]:
        """Paginated list of policies with optional filters."""
        stmt = select(Policy)
        count_stmt = select(func.count()).select_from(Policy)

        conditions = []
        if institution_id is not None:
            if include_global:
                conditions.append(
                    or_(Policy.institution_id == institution_id, Policy.institution_id.is_(None))
                )
            else:
                conditions.append(Policy.institution_id == institution_id)
        elif not include_global:
            conditions.append(Policy.institution_id.is_not(None))

        if is_active is not None:
            conditions.append(Policy.is_active == is_active)

        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)

        stmt = stmt.order_by(Policy.priority.asc(), Policy.policy_code.asc(), Policy.version.desc())
        stmt = stmt.offset(offset).limit(limit)

        items_res = await self.session.execute(stmt)
        total_res = await self.session.execute(count_stmt)
        return items_res.scalars().all(), total_res.scalar_one()
