"""Integration tests for Transaction Domain, Idempotency, and Lifecycle Gateway."""

import uuid

import pytest
from httpx import AsyncClient


@pytest.fixture
async def banking_env(client_with_db: AsyncClient) -> dict[str, dict[str, str]]:
    """Helper fixture to set up two institutions and two active accounts."""
    # Institution A
    code_a = f"IA_{uuid.uuid4().hex[:4].upper()}"
    routing_a = f"{uuid.uuid4().int % 100000000:08d}"
    res_inst_a = await client_with_db.post(
        "/api/v1/institutions",
        json={"institution_code": code_a, "name": "Bank Alpha", "routing_identifier": routing_a},
    )
    assert res_inst_a.status_code == 201
    inst_a = res_inst_a.json()

    # Institution B
    code_b = f"IB_{uuid.uuid4().hex[:4].upper()}"
    routing_b = f"{uuid.uuid4().int % 100000000:08d}"
    res_inst_b = await client_with_db.post(
        "/api/v1/institutions",
        json={"institution_code": code_b, "name": "Bank Beta", "routing_identifier": routing_b},
    )
    assert res_inst_b.status_code == 201
    inst_b = res_inst_b.json()

    # Account A1 (Alpha)
    res_acct_a = await client_with_db.post(
        "/api/v1/accounts",
        json={
            "institution_id": inst_a["id"],
            "account_number": "ACCT-A-001",
            "account_type": "CHECKING",
            "currency": "USD",
            "initial_balance": "100000.0000",
        },
    )
    assert res_acct_a.status_code == 201
    acct_a = res_acct_a.json()

    # Account B1 (Beta)
    res_acct_b = await client_with_db.post(
        "/api/v1/accounts",
        json={
            "institution_id": inst_b["id"],
            "account_number": "ACCT-B-001",
            "account_type": "COMMERCIAL",
            "currency": "USD",
            "initial_balance": "50000.0000",
        },
    )
    assert res_acct_b.status_code == 201
    acct_b = res_acct_b.json()

    return {"inst_a": inst_a, "inst_b": inst_b, "acct_a": acct_a, "acct_b": acct_b}


@pytest.mark.asyncio
async def test_submit_valid_cross_institution_transaction(
    client_with_db: AsyncClient, banking_env: dict[str, dict[str, str]]
) -> None:
    """Verify transaction submission results in PENDING_AUTHORIZATION and records history."""
    inst_a = banking_env["inst_a"]
    inst_b = banking_env["inst_b"]
    acct_a = banking_env["acct_a"]
    acct_b = banking_env["acct_b"]

    payload = {
        "idempotency_key": "IDEMP-TEST-SUBMIT-001",
        "origin_institution_id": inst_a["id"],
        "origin_account_id": acct_a["id"],
        "destination_institution_id": inst_b["id"],
        "destination_account_id": acct_b["id"],
        "amount": "2500.5000",
        "currency": "USD",
        "transaction_type": "TRANSFER",
        "purpose_code": "INVOICE_SETTLEMENT",
        "reference": "Ref #001",
        "simulation_metadata": {"test": True},
    }

    response = await client_with_db.post("/api/v1/transactions", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["idempotency_key"] == "IDEMP-TEST-SUBMIT-001"
    # CRITICAL: Submitted transactions must never be automatically authorized or settled
    assert data["status"] == "PENDING_AUTHORIZATION"
    assert data["amount"] == "2500.5000"
    assert data["currency"] == "USD"
    assert len(data["status_history"]) >= 1
    assert data["status_history"][0]["new_status"] == "PENDING_AUTHORIZATION"


@pytest.mark.asyncio
async def test_idempotent_retry_exact_match(
    client_with_db: AsyncClient, banking_env: dict[str, dict[str, str]]
) -> None:
    """Verify resubmitting with exact idempotency key returns HTTP 200 and identical record."""
    inst_a = banking_env["inst_a"]
    acct_a = banking_env["acct_a"]
    acct_b = banking_env["acct_b"]

    payload = {
        "idempotency_key": "IDEMP-TEST-EXACT-002",
        "origin_institution_id": inst_a["id"],
        "origin_account_id": acct_a["id"],
        "destination_institution_id": banking_env["inst_b"]["id"],
        "destination_account_id": acct_b["id"],
        "amount": "100.0000",
        "currency": "USD",
        "transaction_type": "TRANSFER",
    }

    res1 = await client_with_db.post("/api/v1/transactions", json=payload)
    assert res1.status_code == 201
    tx_id = res1.json()["id"]

    # Re-submission with identical parameters
    res2 = await client_with_db.post("/api/v1/transactions", json=payload)
    assert res2.status_code == 200
    assert res2.json()["id"] == tx_id
    assert res2.json()["idempotency_key"] == "IDEMP-TEST-EXACT-002"


@pytest.mark.asyncio
async def test_idempotent_retry_conflict_payload(
    client_with_db: AsyncClient, banking_env: dict[str, dict[str, str]]
) -> None:
    """Verify resubmitting same idempotency key with conflicting payload returns HTTP 409."""
    inst_a = banking_env["inst_a"]
    acct_a = banking_env["acct_a"]
    acct_b = banking_env["acct_b"]

    payload = {
        "idempotency_key": "IDEMP-TEST-CONFLICT-003",
        "origin_institution_id": inst_a["id"],
        "origin_account_id": acct_a["id"],
        "destination_institution_id": banking_env["inst_b"]["id"],
        "destination_account_id": acct_b["id"],
        "amount": "100.0000",
        "currency": "USD",
        "transaction_type": "TRANSFER",
    }

    res1 = await client_with_db.post("/api/v1/transactions", json=payload)
    assert res1.status_code == 201

    # Conflict: different amount
    conflicting_payload = dict(payload)
    conflicting_payload["amount"] = "999.0000"

    res2 = await client_with_db.post("/api/v1/transactions", json=conflicting_payload)
    assert res2.status_code == 409
    assert "conflicting" in res2.json()["error"]["message"]


@pytest.mark.asyncio
async def test_transaction_validation_failures(
    client_with_db: AsyncClient, banking_env: dict[str, dict[str, str]]
) -> None:
    """Verify proper rejection for account/institution mismatches and invalid accounts."""
    inst_a = banking_env["inst_a"]
    inst_b = banking_env["inst_b"]
    acct_a = banking_env["acct_a"]
    acct_b = banking_env["acct_b"]

    # 1. Unknown origin account
    res_unknown_origin = await client_with_db.post(
        "/api/v1/transactions",
        json={
            "idempotency_key": f"IDEMP-{uuid.uuid4()}",
            "origin_institution_id": inst_a["id"],
            "origin_account_id": str(uuid.uuid4()),
            "destination_institution_id": inst_b["id"],
            "destination_account_id": acct_b["id"],
            "amount": "50.0000",
            "currency": "USD",
            "transaction_type": "TRANSFER",
        },
    )
    assert res_unknown_origin.status_code == 400
    assert "Origin account does not exist" in res_unknown_origin.json()["error"]["message"]

    # 2. Account-to-institution mismatch: claiming acct_a belongs to inst_b
    res_mismatch = await client_with_db.post(
        "/api/v1/transactions",
        json={
            "idempotency_key": f"IDEMP-{uuid.uuid4()}",
            "origin_institution_id": inst_b["id"],  # Wrong!
            "origin_account_id": acct_a["id"],
            "destination_institution_id": inst_b["id"],
            "destination_account_id": acct_b["id"],
            "amount": "50.0000",
            "currency": "USD",
            "transaction_type": "TRANSFER",
        },
    )
    assert res_mismatch.status_code == 400
    assert "does not belong" in res_mismatch.json()["error"]["message"]


@pytest.mark.asyncio
async def test_simulation_lifecycle_actions(
    client_with_db: AsyncClient, banking_env: dict[str, dict[str, str]]
) -> None:
    """Verify permitted simulation actions (HOLD, SETTLE, REJECT) and invalid transitions."""
    inst_a = banking_env["inst_a"]
    inst_b = banking_env["inst_b"]
    acct_a = banking_env["acct_a"]
    acct_b = banking_env["acct_b"]

    submit_res = await client_with_db.post(
        "/api/v1/transactions",
        json={
            "idempotency_key": f"IDEMP-{uuid.uuid4()}",
            "origin_institution_id": inst_a["id"],
            "origin_account_id": acct_a["id"],
            "destination_institution_id": inst_b["id"],
            "destination_account_id": acct_b["id"],
            "amount": "500.0000",
            "currency": "USD",
            "transaction_type": "TRANSFER",
        },
    )
    assert submit_res.status_code == 201
    tx_id = submit_res.json()["id"]

    # Hold simulation action: PENDING_AUTHORIZATION -> HELD (Valid)
    res_hold = await client_with_db.post(
        f"/api/v1/transactions/{tx_id}/simulate-action",
        json={"action": "HOLD", "reason": "Simulated risk hold"},
    )
    assert res_hold.status_code == 200
    assert res_hold.json()["status"] == "HELD"

    # Settle simulation action: HELD -> SETTLED (Valid)
    res_settle = await client_with_db.post(
        f"/api/v1/transactions/{tx_id}/simulate-action",
        json={"action": "SETTLE", "reason": "Manual review approved simulation"},
    )
    assert res_settle.status_code == 200
    assert res_settle.json()["status"] == "SETTLED"

    # Invalid action on terminal SETTLED state: Cannot HOLD settled transaction
    res_invalid = await client_with_db.post(
        f"/api/v1/transactions/{tx_id}/simulate-action",
        json={"action": "HOLD", "reason": "Attempting illegal state rollback"},
    )
    assert res_invalid.status_code == 400
    assert "Invalid transition" in res_invalid.json()["error"]["message"]


@pytest.mark.asyncio
async def test_transaction_institution_boundary_isolation(
    client_with_db: AsyncClient, banking_env: dict[str, dict[str, str]]
) -> None:
    """Verify transaction retrieval is protected by institution boundaries."""
    inst_a = banking_env["inst_a"]
    inst_b = banking_env["inst_b"]
    acct_a = banking_env["acct_a"]
    acct_b = banking_env["acct_b"]

    submit_res = await client_with_db.post(
        "/api/v1/transactions",
        json={
            "idempotency_key": f"IDEMP-{uuid.uuid4()}",
            "origin_institution_id": inst_a["id"],
            "origin_account_id": acct_a["id"],
            "destination_institution_id": inst_b["id"],
            "destination_account_id": acct_b["id"],
            "amount": "10.0000",
            "currency": "USD",
            "transaction_type": "TRANSFER",
        },
    )
    tx_id = submit_res.json()["id"]

    # Origin institution can access
    res_origin = await client_with_db.get(
        f"/api/v1/transactions/{tx_id}",
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert res_origin.status_code == 200

    # Destination institution can access
    res_dest = await client_with_db.get(
        f"/api/v1/transactions/{tx_id}",
        headers={"X-Institution-ID": inst_b["id"]},
    )
    assert res_dest.status_code == 200

    # Foreign institution receives 403 Forbidden
    foreign_id = str(uuid.uuid4())
    res_foreign = await client_with_db.get(
        f"/api/v1/transactions/{tx_id}",
        headers={"X-Institution-ID": foreign_id},
    )
    assert res_foreign.status_code == 403
    assert "forbidden" in res_foreign.json()["error"]["message"]
