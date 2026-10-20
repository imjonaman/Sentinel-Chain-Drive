"""Data access repositories for cross-institution shared intelligence and privacy audits."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.db.models.privacy_audit import (
    PrivacyAction,
    PrivacyAuditLog,
    PrivacyOutcome,
)
from sentinel_chain_drive.db.models.shared_indicator import (
    IndicatorStatus,
    SharedIndicator,
)


class SharedIndicatorRepository:
    """Repository managing persistence and scoped retrieval of shared fraud indicators."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, indicator_id: uuid.UUID) -> SharedIndicator | None:
        """Fetch raw indicator by ID without tenant access checks."""
        stmt = select(SharedIndicator).where(SharedIndicator.id == indicator_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_scoped(
        self,
        indicator_id: uuid.UUID,
        caller_institution_id: uuid.UUID,
    ) -> SharedIndicator | None:
        """Fetch indicator enforcing recipient access control.

        An institution is authorized to read an indicator if:
        1. It is the originating institution, OR
        2. The indicator was broadcast to all member banks (target_institution_id is NULL), OR
        3. The indicator was specifically targeted to the caller institution.
        """
        stmt = (
            select(SharedIndicator)
            .where(
                SharedIndicator.id == indicator_id,
                or_(
                    SharedIndicator.originating_institution_id == caller_institution_id,
                    SharedIndicator.target_institution_id.is_(None),
                    SharedIndicator.target_institution_id == caller_institution_id,
                ),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def publish_idempotent(
        self,
        indicator: SharedIndicator,
    ) -> tuple[SharedIndicator, bool]:
        """Publish a shared indicator idempotently.

        If an active indicator for the same (origin, mesh_id, type, policy_version) exists,
        its mutable fields (evidence summary, severity, confidence, expiration, recipient scope,
        provenance) are updated without duplicate rows.

        If the existing indicator was REVOKED, re-publishing under the same policy version is
        prohibited to prevent silent resurrection.

        Returns:
            tuple[SharedIndicator, bool]: (persisted_indicator, was_newly_created)
        Raises:
            ValueError: If an indicator with the same tuple was previously REVOKED.
        """
        stmt = select(SharedIndicator).where(
            SharedIndicator.originating_institution_id == indicator.originating_institution_id,
            SharedIndicator.pseudonymous_mesh_id == indicator.pseudonymous_mesh_id,
            SharedIndicator.indicator_type == indicator.indicator_type,
            SharedIndicator.sharing_policy_version == indicator.sharing_policy_version,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            if existing.status == IndicatorStatus.REVOKED:
                raise ValueError(
                    f"Cannot republish indicator: record {existing.indicator_code} was REVOKED "
                    f"under policy version '{indicator.sharing_policy_version}'. "
                    f"To update a revoked indicator, advance sharing_policy_version."
                )

            # Update mutable operational fields for ACTIVE indicator
            existing.evidence_summary = indicator.evidence_summary
            existing.severity = indicator.severity
            existing.confidence_score = indicator.confidence_score
            existing.expires_at = indicator.expires_at
            existing.provenance = indicator.provenance
            existing.target_institution_id = indicator.target_institution_id
            existing.pattern_category = indicator.pattern_category
            await self.session.flush()
            return existing, False

        self.session.add(indicator)
        await self.session.flush()
        return indicator, True

    async def query_by_mesh_id(
        self,
        pseudonymous_mesh_id: str,
        caller_institution_id: uuid.UUID,
        now: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[SharedIndicator], int]:
        """Query active, unexpired indicators matching a pseudonymous MeshID."""
        current_time = now or datetime.now(UTC)

        base_filter = [
            SharedIndicator.pseudonymous_mesh_id == pseudonymous_mesh_id,
            SharedIndicator.status == IndicatorStatus.ACTIVE,
            SharedIndicator.expires_at > current_time,
            or_(
                SharedIndicator.originating_institution_id == caller_institution_id,
                SharedIndicator.target_institution_id.is_(None),
                SharedIndicator.target_institution_id == caller_institution_id,
            ),
        ]

        count_stmt = select(func.count(SharedIndicator.id)).where(*base_filter)
        total_res = await self.session.execute(count_stmt)
        total = total_res.scalar_one()

        query_stmt = (
            select(SharedIndicator)
            .where(*base_filter)
            .order_by(SharedIndicator.created_at.desc(), SharedIndicator.id.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query_stmt)
        return result.scalars().all(), total

    async def revoke_indicator(
        self,
        indicator_id: uuid.UUID,
        originating_institution_id: uuid.UUID,
        reason: str,
        now: datetime | None = None,
    ) -> SharedIndicator | None:
        """Revoke a published indicator, enforcing originating institution ownership."""
        stmt = select(SharedIndicator).where(
            SharedIndicator.id == indicator_id,
            SharedIndicator.originating_institution_id == originating_institution_id,
        )
        result = await self.session.execute(stmt)
        indicator = result.scalar_one_or_none()
        if not indicator:
            return None

        current_time = now or datetime.now(UTC)
        indicator.status = IndicatorStatus.REVOKED
        indicator.revocation_reason = reason
        indicator.revoked_at = current_time
        await self.session.flush()
        return indicator


class PrivacyAuditRepository:
    """Repository for logging and querying privacy audit events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_event(
        self,
        institution_id: uuid.UUID,
        actor: str,
        action: PrivacyAction,
        outcome: PrivacyOutcome,
        details: dict[str, Any] | None = None,
        pseudonymous_mesh_id: str | None = None,
        indicator_id: uuid.UUID | None = None,
        correlation_id: str | None = None,
    ) -> PrivacyAuditLog:
        """Record an immutable privacy audit event."""
        log = PrivacyAuditLog(
            institution_id=institution_id,
            actor=actor,
            action=action,
            outcome=outcome,
            pseudonymous_mesh_id=pseudonymous_mesh_id,
            indicator_id=indicator_id,
            details=details or {},
            correlation_id=correlation_id,
            created_at=datetime.now(UTC),
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def list_for_institution(
        self,
        institution_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[Sequence[PrivacyAuditLog], int]:
        """Retrieve audit history for an institution."""
        count_stmt = select(func.count(PrivacyAuditLog.id)).where(
            PrivacyAuditLog.institution_id == institution_id
        )
        total_res = await self.session.execute(count_stmt)
        total = total_res.scalar_one()

        stmt = (
            select(PrivacyAuditLog)
            .where(PrivacyAuditLog.institution_id == institution_id)
            .order_by(PrivacyAuditLog.created_at.desc(), PrivacyAuditLog.id.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def get_summary_counts(self, institution_id: uuid.UUID) -> dict[str, int]:
        """Aggregate audit counts by action for an institution."""
        stmt = (
            select(PrivacyAuditLog.action, func.count(PrivacyAuditLog.id))
            .where(
                PrivacyAuditLog.institution_id == institution_id,
                PrivacyAuditLog.outcome == PrivacyOutcome.SUCCESS,
            )
            .group_by(PrivacyAuditLog.action)
        )
        result = await self.session.execute(stmt)
        counts = dict(result.all())
        revoked = counts.get(PrivacyAction.REVOKE, 0) + counts.get(PrivacyAction.WITHDRAW, 0)
        return {
            "published_count": counts.get(PrivacyAction.PUBLISH, 0),
            "queried_count": counts.get(PrivacyAction.QUERY, 0),
            "revoked_count": revoked,
        }

