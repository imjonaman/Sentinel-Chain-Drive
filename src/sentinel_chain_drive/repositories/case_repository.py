"""Repository for investigation cases, evidentiary links, and status history."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from sentinel_chain_drive.db.models.case import (
    Case,
    CaseAccount,
    CaseAlert,
    CaseCategory,
    CaseEvidence,
    CasePriority,
    CaseStatus,
    CaseStatusHistory,
    CaseTransaction,
    EvidenceType,
)
from sentinel_chain_drive.repositories.base import BaseRepository


class CaseRepository(BaseRepository[Case]):
    """Encapsulates database operations for cases, evidence, and lifecycle history."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Case, session)

    async def get_by_id_scoped(
        self,
        case_id: uuid.UUID,
        institution_id: uuid.UUID,
    ) -> Case | None:
        """Fetch case by ID ensuring strict tenant institution scoping."""
        stmt = (
            select(Case)
            .where(
                Case.id == case_id,
                Case.institution_id == institution_id,
            )
            .options(
                selectinload(Case.case_transactions).selectinload(CaseTransaction.transaction),
                selectinload(Case.case_alerts).selectinload(CaseAlert.alert),
                selectinload(Case.case_accounts).selectinload(CaseAccount.account),
                selectinload(Case.evidence_items),
                selectinload(Case.history_records),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_case_number(
        self,
        case_number: str,
        institution_id: uuid.UUID,
    ) -> Case | None:
        """Fetch case by human-readable case number within institution scope."""
        stmt = (
            select(Case)
            .where(
                Case.case_number == case_number,
                Case.institution_id == institution_id,
            )
            .options(
                selectinload(Case.case_transactions),
                selectinload(Case.case_alerts),
                selectinload(Case.case_accounts),
                selectinload(Case.evidence_items),
                selectinload(Case.history_records),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_source(
        self,
        institution_id: uuid.UUID,
        source_type: str,
        source_id: str,
    ) -> Case | None:
        """Fetch existing case by institution and originating source record for idempotency."""
        stmt = (
            select(Case)
            .where(
                Case.institution_id == institution_id,
                Case.source_type == source_type,
                Case.source_id == source_id,
            )
            .options(
                selectinload(Case.case_transactions),
                selectinload(Case.case_alerts),
                selectinload(Case.case_accounts),
                selectinload(Case.evidence_items),
                selectinload(Case.history_records),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def generate_case_number(self, institution_id: uuid.UUID) -> str:
        """Generate a sequential or unique case number for an institution."""
        current_year = datetime.now(UTC).year
        stmt = (
            select(func.count())
            .select_from(Case)
            .where(
                Case.institution_id == institution_id,
                Case.case_number.like(f"CASE-{current_year}-%"),
            )
        )
        result = await self.session.execute(stmt)
        count = result.scalar_one() or 0
        return f"CASE-{current_year}-{(count + 1):04d}"

    async def list_cases_scoped(
        self,
        institution_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
        status: CaseStatus | None = None,
        priority: CasePriority | None = None,
        category: CaseCategory | None = None,
        assigned_analyst_id: str | None = None,
    ) -> tuple[Sequence[Case], int]:
        """Fetch paginated cases strictly scoped to the caller's institution."""
        base_query = (
            select(Case)
            .where(Case.institution_id == institution_id)
            .options(
                selectinload(Case.case_transactions),
                selectinload(Case.case_alerts),
                selectinload(Case.case_accounts),
                selectinload(Case.evidence_items),
            )
        )
        count_query = (
            select(func.count()).select_from(Case).where(Case.institution_id == institution_id)
        )

        if status is not None:
            base_query = base_query.where(Case.status == status)
            count_query = count_query.where(Case.status == status)

        if priority is not None:
            base_query = base_query.where(Case.priority == priority)
            count_query = count_query.where(Case.priority == priority)

        if category is not None:
            base_query = base_query.where(Case.category == category)
            count_query = count_query.where(Case.category == category)

        if assigned_analyst_id is not None:
            base_query = base_query.where(Case.assigned_analyst_id == assigned_analyst_id)
            count_query = count_query.where(Case.assigned_analyst_id == assigned_analyst_id)

        base_query = base_query.order_by(Case.created_at.desc()).limit(limit).offset(offset)

        items_res = await self.session.execute(base_query)
        count_res = await self.session.execute(count_query)

        items = items_res.scalars().all()
        total = count_res.scalar_one() or 0
        return items, total

    async def add_transaction_association(
        self,
        case_id: uuid.UUID,
        transaction_id: uuid.UUID,
        relation_type: str = "PRIMARY",
        added_by: str = "system",
    ) -> CaseTransaction:
        """Link a transaction to a case if not already associated."""
        stmt = select(CaseTransaction).where(
            CaseTransaction.case_id == case_id,
            CaseTransaction.transaction_id == transaction_id,
        )
        res = await self.session.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing is not None:
            return existing

        link = CaseTransaction(
            case_id=case_id,
            transaction_id=transaction_id,
            relation_type=relation_type,
            added_by=added_by,
        )
        self.session.add(link)
        await self.session.flush()
        return link

    async def add_alert_association(
        self,
        case_id: uuid.UUID,
        alert_id: uuid.UUID,
        relation_type: str = "PRIMARY",
        added_by: str = "system",
    ) -> CaseAlert:
        """Link a fraud alert to a case if not already associated."""
        stmt = select(CaseAlert).where(
            CaseAlert.case_id == case_id,
            CaseAlert.alert_id == alert_id,
        )
        res = await self.session.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing is not None:
            return existing

        link = CaseAlert(
            case_id=case_id,
            alert_id=alert_id,
            relation_type=relation_type,
            added_by=added_by,
        )
        self.session.add(link)
        await self.session.flush()
        return link

    async def add_account_association(
        self,
        case_id: uuid.UUID,
        account_id: uuid.UUID,
        role: str = "MULE_SUSPECT",
        added_by: str = "system",
    ) -> CaseAccount:
        """Link an account to a case if not already associated."""
        stmt = select(CaseAccount).where(
            CaseAccount.case_id == case_id,
            CaseAccount.account_id == account_id,
        )
        res = await self.session.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing is not None:
            return existing

        link = CaseAccount(
            case_id=case_id,
            account_id=account_id,
            role=role,
            added_by=added_by,
        )
        self.session.add(link)
        await self.session.flush()
        return link

    async def add_evidence(
        self,
        case_id: uuid.UUID,
        evidence_type: EvidenceType,
        title: str,
        description: str | None,
        reference_uri: str | None,
        payload_json: dict[str, Any],
        checksum_sha256: str | None,
        added_by: str,
    ) -> CaseEvidence:
        """Attach an evidentiary item to a case."""
        evidence = CaseEvidence(
            case_id=case_id,
            evidence_type=evidence_type,
            title=title,
            description=description,
            reference_uri=reference_uri,
            payload_json=payload_json,
            checksum_sha256=checksum_sha256,
            added_by=added_by,
        )
        self.session.add(evidence)
        await self.session.flush()
        return evidence

    async def record_history(
        self,
        case_id: uuid.UUID,
        actor: str,
        from_status: str,
        to_status: str,
        transition_type: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> CaseStatusHistory:
        """Persist an immutable lifecycle transition log entry."""
        history = CaseStatusHistory(
            case_id=case_id,
            actor=actor,
            from_status=from_status,
            to_status=to_status,
            transition_type=transition_type,
            reason=reason,
            details=details or {},
        )
        self.session.add(history)
        await self.session.flush()
        return history

    async def get_case_history(self, case_id: uuid.UUID) -> Sequence[CaseStatusHistory]:
        """Retrieve chronological lifecycle history for a case."""
        stmt = (
            select(CaseStatusHistory)
            .where(CaseStatusHistory.case_id == case_id)
            .order_by(CaseStatusHistory.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_case_evidence(self, case_id: uuid.UUID) -> Sequence[CaseEvidence]:
        """Retrieve all evidentiary items attached to a case."""
        stmt = (
            select(CaseEvidence)
            .where(CaseEvidence.case_id == case_id)
            .order_by(CaseEvidence.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
