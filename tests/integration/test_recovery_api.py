"""Integration tests for Phase 9 Recovery Request API, dual control, and reconciliation."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sentinel_chain_drive.db.models.account import Account, AccountType
from sentinel_chain_drive.db.models.institution import Institution, InstitutionStatus
from sentinel_chain_drive.db.models.transaction import (
    Transaction,
    TransactionStatus,
    TransactionType,
)


async def _seed_recovery_fixtures(
    sqlite_engine: AsyncEngine,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed test institutions, account, and transaction in the test database."""
    session_factory = async_sessionmaker(
        bind=sqlite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        inst_a = Institution(
            name="Bank Alpha",
            institution_code=f"BA-{uuid.uuid4().hex[:6].upper()}",
            routing_identifier=f"021{uuid.uuid4().hex[:6]}",
            status=InstitutionStatus.ACTIVE,
        )
        inst_b = Institution(
            name="Bank Beta",
            institution_code=f"BB-{uuid.uuid4().hex[:6].upper()}",
            routing_identifier=f"022{uuid.uuid4().hex[:6]}",
            status=InstitutionStatus.ACTIVE,
        )
        session.add_all([inst_a, inst_b])
        await session.flush()

        acct = Account(
            institution_id=inst_a.id,
            account_number=f"ACCT-{uuid.uuid4().hex[:8]}",
            account_type=AccountType.CHECKING,
            currency="USD",
        )
        session.add(acct)
        await session.flush()

        tx = Transaction(
            idempotency_key=f"tx-key-{uuid.uuid4().hex}",
            origin_institution_id=inst_a.id,
            origin_account_id=acct.id,
            destination_institution_id=inst_b.id,
            destination_account_id=acct.id,
            amount=Decimal("30000.00"),
            currency="USD",
            transaction_type=TransactionType.TRANSFER,
            status=TransactionStatus.SETTLED,
        )
        session.add(tx)
        await session.commit()

        return inst_a.id, inst_b.id, acct.id, tx.id


@pytest.mark.asyncio
async def test_recovery_request_full_workflow(
    client_with_db: AsyncClient,
    sqlite_engine: AsyncEngine,
) -> None:
    """Verify end-to-end recovery draft, dual-control approval, submit, and history tracking."""
    inst_a_id, inst_b_id, _, tx_id = await _seed_recovery_fixtures(sqlite_engine)
    headers_requester = {
        "X-Institution-ID": str(inst_a_id),
        "X-Actor-ID": "analyst_alice",
        "X-Actor-Role": "INVESTIGATOR",
    }

    # 1. Open Case
    case_resp = await client_with_db.post(
        "/api/v1/cases",
        headers=headers_requester,
        json={
            "summary": "Case for Recovery Flow",
            "category": "FRAUD_ALERT",
            "source_type": "ALERT",
            "source_id": f"alert-{uuid.uuid4()}",
            "transaction_ids": [str(tx_id)],
        },
    )
    assert case_resp.status_code == 201
    case_id = case_resp.json()["id"]

    # 2. Draft Recovery Request
    draft_resp = await client_with_db.post(
        f"/api/v1/cases/{case_id}/recovery-requests",
        headers=headers_requester,
        json={
            "transaction_id": str(tx_id),
            "target_institution_id": str(inst_b_id),
            "amount": "30000.00",
            "currency": "USD",
            "action_type": "FUNDS_RECALL",
            "rationale": "High confidence mule account destination. Recall requested.",
            "idempotency_key": f"rec-{uuid.uuid4()}",
        },
    )
    assert draft_resp.status_code == 201
    rec_data = draft_resp.json()
    request_id = rec_data["id"]
    assert rec_data["status"] == "PENDING_APPROVAL"
    assert rec_data["requester_id"] == "analyst_alice"

    # 3. Dual Control Enforcement: Requester attempts to approve their own request -> 403 Forbidden
    self_approve_resp = await client_with_db.post(
        f"/api/v1/recovery-requests/{request_id}/approve",
        headers=headers_requester,
        json={"approval_notes": "Attempting self approval"},
    )
    assert self_approve_resp.status_code == 403
    assert self_approve_resp.json()["error"]["code"] == "DUAL_CONTROL_VIOLATION"

    # 4. Cross-Tenant Isolation: Bank B cannot see Bank A's recovery request -> 404
    headers_bank_b = {"X-Institution-ID": str(inst_b_id), "X-Actor-ID": "supervisor_bob"}
    unauth_resp = await client_with_db.get(
        f"/api/v1/recovery-requests/{request_id}",
        headers=headers_bank_b,
    )
    assert unauth_resp.status_code == 404
    assert unauth_resp.json()["error"]["code"] == "RECOVERY_REQUEST_NOT_FOUND"

    # 5. Dual Control Valid Approval: Separate supervisor approves -> 200 OK
    headers_supervisor = {
        "X-Institution-ID": str(inst_a_id),
        "X-Actor-ID": "supervisor_charlie",
        "X-Actor-Role": "SUPERVISOR",
    }
    approve_resp = await client_with_db.post(
        f"/api/v1/recovery-requests/{request_id}/approve",
        headers=headers_supervisor,
        json={"approval_notes": "Dual-control authorized after evidentiary review."},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "APPROVED"
    assert approve_resp.json()["approver_id"] == "supervisor_charlie"

    # 6. Submit to Simulated Inter-Bank Rails
    headers_operator = {
        "X-Institution-ID": str(inst_a_id),
        "X-Actor-ID": "operator_dave",
    }
    submit_resp = await client_with_db.post(
        f"/api/v1/recovery-requests/{request_id}/submit",
        headers=headers_operator,
        json={
            "target_rail": "ACH",
            "idempotency_key": f"submit-{uuid.uuid4()}",
            "simulated_outcome": "ACKNOWLEDGE",
        },
    )
    assert submit_resp.status_code == 200
    sub_data = submit_resp.json()
    assert sub_data["status"] == "ACKNOWLEDGED"
    assert sub_data["external_reference"] is not None

    # 7. Reconcile to SETTLED
    reconcile_resp = await client_with_db.post(
        f"/api/v1/recovery-requests/{request_id}/reconcile",
        headers=headers_operator,
        json={
            "reconciliation_status": "SETTLED",
            "reconciliation_notes": "Funds credited back to origin account.",
        },
    )
    assert reconcile_resp.status_code == 200
    assert reconcile_resp.json()["status"] == "SETTLED"

    # 8. Check History Trail
    hist_resp = await client_with_db.get(
        f"/api/v1/recovery-requests/{request_id}/history",
        headers=headers_requester,
    )
    assert hist_resp.status_code == 200
    history = hist_resp.json()
    assert len(history) >= 4  # CREATE, APPROVE, SUBMIT/ACKNOWLEDGE, RECONCILE
