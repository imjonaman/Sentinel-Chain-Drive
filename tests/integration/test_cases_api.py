"""Integration tests for Phase 9 Case Management API endpoints, isolation, and lifecycle."""

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


async def _seed_api_fixtures(
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
            amount=Decimal("25000.00"),
            currency="USD",
            transaction_type=TransactionType.TRANSFER,
            status=TransactionStatus.SETTLED,
        )
        session.add(tx)
        await session.commit()

        return inst_a.id, inst_b.id, acct.id, tx.id


@pytest.mark.asyncio
async def test_cases_api_full_investigation_lifecycle(
    client_with_db: AsyncClient,
    sqlite_engine: AsyncEngine,
) -> None:
    """Verify end-to-end case creation, assignment, evidence, and dossier compilation via API."""
    inst_a_id, inst_b_id, acct_id, tx_id = await _seed_api_fixtures(sqlite_engine)
    headers_a = {"X-Institution-ID": str(inst_a_id), "X-Actor-ID": "analyst_alice"}

    # 1. Create Case
    create_resp = await client_with_db.post(
        "/api/v1/cases",
        headers=headers_a,
        json={
            "summary": "Mule chain circular pattern detected",
            "description": "Suspicious burst outbound transfers to unknown account.",
            "category": "FRAUD_ALERT",
            "priority": "HIGH",
            "risk_score": 82,
            "source_type": "MULECHAIN",
            "source_id": "ALERT-MC-9001",
            "transaction_ids": [str(tx_id)],
            "account_ids": [str(acct_id)],
        },
    )
    assert create_resp.status_code == 201
    case_data = create_resp.json()
    case_id = case_data["id"]
    assert case_data["case_number"].startswith("CASE-")
    assert case_data["status"] == "OPEN"
    assert case_data["priority"] == "HIGH"
    assert case_data["risk_score"] == 82

    # 2. Get Case Details
    get_resp = await client_with_db.get(f"/api/v1/cases/{case_id}", headers=headers_a)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == case_id

    # 3. Tenant Isolation Check: Bank B cannot access Bank A's case
    headers_b = {"X-Institution-ID": str(inst_b_id), "X-Actor-ID": "analyst_bob"}
    unauthorized_resp = await client_with_db.get(f"/api/v1/cases/{case_id}", headers=headers_b)
    assert unauthorized_resp.status_code == 404
    assert unauthorized_resp.json()["error"]["code"] == "CASE_NOT_FOUND"

    # 4. Assign Case to Investigator
    assign_resp = await client_with_db.patch(
        f"/api/v1/cases/{case_id}/assign",
        headers=headers_a,
        json={
            "assigned_analyst_id": "investigator_john",
            "assigned_role": "SENIOR_INVESTIGATOR",
            "notes": "Assigned for priority AML review",
        },
    )
    assert assign_resp.status_code == 200
    # Auto-transitions to UNDER_INVESTIGATION
    assert assign_resp.json()["status"] == "UNDER_INVESTIGATION"
    assert assign_resp.json()["assigned_analyst_id"] == "investigator_john"

    # 5. Add Note
    note_resp = await client_with_db.post(
        f"/api/v1/cases/{case_id}/notes",
        headers=headers_a,
        json={"note_text": "Confirmed KYC anomalies on destination counterparty."},
    )
    assert note_resp.status_code == 201
    assert len(note_resp.json()["notes_log"]) >= 1

    # 6. Add Evidence Item
    evidence_resp = await client_with_db.post(
        f"/api/v1/cases/{case_id}/evidence",
        headers=headers_a,
        json={
            "evidence_type": "GRAPH_SUBGRAPH",
            "title": "Sub-graph topological cycle",
            "description": "3-hop circular flow graph trace",
            "reference_uri": "/evidence/graph/mc_trace.json",
            "payload_json": {"cycle_length": 3, "total_volume": 75000},
        },
    )
    assert evidence_resp.status_code == 201
    ev_data = evidence_resp.json()
    assert ev_data["checksum_sha256"] is not None

    # 7. Compile Dossier
    dossier_resp = await client_with_db.get(f"/api/v1/cases/{case_id}/dossier", headers=headers_a)
    assert dossier_resp.status_code == 200
    dossier = dossier_resp.json()
    assert dossier["dossier_hash_sha256"] is not None
    assert len(dossier["evidence_items"]) == 1
    assert len(dossier["transactions"]) == 1

    # 8. List Cases with filtering
    list_resp = await client_with_db.get(
        "/api/v1/cases?status=UNDER_INVESTIGATION&priority=HIGH",
        headers=headers_a,
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1

    # 9. View Audit History
    hist_resp = await client_with_db.get(f"/api/v1/cases/{case_id}/history", headers=headers_a)
    assert hist_resp.status_code == 200
    history = hist_resp.json()
    assert len(history) >= 1
    assert any(h["transition_type"] == "ASSIGNMENT" for h in history)
