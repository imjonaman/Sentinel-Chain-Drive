"""Unit tests for Phase 9 Case Management domain models, state machine, and service."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.core.errors import AppException
from sentinel_chain_drive.db.models.account import Account, AccountType
from sentinel_chain_drive.db.models.case import (
    CaseCategory,
    CasePriority,
    CaseStatus,
    EvidenceType,
)
from sentinel_chain_drive.db.models.institution import Institution, InstitutionStatus
from sentinel_chain_drive.db.models.transaction import (
    Transaction,
    TransactionStatus,
    TransactionType,
)
from sentinel_chain_drive.schemas.case import (
    CaseAssignRequest,
    CaseCreateRequest,
    CaseEvidenceCreateRequest,
    CasePriorityUpdateRequest,
    CaseStatusTransitionRequest,
)
from sentinel_chain_drive.services.case_service import CaseService


async def _create_test_fixtures(session: AsyncSession) -> tuple[Institution, Account, Transaction]:
    """Helper creating basic institution, account, and settled transaction."""
    inst = Institution(
        name="Bank Alpha",
        institution_code=f"BA-{uuid.uuid4().hex[:6].upper()}",
        routing_identifier=f"021{uuid.uuid4().hex[:6]}",
        status=InstitutionStatus.ACTIVE,
    )
    session.add(inst)
    await session.flush()

    acct = Account(
        institution_id=inst.id,
        account_number=f"ACCT-{uuid.uuid4().hex[:8]}",
        account_type=AccountType.CHECKING,
        currency="USD",
    )
    session.add(acct)
    await session.flush()

    tx = Transaction(
        idempotency_key=f"tx-key-{uuid.uuid4().hex}",
        origin_institution_id=inst.id,
        origin_account_id=acct.id,
        destination_institution_id=inst.id,
        destination_account_id=acct.id,
        amount=Decimal("15000.00"),
        currency="USD",
        transaction_type=TransactionType.TRANSFER,
        status=TransactionStatus.SETTLED,
    )
    session.add(tx)
    await session.flush()

    return inst, acct, tx


@pytest.mark.asyncio
async def test_case_creation_and_idempotency(db_session: AsyncSession) -> None:
    """Verify case creation with transaction associations and idempotent deduplication."""
    inst, acct, tx = await _create_test_fixtures(db_session)
    service = CaseService(db_session)

    req = CaseCreateRequest(
        summary="Suspicious burst activity",
        description="High velocity transfers detected.",
        category=CaseCategory.FRAUD_ALERT,
        priority=CasePriority.HIGH,
        risk_score=85,
        source_type="ALERT",
        source_id="ALT-001",
        correlation_id=f"corr-{uuid.uuid4()}",
        transaction_ids=[tx.id],
        account_ids=[acct.id],
    )

    # 1. Create case
    case = await service.create_case(inst.id, req, actor="analyst_1")
    assert case.id is not None
    assert case.case_number.startswith("CASE-")
    assert case.status == CaseStatus.OPEN
    assert case.priority == CasePriority.HIGH
    assert case.risk_score == 85
    assert len(case.case_transactions) == 1
    assert len(case.case_accounts) == 1

    # 2. Idempotent submission with same source_type and source_id returns existing case
    case_dup = await service.create_case(inst.id, req, actor="analyst_1")
    assert case_dup.id == case.id
    assert case_dup.case_number == case.case_number


@pytest.mark.asyncio
async def test_case_state_machine_valid_progression(db_session: AsyncSession) -> None:
    """Verify valid state transitions from OPEN to RESOLVED."""
    inst, _, _ = await _create_test_fixtures(db_session)
    service = CaseService(db_session)

    case = await service.create_case(
        inst.id,
        CaseCreateRequest(
            summary="Test Case Flow",
            category=CaseCategory.MANUAL,
            source_type="MANUAL",
            source_id=f"src-{uuid.uuid4()}",
        ),
        actor="lead_analyst",
    )
    assert case.status == CaseStatus.OPEN

    # 1. OPEN -> UNDER_INVESTIGATION via assignment
    case = await service.assign_case(
        case.id,
        inst.id,
        CaseAssignRequest(assigned_analyst_id="investigator_bob", assigned_role="SENIOR_ANALYST"),
        actor="lead_analyst",
    )
    assert case.status == CaseStatus.UNDER_INVESTIGATION
    assert case.assigned_analyst_id == "investigator_bob"

    # 2. UNDER_INVESTIGATION -> IN_REVIEW
    case = await service.transition_status(
        case.id,
        inst.id,
        CaseStatusTransitionRequest(
            target_status=CaseStatus.IN_REVIEW,
            reason="Investigation complete, awaiting supervisor approval.",
        ),
        actor="investigator_bob",
    )
    assert case.status == CaseStatus.IN_REVIEW

    # 3. IN_REVIEW -> RESOLVED (Requires mandatory resolution notes and category)
    case = await service.transition_status(
        case.id,
        inst.id,
        CaseStatusTransitionRequest(
            target_status=CaseStatus.RESOLVED,
            reason="Fraud confirmed and mitigation coordinated.",
            resolution_category="CONFIRMED_FRAUD",
            resolution_notes="Funds halted at counterparty and account restricted.",
        ),
        actor="supervisor_carol",
    )
    assert case.status == CaseStatus.RESOLVED
    assert case.closed_at is not None
    assert case.closed_by == "supervisor_carol"
    assert case.resolution_category == "CONFIRMED_FRAUD"


@pytest.mark.asyncio
async def test_case_state_machine_invalid_transitions_rejected(
    db_session: AsyncSession,
) -> None:
    """Verify rejection of invalid state transitions not allowed by state machine."""
    inst, _, _ = await _create_test_fixtures(db_session)
    service = CaseService(db_session)

    case = await service.create_case(
        inst.id,
        CaseCreateRequest(
            summary="Invalid Transition Case",
            category=CaseCategory.MANUAL,
            source_type="MANUAL",
            source_id=f"src-{uuid.uuid4()}",
        ),
        actor="analyst_1",
    )
    assert case.status == CaseStatus.OPEN

    # Cannot transition directly from OPEN to RESOLVED
    with pytest.raises(AppException) as exc_info:
        await service.transition_status(
            case.id,
            inst.id,
            CaseStatusTransitionRequest(
                target_status=CaseStatus.RESOLVED,
                reason="Attempting immediate resolution without review",
                resolution_category="CONFIRMED_FRAUD",
                resolution_notes="Skipped review",
            ),
            actor="analyst_1",
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "INVALID_STATE_TRANSITION"


@pytest.mark.asyncio
async def test_mandatory_closure_and_reopening_rationale(db_session: AsyncSession) -> None:
    """Verify closure requires resolution fields and reopening requires supervisory reason."""
    inst, _, _ = await _create_test_fixtures(db_session)
    service = CaseService(db_session)

    case = await service.create_case(
        inst.id,
        CaseCreateRequest(
            summary="Closure Rationale Case",
            category=CaseCategory.MANUAL,
            source_type="MANUAL",
            source_id=f"src-{uuid.uuid4()}",
        ),
        actor="analyst_1",
    )

    # Move to UNDER_INVESTIGATION
    case.status = CaseStatus.UNDER_INVESTIGATION
    await db_session.flush()

    # 1. Missing resolution category or notes when closing raises 422
    with pytest.raises(AppException) as exc_info:
        await service.transition_status(
            case.id,
            inst.id,
            CaseStatusTransitionRequest(
                target_status=CaseStatus.CLOSED_BENIGN,
                reason="Closing without rationale",
            ),
            actor="analyst_1",
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "MANDATORY_RESOLUTION_RATIONALE"

    # Close with valid rationale
    case = await service.transition_status(
        case.id,
        inst.id,
        CaseStatusTransitionRequest(
            target_status=CaseStatus.CLOSED_BENIGN,
            reason="Verified benign customer activity",
            resolution_category="FALSE_POSITIVE",
            resolution_notes="Customer confirmed transaction directly.",
        ),
        actor="analyst_1",
    )
    assert case.status == CaseStatus.CLOSED_BENIGN

    # 2. Reopening without reopen_reason raises 422
    with pytest.raises(AppException) as exc_info:
        await service.transition_status(
            case.id,
            inst.id,
            CaseStatusTransitionRequest(
                target_status=CaseStatus.REOPENED,
                reason="Reopening without reason",
            ),
            actor="supervisor_1",
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "MANDATORY_REOPEN_RATIONALE"

    # Reopen with valid supervisory reason
    case = await service.transition_status(
        case.id,
        inst.id,
        CaseStatusTransitionRequest(
            target_status=CaseStatus.REOPENED,
            reason="New evidence surfaced from counterparty",
            reopen_reason="Counterparty flagged additional linked accounts.",
        ),
        actor="supervisor_1",
    )
    assert case.status == CaseStatus.REOPENED
    assert case.reopened_by == "supervisor_1"
    assert case.reopened_at is not None


@pytest.mark.asyncio
async def test_case_evidence_and_dossier_tamper_evidence(db_session: AsyncSession) -> None:
    """Verify evidence addition computes SHA-256 and dossier compilation succeeds."""
    inst, acct, tx = await _create_test_fixtures(db_session)
    service = CaseService(db_session)

    case = await service.create_case(
        inst.id,
        CaseCreateRequest(
            summary="Dossier Test Case",
            category=CaseCategory.POLICY_VIOLATION,
            source_type="TRANSACTION",
            source_id=str(tx.id),
            transaction_ids=[tx.id],
            account_ids=[acct.id],
        ),
        actor="analyst_1",
    )

    # Attach evidence
    evidence = await service.add_evidence(
        case.id,
        inst.id,
        CaseEvidenceCreateRequest(
            evidence_type=EvidenceType.GRAPH_SUBGRAPH,
            title="Mule Ring 3-Hop Subgraph",
            description="Graph path extracted during MuleChain cycle detection",
            reference_uri="/evidence/graph/2026/001.json",
            payload_json={"nodes": [str(acct.id)], "hops": 3},
        ),
        author="analyst_1",
    )
    assert evidence.checksum_sha256 is not None
    assert len(evidence.checksum_sha256) == 64

    # Add investigation note
    case = await service.add_note(
        case.id,
        inst.id,
        note_text="Investigator verified IP address match with known fraud cluster.",
        author="analyst_1",
    )
    assert len(case.notes_log) == 1

    # Escalate priority
    case = await service.update_priority(
        case.id,
        inst.id,
        CasePriorityUpdateRequest(
            priority=CasePriority.CRITICAL,
            reason="High value exposure and corroborated mule signal.",
        ),
        actor="analyst_1",
    )
    assert case.priority == CasePriority.CRITICAL

    # Compile dossier
    dossier = await service.compile_dossier(case.id, inst.id, compiled_by="auditor_dave")
    assert dossier.case_number == case.case_number
    assert dossier.dossier_hash_sha256 is not None
    assert len(dossier.dossier_hash_sha256) == 64
    assert len(dossier.transactions) == 1
    assert len(dossier.evidence_items) == 1
    # Check data minimization (masked account)
    assert len(dossier.accounts) == 1
    assert dossier.accounts[0]["account_number_masked"].startswith("***")
