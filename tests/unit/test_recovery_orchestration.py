"""Unit tests for Phase 9 Recovery Request Orchestration, dual control, and simulated rails."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel_chain_drive.core.errors import AppException
from sentinel_chain_drive.db.models.account import Account, AccountType
from sentinel_chain_drive.db.models.case import CaseCategory, CaseStatus
from sentinel_chain_drive.db.models.institution import Institution, InstitutionStatus
from sentinel_chain_drive.db.models.recovery import RecoveryActionType, RecoveryStatus
from sentinel_chain_drive.db.models.transaction import (
    Transaction,
    TransactionStatus,
    TransactionType,
)
from sentinel_chain_drive.schemas.case import CaseCreateRequest
from sentinel_chain_drive.schemas.recovery import (
    RecoveryApprovalRequest,
    RecoveryReconcileRequest,
    RecoveryRejectionRequest,
    RecoveryRequestCreate,
    RecoverySubmissionRequest,
)
from sentinel_chain_drive.services.case_service import CaseService
from sentinel_chain_drive.services.recovery_service import RecoveryService


async def _create_test_fixtures(
    session: AsyncSession,
) -> tuple[Institution, Institution, Account, Transaction]:
    """Helper creating origin and target institutions, account, and transaction."""
    inst_origin = Institution(
        name="Origin Bank",
        institution_code=f"OB-{uuid.uuid4().hex[:6].upper()}",
        routing_identifier=f"021{uuid.uuid4().hex[:6]}",
        status=InstitutionStatus.ACTIVE,
    )
    inst_target = Institution(
        name="Target Bank",
        institution_code=f"TB-{uuid.uuid4().hex[:6].upper()}",
        routing_identifier=f"022{uuid.uuid4().hex[:6]}",
        status=InstitutionStatus.ACTIVE,
    )
    session.add_all([inst_origin, inst_target])
    await session.flush()

    acct = Account(
        institution_id=inst_origin.id,
        account_number=f"ACCT-{uuid.uuid4().hex[:8]}",
        account_type=AccountType.CHECKING,
        currency="USD",
    )
    session.add(acct)
    await session.flush()

    tx = Transaction(
        idempotency_key=f"tx-key-{uuid.uuid4().hex}",
        origin_institution_id=inst_origin.id,
        origin_account_id=acct.id,
        destination_institution_id=inst_target.id,
        destination_account_id=acct.id,
        amount=Decimal("45000.00"),
        currency="USD",
        transaction_type=TransactionType.TRANSFER,
        status=TransactionStatus.SETTLED,
    )
    session.add(tx)
    await session.flush()

    return inst_origin, inst_target, acct, tx


@pytest.mark.asyncio
async def test_recovery_request_creation_and_dual_control(db_session: AsyncSession) -> None:
    """Verify recovery request creation and strict dual control enforcement."""
    inst_origin, inst_target, acct, tx = await _create_test_fixtures(db_session)
    case_service = CaseService(db_session)
    recovery_service = RecoveryService(db_session)

    case = await case_service.create_case(
        inst_origin.id,
        CaseCreateRequest(
            summary="Recovery Test Case",
            category=CaseCategory.FRAUD_ALERT,
            source_type="ALERT",
            source_id=f"src-{uuid.uuid4()}",
            transaction_ids=[tx.id],
        ),
        actor="analyst_alice",
    )

    # 1. Draft recovery request
    req_payload = RecoveryRequestCreate(
        transaction_id=tx.id,
        target_institution_id=inst_target.id,
        amount=Decimal("45000.00"),
        currency="USD",
        action_type=RecoveryActionType.FUNDS_RECALL,
        rationale="Topological mule chain confirmed. Immediate funds recall requested.",
        idempotency_key=f"rec-key-{uuid.uuid4()}",
    )
    rec_req = await recovery_service.create_recovery_request(
        case.id,
        inst_origin.id,
        req_payload,
        requester_id="investigator_alice",
        requester_role="INVESTIGATOR",
    )
    assert rec_req.id is not None
    assert rec_req.request_number.startswith("REC-")
    assert rec_req.status == RecoveryStatus.PENDING_APPROVAL
    assert rec_req.requester_id == "investigator_alice"
    assert case.status == CaseStatus.PENDING_RECOVERY

    # 2. Dual control enforcement: Requester CANNOT approve their own request
    with pytest.raises(AppException) as exc_info:
        await recovery_service.approve_recovery_request(
            rec_req.id,
            inst_origin.id,
            RecoveryApprovalRequest(approval_notes="Self approval attempt"),
            approver_id="investigator_alice",  # Same as requester
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.error_code == "DUAL_CONTROL_VIOLATION"

    # 3. Authorized supervisor (different identity) approves
    approved = await recovery_service.approve_recovery_request(
        rec_req.id,
        inst_origin.id,
        RecoveryApprovalRequest(approval_notes="Confirmed unauthorized transfer. Approved."),
        approver_id="supervisor_bob",
        approver_role="SUPERVISOR",
    )
    assert approved.status == RecoveryStatus.APPROVED
    assert approved.approver_id == "supervisor_bob"
    assert approved.approved_at is not None


@pytest.mark.asyncio
async def test_recovery_submission_and_uncertain_outcome_reconciliation(
    db_session: AsyncSession,
) -> None:
    """Verify submission timeout handling to OUTCOME_UNKNOWN and subsequent reconciliation."""
    inst_origin, inst_target, acct, tx = await _create_test_fixtures(db_session)
    case_service = CaseService(db_session)
    recovery_service = RecoveryService(db_session)

    case = await case_service.create_case(
        inst_origin.id,
        CaseCreateRequest(
            summary="Timeout Test Case",
            category=CaseCategory.FRAUD_ALERT,
            source_type="ALERT",
            source_id=f"src-{uuid.uuid4()}",
            transaction_ids=[tx.id],
        ),
        actor="analyst_alice",
    )

    rec_req = await recovery_service.create_recovery_request(
        case.id,
        inst_origin.id,
        RecoveryRequestCreate(
            transaction_id=tx.id,
            target_institution_id=inst_target.id,
            amount=Decimal("10000.00"),
            currency="USD",
            action_type=RecoveryActionType.FUNDS_RECALL,
            rationale="Uncertain outcome flow testing.",
            idempotency_key=f"rec-key-{uuid.uuid4()}",
        ),
        requester_id="investigator_alice",
    )

    # Approve
    await recovery_service.approve_recovery_request(
        rec_req.id,
        inst_origin.id,
        RecoveryApprovalRequest(approval_notes="Approved for submission"),
        approver_id="supervisor_bob",
    )

    # Submit with simulated TIMEOUT outcome
    submitted = await recovery_service.submit_recovery_request(
        rec_req.id,
        inst_origin.id,
        RecoverySubmissionRequest(
            target_rail="FEDNOW",
            idempotency_key=f"sub-key-{uuid.uuid4()}",
            simulated_outcome="TIMEOUT",
        ),
        actor="operator_dan",
    )
    assert submitted.status == RecoveryStatus.OUTCOME_UNKNOWN
    assert submitted.submission_attempt_count == 1

    # Reconcile OUTCOME_UNKNOWN -> SETTLED
    reconciled = await recovery_service.reconcile_recovery_request(
        submitted.id,
        inst_origin.id,
        RecoveryReconcileRequest(
            reconciliation_status="SETTLED",
            reconciliation_notes="Received counterparty MT103 confirmation via manual channel.",
        ),
        actor="reconciliation_officer_eve",
    )
    assert reconciled.status == RecoveryStatus.SETTLED
    assert reconciled.reconciled_by == "reconciliation_officer_eve"
    assert reconciled.reconciled_at is not None


@pytest.mark.asyncio
async def test_recovery_rejection_and_closed_case_protection(
    db_session: AsyncSession,
) -> None:
    """Verify rejection flow and guard against drafting recovery for closed cases."""
    inst_origin, inst_target, acct, tx = await _create_test_fixtures(db_session)
    case_service = CaseService(db_session)
    recovery_service = RecoveryService(db_session)

    case = await case_service.create_case(
        inst_origin.id,
        CaseCreateRequest(
            summary="Rejection Case",
            category=CaseCategory.FRAUD_ALERT,
            source_type="ALERT",
            source_id=f"src-{uuid.uuid4()}",
            transaction_ids=[tx.id],
        ),
        actor="analyst_alice",
    )

    rec_req = await recovery_service.create_recovery_request(
        case.id,
        inst_origin.id,
        RecoveryRequestCreate(
            transaction_id=tx.id,
            target_institution_id=inst_target.id,
            amount=Decimal("5000.00"),
            currency="USD",
            action_type=RecoveryActionType.ACCOUNT_FREEZE_REQUEST,
            rationale="Test rejection flow.",
            idempotency_key=f"rec-key-{uuid.uuid4()}",
        ),
        requester_id="investigator_alice",
    )

    # Reject recovery request
    rejected = await recovery_service.reject_recovery_request(
        rec_req.id,
        inst_origin.id,
        RecoveryRejectionRequest(rejection_reason="Transaction already settled outside window."),
        rejected_by="supervisor_bob",
    )
    assert rejected.status == RecoveryStatus.REJECTED
    assert rejected.rejected_by == "supervisor_bob"

    # Now close the case
    case.status = CaseStatus.RESOLVED
    case.closed_by = "supervisor_bob"
    case.resolution_category = "INCONCLUSIVE"
    case.resolution_notes = "Case concluded without recovery."
    await db_session.flush()

    # Attempting to draft a new recovery request on a closed case must fail
    with pytest.raises(AppException) as exc_info:
        await recovery_service.create_recovery_request(
            case.id,
            inst_origin.id,
            RecoveryRequestCreate(
                transaction_id=tx.id,
                target_institution_id=inst_target.id,
                amount=Decimal("5000.00"),
                currency="USD",
                action_type=RecoveryActionType.FUNDS_RECALL,
                rationale="Should fail because case is closed.",
                idempotency_key=f"rec-key-{uuid.uuid4()}",
            ),
            requester_id="investigator_alice",
        )
    assert exc_info.value.status_code == 400
    assert exc_info.value.error_code == "CASE_CLOSED"
