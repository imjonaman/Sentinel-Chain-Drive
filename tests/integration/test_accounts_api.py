import uuid
from typing import Any, cast

import pytest
from httpx import AsyncClient


@pytest.fixture
async def sample_institution(client_with_db: AsyncClient) -> dict[str, Any]:
    """Helper fixture to create an institution for account tests."""
    code = f"BK_{uuid.uuid4().hex[:6].upper()}"
    routing = f"{uuid.uuid4().int % 100000000:08d}"
    res = await client_with_db.post(
        "/api/v1/institutions",
        json={"institution_code": code, "name": "Sample Bank", "routing_identifier": routing},
    )
    assert res.status_code == 201
    return cast(dict[str, Any], res.json())


@pytest.mark.asyncio
async def test_create_account_success(
    client_with_db: AsyncClient, sample_institution: dict[str, Any]
) -> None:
    """Verify creating a valid synthetic account associated with an institution."""
    payload = {
        "institution_id": sample_institution["id"],
        "account_number": "SYNTH-ACCT-001",
        "account_type": "CHECKING",
        "currency": "USD",
        "initial_balance": "50000.0000",
        "risk_flags": ["PRIMARY_CHECKING"],
    }
    response = await client_with_db.post("/api/v1/accounts", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["account_number"] == "SYNTH-ACCT-001"
    assert data["institution_id"] == sample_institution["id"]
    assert data["status"] == "ACTIVE"
    assert data["balance"] == "50000.0000"
    assert data["currency"] == "USD"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_account_unknown_institution(client_with_db: AsyncClient) -> None:
    """Verify account creation with nonexistent institution fails with 404 Not Found."""
    payload = {
        "institution_id": str(uuid.uuid4()),
        "account_number": "SYNTH-ACCT-NOINST",
        "account_type": "CHECKING",
        "currency": "USD",
        "initial_balance": "100.0000",
    }
    response = await client_with_db.post("/api/v1/accounts", json=payload)
    assert response.status_code == 404
    assert "not found" in response.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_create_account_duplicate_number_in_same_institution(
    client_with_db: AsyncClient, sample_institution: dict[str, str]
) -> None:
    """Verify duplicate account number under the same institution fails with 400."""
    payload = {
        "institution_id": sample_institution["id"],
        "account_number": "DUPLICATE-ACCT-NUM",
        "account_type": "CHECKING",
        "currency": "USD",
        "initial_balance": "1000.0000",
    }
    res1 = await client_with_db.post("/api/v1/accounts", json=payload)
    assert res1.status_code == 201

    res2 = await client_with_db.post("/api/v1/accounts", json=payload)
    assert res2.status_code == 400
    assert "already exists" in res2.json()["error"]["message"]


@pytest.mark.asyncio
async def test_account_lifecycle_transitions(
    client_with_db: AsyncClient, sample_institution: dict[str, str]
) -> None:
    """Verify active -> frozen -> active and terminal closed state."""
    res = await client_with_db.post(
        "/api/v1/accounts",
        json={
            "institution_id": sample_institution["id"],
            "account_number": "LIFECYCLE-ACCT",
            "account_type": "SAVINGS",
            "currency": "USD",
            "initial_balance": "500.0000",
        },
    )
    acct_id = res.json()["id"]

    # Active -> Frozen (Valid)
    res_freeze = await client_with_db.patch(
        f"/api/v1/accounts/{acct_id}/status",
        json={"status": "FROZEN", "reason": "Suspected anomalous activity"},
    )
    assert res_freeze.status_code == 200
    assert res_freeze.json()["status"] == "FROZEN"

    # Frozen -> Active (Valid)
    res_unfreeze = await client_with_db.patch(
        f"/api/v1/accounts/{acct_id}/status",
        json={"status": "ACTIVE", "reason": "Investigation concluded"},
    )
    assert res_unfreeze.status_code == 200
    assert res_unfreeze.json()["status"] == "ACTIVE"

    # Active -> Closed (Valid)
    res_close = await client_with_db.patch(
        f"/api/v1/accounts/{acct_id}/status",
        json={"status": "CLOSED", "reason": "Customer closed"},
    )
    assert res_close.status_code == 200
    assert res_close.json()["status"] == "CLOSED"

    # Closed -> Active (Invalid - terminal)
    res_reopen = await client_with_db.patch(
        f"/api/v1/accounts/{acct_id}/status",
        json={"status": "ACTIVE", "reason": "Cannot reopen closed account"},
    )
    assert res_reopen.status_code == 400
    assert "status transition" in res_reopen.json()["error"]["message"]


@pytest.mark.asyncio
async def test_account_institution_access_boundary(
    client_with_db: AsyncClient, sample_institution: dict[str, str]
) -> None:
    """Verify institution boundary enforcement via X-Institution-ID header."""
    res = await client_with_db.post(
        "/api/v1/accounts",
        json={
            "institution_id": sample_institution["id"],
            "account_number": "SECURE-ACCT-01",
            "account_type": "CHECKING",
            "currency": "USD",
            "initial_balance": "100.0000",
        },
    )
    acct_id = res.json()["id"]

    # Access with matching institution header -> OK
    res_matching = await client_with_db.get(
        f"/api/v1/accounts/{acct_id}",
        headers={"X-Institution-ID": sample_institution["id"]},
    )
    assert res_matching.status_code == 200

    # Access with different foreign institution header -> 403 Forbidden
    other_inst_id = str(uuid.uuid4())
    res_foreign = await client_with_db.get(
        f"/api/v1/accounts/{acct_id}",
        headers={"X-Institution-ID": other_inst_id},
    )
    assert res_foreign.status_code == 403
    assert "forbidden" in res_foreign.json()["error"]["message"]
