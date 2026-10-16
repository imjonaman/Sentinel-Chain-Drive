"""Integration tests for Institution Management API endpoints."""

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_institution_success(client_with_db: AsyncClient) -> None:
    """Verify successful creation of a simulated institution."""
    payload = {
        "institution_code": "FIRST_SYNTH_BANK",
        "name": "First Synthetic Bank",
        "routing_identifier": "12345678",
        "settings": {"synthetic": True, "tier": 1},
    }
    response = await client_with_db.post("/api/v1/institutions", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["institution_code"] == "FIRST_SYNTH_BANK"
    assert data["name"] == "First Synthetic Bank"
    assert data["status"] == "ACTIVE"
    assert data["routing_identifier"] == "12345678"
    assert data["settings"]["tier"] == 1
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_create_institution_duplicate_code_or_routing(client_with_db: AsyncClient) -> None:
    """Verify duplicate code or routing number is rejected with 400 Bad Request."""
    payload = {
        "institution_code": "DUPLICATE_BANK",
        "name": "Duplicate Bank Original",
        "routing_identifier": "87654321",
    }
    res1 = await client_with_db.post("/api/v1/institutions", json=payload)
    assert res1.status_code == 201

    # Same code
    res2 = await client_with_db.post(
        "/api/v1/institutions",
        json={
            "institution_code": "DUPLICATE_BANK",
            "name": "Duplicate Bank Copy",
            "routing_identifier": "99999999",
        },
    )
    assert res2.status_code == 400
    assert "already registered" in res2.json()["error"]["message"]

    # Same routing
    res3 = await client_with_db.post(
        "/api/v1/institutions",
        json={
            "institution_code": "OTHER_BANK",
            "name": "Other Bank",
            "routing_identifier": "87654321",
        },
    )
    assert res3.status_code == 400
    assert "already in use" in res3.json()["error"]["message"]


@pytest.mark.asyncio
async def test_get_and_list_institutions(client_with_db: AsyncClient) -> None:
    """Verify pagination and retrieving an institution by ID."""
    # Create two institutions
    await client_with_db.post(
        "/api/v1/institutions",
        json={
            "institution_code": "LIST_BANK_1",
            "name": "List Bank 1",
            "routing_identifier": "10000001",
        },
    )
    res_b2 = await client_with_db.post(
        "/api/v1/institutions",
        json={
            "institution_code": "LIST_BANK_2",
            "name": "List Bank 2",
            "routing_identifier": "10000002",
        },
    )
    b2_id = res_b2.json()["id"]

    # Retrieve by ID
    get_res = await client_with_db.get(f"/api/v1/institutions/{b2_id}")
    assert get_res.status_code == 200
    assert get_res.json()["institution_code"] == "LIST_BANK_2"

    # 404 for unknown
    unknown_res = await client_with_db.get(f"/api/v1/institutions/{uuid.uuid4()}")
    assert unknown_res.status_code == 404

    # List with pagination
    list_res = await client_with_db.get("/api/v1/institutions?limit=10&offset=0")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["total"] >= 2
    assert any(inst["institution_code"] == "LIST_BANK_1" for inst in list_data["items"])


@pytest.mark.asyncio
async def test_update_institution_metadata(client_with_db: AsyncClient) -> None:
    """Verify updating institution display name and settings."""
    create_res = await client_with_db.post(
        "/api/v1/institutions",
        json={
            "institution_code": "UPDATE_BANK",
            "name": "Initial Name",
            "routing_identifier": "20000001",
        },
    )
    inst_id = create_res.json()["id"]

    patch_res = await client_with_db.patch(
        f"/api/v1/institutions/{inst_id}",
        json={"name": "Renamed Commercial Bank", "settings": {"notes": "Updated"}},
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["name"] == "Renamed Commercial Bank"
    assert updated["settings"] == {"notes": "Updated"}


@pytest.mark.asyncio
async def test_institution_lifecycle_transitions(client_with_db: AsyncClient) -> None:
    """Verify valid and invalid state machine transitions for an institution."""
    create_res = await client_with_db.post(
        "/api/v1/institutions",
        json={
            "institution_code": "LIFECYCLE_BANK",
            "name": "Lifecycle Bank",
            "routing_identifier": "30000001",
        },
    )
    inst_id = create_res.json()["id"]

    # Active -> Suspended (Valid)
    res_suspend = await client_with_db.patch(
        f"/api/v1/institutions/{inst_id}/status",
        json={"status": "SUSPENDED", "reason": "Simulated audit check"},
    )
    assert res_suspend.status_code == 200
    assert res_suspend.json()["status"] == "SUSPENDED"

    # Suspended -> Active (Valid)
    res_reactivate = await client_with_db.patch(
        f"/api/v1/institutions/{inst_id}/status",
        json={"status": "ACTIVE", "reason": "Audit cleared"},
    )
    assert res_reactivate.status_code == 200
    assert res_reactivate.json()["status"] == "ACTIVE"

    # Active -> Inactive (Valid)
    res_deactivate = await client_with_db.patch(
        f"/api/v1/institutions/{inst_id}/status",
        json={"status": "INACTIVE", "reason": "Institution decommissioned"},
    )
    assert res_deactivate.status_code == 200
    assert res_deactivate.json()["status"] == "INACTIVE"

    # Inactive -> Active (Invalid - terminal state)
    res_invalid = await client_with_db.patch(
        f"/api/v1/institutions/{inst_id}/status",
        json={"status": "ACTIVE", "reason": "Attempting invalid recovery"},
    )
    assert res_invalid.status_code == 400
    assert "status transition" in res_invalid.json()["error"]["message"]
