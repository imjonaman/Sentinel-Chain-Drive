"""Integration tests for Phase 3: AgentID and Capability Registry."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from httpx import AsyncClient

from sentinel_chain_drive.core.crypto import (
    compute_transaction_intent_hash,
    generate_ed25519_keypair,
    sign_payload,
)


@pytest.fixture
async def active_institution(client_with_db: AsyncClient) -> dict[str, Any]:
    """Helper to create and return an active institution."""
    payload = {
        "institution_code": f"BANK_{uuid.uuid4().hex[:6].upper()}",
        "name": "Integration Bank Corp",
        "routing_identifier": f"RT{uuid.uuid4().hex[:6].upper()}",
    }
    res = await client_with_db.post("/api/v1/institutions", json=payload)
    assert res.status_code == 201
    return cast(dict[str, Any], res.json())


@pytest.fixture
async def registered_agent(
    client_with_db: AsyncClient,
    active_institution: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Helper to register an agent and return (agent_dict, private_pem)."""
    private_pem, public_pem = generate_ed25519_keypair()
    institution_id = active_institution["id"]

    reg_payload = {
        "institution_id": institution_id,
        "name": "Trading Agent 007",
        "owner_contact": "quant-desk@bank.com",
        "agent_type": "AUTONOMOUS_PAYMENT_AGENT",
        "public_key": public_pem,
    }
    res = await client_with_db.post(
        f"/api/v1/institutions/{institution_id}/agents",
        json=reg_payload,
    )
    assert res.status_code == 201
    agent_data = res.json()
    assert agent_data["status"] == "PENDING_APPROVAL"
    return agent_data, private_pem


@pytest.fixture
async def active_agent(
    client_with_db: AsyncClient,
    registered_agent: tuple[dict[str, Any], str],
) -> tuple[dict[str, Any], str]:
    """Helper to activate an agent."""
    agent_data, private_pem = registered_agent
    institution_id = agent_data["institution_id"]
    agent_id = agent_data["id"]

    # Transition to ACTIVE
    res = await client_with_db.post(
        f"/api/v1/institutions/{institution_id}/agents/{agent_id}/status",
        json={"status": "ACTIVE", "reason": "Approved by compliance"},
    )
    assert res.status_code == 200
    active_data = res.json()
    assert active_data["status"] == "ACTIVE"
    return active_data, private_pem


@pytest.mark.asyncio
async def test_agent_registration_and_get(
    client_with_db: AsyncClient,
    active_institution: dict[str, Any],
) -> None:
    """Verify successful agent registration and lookup."""
    priv, pub = generate_ed25519_keypair()
    inst_id = active_institution["id"]

    res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/agents",
        json={
            "institution_id": inst_id,
            "name": "Treasury Agent",
            "owner_contact": "treasury@bank.com",
            "public_key": pub,
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Treasury Agent"
    assert data["status"] == "PENDING_APPROVAL"
    assert data["key_version"] == 1

    # Lookup
    get_res = await client_with_db.get(f"/api/v1/institutions/{inst_id}/agents/{data['id']}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == data["id"]


@pytest.mark.asyncio
async def test_agent_lifecycle_transitions_and_terminal_revocation(
    client_with_db: AsyncClient,
    registered_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify legal lifecycle transitions and that REVOKED is irreversible."""
    agent_data, _ = registered_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]

    # Illegal transition: PENDING -> SUSPENDED
    bad_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/agents/{agent_id}/status",
        json={"status": "SUSPENDED"},
    )
    assert bad_res.status_code == 409

    # Legal: PENDING -> ACTIVE
    ok_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/agents/{agent_id}/status",
        json={"status": "ACTIVE"},
    )
    assert ok_res.status_code == 200
    assert ok_res.json()["status"] == "ACTIVE"

    # Legal: ACTIVE -> SUSPENDED -> ACTIVE
    res_susp = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/agents/{agent_id}/status",
        json={"status": "SUSPENDED"},
    )
    assert res_susp.status_code == 200

    res_react = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/agents/{agent_id}/status",
        json={"status": "ACTIVE"},
    )
    assert res_react.status_code == 200

    # Legal: ACTIVE -> REVOKED
    res_rev = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/agents/{agent_id}/status",
        json={"status": "REVOKED", "reason": "Compromised key"},
    )
    assert res_rev.status_code == 200
    assert res_rev.json()["status"] == "REVOKED"

    # Reversal attempt: REVOKED -> ACTIVE must fail with 409
    res_react_bad = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/agents/{agent_id}/status",
        json={"status": "ACTIVE"},
    )
    assert res_react_bad.status_code == 409
    assert "Illegal lifecycle transition" in res_react_bad.json()["error"]["message"]


@pytest.mark.asyncio
async def test_key_rotation(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify key rotation bumps key_version and updates public key."""
    agent_data, _ = active_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]

    _, new_pub = generate_ed25519_keypair()
    res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/agents/{agent_id}/rotate-key",
        json={"new_public_key": new_pub, "reason": "Periodic key rotation"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["key_version"] == 2
    assert data["public_key"] == new_pub.strip()


@pytest.mark.asyncio
async def test_capability_creation_and_limits_enforcement(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify capability creation and limits."""
    agent_data, _ = active_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]

    now = datetime.now(UTC)
    cap_payload = {
        "agent_id": agent_id,
        "name": "Standard Payment Limits",
        "permitted_transaction_types": ["DOMESTIC_TRANSFER"],
        "permitted_currencies": ["USD"],
        "max_amount_per_transaction": "5000.00",
        "max_daily_cumulative_amount": "20000.00",
        "valid_until": (now + timedelta(days=365)).isoformat(),
        "created_by": "sec-admin",
    }
    res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/capabilities",
        json=cap_payload,
    )
    assert res.status_code == 201
    cap_data = res.json()
    assert cap_data["name"] == "Standard Payment Limits"
    assert Decimal(cap_data["max_amount_per_transaction"]) == Decimal("5000.00")


@pytest.mark.asyncio
async def test_end_to_end_authorization_verification_flow(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify full cryptographic authorization verification pipeline with valid signature."""
    agent_data, priv_pem = active_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]
    now = datetime.now(UTC)

    # 1. Assign capability
    cap_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/capabilities",
        json={
            "agent_id": agent_id,
            "name": "Domestic Transfer Cap",
            "permitted_transaction_types": ["DOMESTIC_TRANSFER"],
            "permitted_currencies": ["USD"],
            "max_amount_per_transaction": "10000.00",
            "max_daily_cumulative_amount": "50000.00",
            "valid_until": (now + timedelta(days=30)).isoformat(),
            "created_by": "compliance_officer",
        },
    )
    assert cap_res.status_code == 201

    # 2. Issue credential
    cred_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/credentials",
        json={
            "agent_id": agent_id,
            "institution_id": inst_id,
            "valid_hours": 24,
            "claims": {"tier": "gold"},
            "signature": "mock_sig_hex",
        },
    )
    assert cred_res.status_code == 201
    cred_data = cred_res.json()
    credential_id = cred_data["credential_id"]

    # 3. Construct transaction intent
    tx_intent = {
        "amount": "2500.00",
        "currency": "USD",
        "origin_institution_code": "APEX_BANK",
        "origin_account_number": "ACC10001",
        "destination_institution_code": "GLOBAL_BANK",
        "destination_account_number": "ACC20002",
        "transaction_type": "DOMESTIC_TRANSFER",
        "purpose_code": "SUPPLIER_PAYMENT",
    }
    tx_hash = compute_transaction_intent_hash(tx_intent)

    nonce = f"nonce_{uuid.uuid4().hex}"
    req_timestamp = datetime.now(UTC)

    # 4. Sign canonical authorization payload with agent's private key
    auth_payload = {
        "credential_id": credential_id,
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": nonce,
        "request_timestamp": req_timestamp.isoformat(),
        "transaction_hash": tx_hash,
    }
    sig_hex = sign_payload(priv_pem, auth_payload)

    # 5. Submit verification
    verify_req = {
        "credential_id": credential_id,
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": nonce,
        "request_timestamp": req_timestamp.isoformat(),
        "transaction": tx_intent,
        "signature": sig_hex,
    }
    verify_res = await client_with_db.post(
        "/api/v1/authorizations/verify",
        json=verify_req,
    )
    assert verify_res.status_code == 200
    res_data = verify_res.json()
    assert res_data["authorized"] is True
    assert res_data["decision"] == "AUTHORIZED"
    assert "AUTHORIZED" in res_data["reasons"]


@pytest.mark.asyncio
async def test_adversarial_tampered_payload_rejected(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify that tampering with transaction intent or metadata breaks signature check."""
    agent_data, priv_pem = active_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]
    now = datetime.now(UTC)

    await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/capabilities",
        json={
            "agent_id": agent_id,
            "name": "Domestic Transfer Cap",
            "permitted_transaction_types": ["DOMESTIC_TRANSFER"],
            "permitted_currencies": ["USD"],
            "max_amount_per_transaction": "10000.00",
            "max_daily_cumulative_amount": "50000.00",
            "valid_until": (now + timedelta(days=30)).isoformat(),
            "created_by": "compliance_officer",
        },
    )
    cred_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/credentials",
        json={
            "agent_id": agent_id,
            "institution_id": inst_id,
            "valid_hours": 24,
            "signature": "mock_sig",
        },
    )
    credential_id = cred_res.json()["credential_id"]

    tx_intent = {
        "amount": "1000.00",
        "currency": "USD",
        "origin_institution_code": "APEX_BANK",
        "origin_account_number": "ACC10001",
        "destination_institution_code": "GLOBAL_BANK",
        "destination_account_number": "ACC20002",
        "transaction_type": "DOMESTIC_TRANSFER",
    }
    tx_hash = compute_transaction_intent_hash(tx_intent)
    nonce = f"nonce_{uuid.uuid4().hex}"
    req_timestamp = datetime.now(UTC)

    auth_payload = {
        "credential_id": credential_id,
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": nonce,
        "request_timestamp": req_timestamp.isoformat(),
        "transaction_hash": tx_hash,
    }
    sig_hex = sign_payload(priv_pem, auth_payload)

    # TAMPER: change amount from 1000.00 to 1000.01 in the transaction submitted to verify!
    tampered_tx = dict(tx_intent)
    tampered_tx["amount"] = "1000.01"

    tampered_req = {
        "credential_id": credential_id,
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": nonce,
        "request_timestamp": req_timestamp.isoformat(),
        "transaction": tampered_tx,
        "signature": sig_hex,
    }
    res = await client_with_db.post("/api/v1/authorizations/verify", json=tampered_req)
    assert res.status_code == 200
    data = res.json()
    assert data["authorized"] is False
    assert data["decision"] == "REJECTED"
    assert any("INVALID_SIGNATURE" in r for r in data["reasons"])


@pytest.mark.asyncio
async def test_replay_attack_rejected(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify duplicate nonce submitted twice is rejected on second attempt."""
    agent_data, priv_pem = active_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]
    now = datetime.now(UTC)

    await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/capabilities",
        json={
            "agent_id": agent_id,
            "name": "Cap",
            "permitted_transaction_types": ["DOMESTIC_TRANSFER"],
            "permitted_currencies": ["USD"],
            "max_amount_per_transaction": "10000.00",
            "max_daily_cumulative_amount": "50000.00",
            "valid_until": (now + timedelta(days=30)).isoformat(),
            "created_by": "sec",
        },
    )
    cred_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/credentials",
        json={
            "agent_id": agent_id,
            "institution_id": inst_id,
            "valid_hours": 24,
            "signature": "mock_sig",
        },
    )
    credential_id = cred_res.json()["credential_id"]

    tx_intent = {
        "amount": "500.00",
        "currency": "USD",
        "origin_institution_code": "APEX_BANK",
        "origin_account_number": "ACC10001",
        "destination_institution_code": "GLOBAL_BANK",
        "destination_account_number": "ACC20002",
        "transaction_type": "DOMESTIC_TRANSFER",
    }
    tx_hash = compute_transaction_intent_hash(tx_intent)
    nonce = f"fixed_replay_nonce_{uuid.uuid4().hex}"
    req_timestamp = datetime.now(UTC)

    auth_payload = {
        "credential_id": credential_id,
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": nonce,
        "request_timestamp": req_timestamp.isoformat(),
        "transaction_hash": tx_hash,
    }
    sig_hex = sign_payload(priv_pem, auth_payload)

    verify_req = {
        "credential_id": credential_id,
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": nonce,
        "request_timestamp": req_timestamp.isoformat(),
        "transaction": tx_intent,
        "signature": sig_hex,
    }

    # First request: SUCCESS
    res1 = await client_with_db.post("/api/v1/authorizations/verify", json=verify_req)
    assert res1.status_code == 200
    assert res1.json()["authorized"] is True

    # Second request with SAME NONCE: REPLAY REJECTED!
    res2 = await client_with_db.post("/api/v1/authorizations/verify", json=verify_req)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["authorized"] is False
    assert data2["decision"] == "REJECTED"
    assert "REPLAY_DETECTED_NONCE_REUSED" in data2["reasons"]


@pytest.mark.asyncio
async def test_clock_skew_exceeded_rejected(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify request timestamp outside +-300 seconds window is rejected."""
    agent_data, priv_pem = active_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]

    old_timestamp = datetime.now(UTC) - timedelta(seconds=301)
    tx_intent = {
        "amount": "500.00",
        "currency": "USD",
        "origin_institution_code": "APEX_BANK",
        "origin_account_number": "ACC10001",
        "destination_institution_code": "GLOBAL_BANK",
        "destination_account_number": "ACC20002",
        "transaction_type": "DOMESTIC_TRANSFER",
    }
    verify_req = {
        "credential_id": "mock_cred",
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": f"nonce_{uuid.uuid4().hex}",
        "request_timestamp": old_timestamp.isoformat(),
        "transaction": tx_intent,
        "signature": "dummy_sig",
    }
    res = await client_with_db.post("/api/v1/authorizations/verify", json=verify_req)
    assert res.status_code == 200
    data = res.json()
    assert data["authorized"] is False
    assert any("CLOCK_SKEW_EXCEEDED" in r for r in data["reasons"])


@pytest.mark.asyncio
async def test_revoked_credential_rejected(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify immediately revoking a credential blocks authorization."""
    agent_data, priv_pem = active_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]
    now = datetime.now(UTC)

    await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/capabilities",
        json={
            "agent_id": agent_id,
            "name": "Cap",
            "permitted_transaction_types": ["DOMESTIC_TRANSFER"],
            "permitted_currencies": ["USD"],
            "max_amount_per_transaction": "10000.00",
            "max_daily_cumulative_amount": "50000.00",
            "valid_until": (now + timedelta(days=30)).isoformat(),
            "created_by": "sec",
        },
    )
    cred_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/credentials",
        json={
            "agent_id": agent_id,
            "institution_id": inst_id,
            "valid_hours": 24,
            "signature": "mock_sig",
        },
    )
    credential_id = cred_res.json()["credential_id"]

    # Revoke credential
    rev_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/credentials/{credential_id}/revoke",
        json={"reason": "Suspicious agent anomaly"},
    )
    assert rev_res.status_code == 200
    assert rev_res.json()["is_revoked"] is True

    # Try authorization
    tx_intent = {
        "amount": "500.00",
        "currency": "USD",
        "origin_institution_code": "APEX_BANK",
        "origin_account_number": "ACC10001",
        "destination_institution_code": "GLOBAL_BANK",
        "destination_account_number": "ACC20002",
        "transaction_type": "DOMESTIC_TRANSFER",
    }
    tx_hash = compute_transaction_intent_hash(tx_intent)
    nonce = f"nonce_{uuid.uuid4().hex}"
    req_timestamp = datetime.now(UTC)

    auth_payload = {
        "credential_id": credential_id,
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": nonce,
        "request_timestamp": req_timestamp.isoformat(),
        "transaction_hash": tx_hash,
    }
    sig_hex = sign_payload(priv_pem, auth_payload)

    verify_res = await client_with_db.post(
        "/api/v1/authorizations/verify",
        json={
            "credential_id": credential_id,
            "agent_id": agent_id,
            "institution_id": inst_id,
            "nonce": nonce,
            "request_timestamp": req_timestamp.isoformat(),
            "transaction": tx_intent,
            "signature": sig_hex,
        },
    )
    assert verify_res.status_code == 200
    data = verify_res.json()
    assert data["authorized"] is False
    assert "CREDENTIAL_REVOKED" in data["reasons"]


@pytest.mark.asyncio
async def test_capability_spending_limit_exceeded(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify attempting to spend more than max_amount_per_transaction is rejected."""
    agent_data, priv_pem = active_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]
    now = datetime.now(UTC)

    # Capability has limit of 1000.00
    await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/capabilities",
        json={
            "agent_id": agent_id,
            "name": "Micro Transfers Only",
            "permitted_transaction_types": ["DOMESTIC_TRANSFER"],
            "permitted_currencies": ["USD"],
            "max_amount_per_transaction": "1000.00",
            "max_daily_cumulative_amount": "5000.00",
            "valid_until": (now + timedelta(days=30)).isoformat(),
            "created_by": "sec",
        },
    )
    cred_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/credentials",
        json={
            "agent_id": agent_id,
            "institution_id": inst_id,
            "valid_hours": 24,
            "signature": "mock_sig",
        },
    )
    credential_id = cred_res.json()["credential_id"]

    # Transaction intent with amount 1500.00 (> 1000.00)
    tx_intent = {
        "amount": "1500.00",
        "currency": "USD",
        "origin_institution_code": "APEX_BANK",
        "origin_account_number": "ACC10001",
        "destination_institution_code": "GLOBAL_BANK",
        "destination_account_number": "ACC20002",
        "transaction_type": "DOMESTIC_TRANSFER",
    }
    tx_hash = compute_transaction_intent_hash(tx_intent)
    nonce = f"nonce_{uuid.uuid4().hex}"
    req_timestamp = datetime.now(UTC)

    auth_payload = {
        "credential_id": credential_id,
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": nonce,
        "request_timestamp": req_timestamp.isoformat(),
        "transaction_hash": tx_hash,
    }
    sig_hex = sign_payload(priv_pem, auth_payload)

    verify_res = await client_with_db.post(
        "/api/v1/authorizations/verify",
        json={
            "credential_id": credential_id,
            "agent_id": agent_id,
            "institution_id": inst_id,
            "nonce": nonce,
            "request_timestamp": req_timestamp.isoformat(),
            "transaction": tx_intent,
            "signature": sig_hex,
        },
    )
    assert verify_res.status_code == 200
    data = verify_res.json()
    assert data["authorized"] is False
    assert any("exceeds single limit" in r for r in data["reasons"])


@pytest.mark.asyncio
async def test_tenant_isolation_boundary(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify an institution cannot access or manipulate agents of another institution."""
    agent_data, _ = active_agent
    agent_id = agent_data["id"]

    # Another institution
    other_bank_res = await client_with_db.post(
        "/api/v1/institutions",
        json={
            "institution_code": f"OTHER_{uuid.uuid4().hex[:6].upper()}",
            "name": "Rival Bank",
            "routing_identifier": f"RT{uuid.uuid4().hex[:6].upper()}",
        },
    )
    other_inst_id = other_bank_res.json()["id"]

    # Attempting to fetch agent via other institution scope returns 404
    cross_res = await client_with_db.get(f"/api/v1/institutions/{other_inst_id}/agents/{agent_id}")
    assert cross_res.status_code == 404


@pytest.mark.asyncio
async def test_x_institution_id_header_mismatch_rejected_403(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify mismatched X-Institution-ID header is rejected with 403 Forbidden."""
    agent_data, _ = active_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]
    spoofed_inst_id = str(uuid.uuid4())

    # GET agent with spoofed header
    res = await client_with_db.get(
        f"/api/v1/institutions/{inst_id}/agents/{agent_id}",
        headers={"X-Institution-ID": spoofed_inst_id},
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "CROSS_INSTITUTION_ACCESS_FORBIDDEN"

    # POST agent status with spoofed header
    res_status = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/agents/{agent_id}/status",
        json={"status": "SUSPENDED"},
        headers={"X-Institution-ID": spoofed_inst_id},
    )
    assert res_status.status_code == 403
    assert res_status.json()["error"]["code"] == "CROSS_INSTITUTION_ACCESS_FORBIDDEN"


@pytest.mark.asyncio
async def test_wrong_issuer_and_wrong_audience_rejected(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify credentials issued for wrong issuer or audience are rejected."""
    agent_data, priv_pem = active_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]
    now = datetime.now(UTC)

    # Capability
    await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/capabilities",
        json={
            "agent_id": agent_id,
            "name": "General Cap",
            "permitted_transaction_types": ["DOMESTIC_TRANSFER"],
            "permitted_currencies": ["USD"],
            "max_amount_per_transaction": "5000.00",
            "max_daily_cumulative_amount": "20000.00",
            "valid_until": (now + timedelta(days=30)).isoformat(),
            "created_by": "sec",
        },
    )

    # Issue credential with custom audience and issuer
    cred_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/credentials",
        json={
            "agent_id": agent_id,
            "institution_id": inst_id,
            "issuer_id": "sentinel.trust-authority.regional",
            "audience": "sentinel.sandbox",
            "valid_hours": 24,
            "signature": "mock_sig",
        },
    )
    assert cred_res.status_code == 201
    cred_id = cred_res.json()["credential_id"]

    tx_intent = {
        "amount": "100.00",
        "currency": "USD",
        "origin_institution_code": "APEX_BANK",
        "origin_account_number": "ACC10001",
        "destination_institution_code": "GLOBAL_BANK",
        "destination_account_number": "ACC20002",
        "transaction_type": "DOMESTIC_TRANSFER",
    }
    tx_hash = compute_transaction_intent_hash(tx_intent)
    req_timestamp = datetime.now(UTC)

    auth_payload = {
        "credential_id": cred_id,
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": f"nonce_{uuid.uuid4().hex}",
        "request_timestamp": req_timestamp.isoformat(),
        "transaction_hash": tx_hash,
    }
    sig_hex = sign_payload(priv_pem, auth_payload)

    # 1. Verification with default expected_audience ("sentinel.authorization"):
    # Must fail because credential audience is "sentinel.sandbox"
    res1 = await client_with_db.post(
        "/api/v1/authorizations/verify",
        json={
            **auth_payload,
            "transaction": tx_intent,
            "signature": sig_hex,
        },
    )
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["authorized"] is False
    assert any("INVALID_CREDENTIAL_AUDIENCE" in r for r in data1["reasons"])

    # 2. Verification with expected_issuer mismatch
    auth_payload2 = {
        "credential_id": cred_id,
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": f"nonce_{uuid.uuid4().hex}",
        "request_timestamp": req_timestamp.isoformat(),
        "transaction_hash": tx_hash,
    }
    sig_hex2 = sign_payload(priv_pem, auth_payload2)
    res2 = await client_with_db.post(
        "/api/v1/authorizations/verify",
        json={
            **auth_payload2,
            "transaction": tx_intent,
            "signature": sig_hex2,
            "expected_audience": "sentinel.sandbox",
            "expected_issuer": "sentinel.federal-authority",
        },
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["authorized"] is False
    assert any("INVALID_CREDENTIAL_ISSUER" in r for r in data2["reasons"])


@pytest.mark.asyncio
async def test_old_key_credential_rejected_after_rotation(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify credentials issued with key_version 1 are rejected after key rotation to version 2."""
    agent_data, priv_pem_v1 = active_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]
    now = datetime.now(UTC)

    await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/capabilities",
        json={
            "agent_id": agent_id,
            "name": "Cap",
            "permitted_transaction_types": ["DOMESTIC_TRANSFER"],
            "permitted_currencies": ["USD"],
            "max_amount_per_transaction": "5000.00",
            "max_daily_cumulative_amount": "20000.00",
            "valid_until": (now + timedelta(days=30)).isoformat(),
            "created_by": "sec",
        },
    )

    # Issue credential under key version 1
    cred_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/credentials",
        json={
            "agent_id": agent_id,
            "institution_id": inst_id,
            "valid_hours": 24,
            "signature": "mock_sig",
        },
    )
    cred_id = cred_res.json()["credential_id"]
    assert cred_res.json()["key_version"] == 1

    # Rotate agent key to version 2
    priv_pem_v2, pub_pem_v2 = generate_ed25519_keypair()
    rot_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/agents/{agent_id}/rotate-key",
        json={"new_public_key": pub_pem_v2, "reason": "Compromised v1 key"},
    )
    assert rot_res.status_code == 200
    assert rot_res.json()["key_version"] == 2

    # Attempt verification using old credential
    tx_intent = {
        "amount": "200.00",
        "currency": "USD",
        "origin_institution_code": "APEX_BANK",
        "origin_account_number": "ACC10001",
        "destination_institution_code": "GLOBAL_BANK",
        "destination_account_number": "ACC20002",
        "transaction_type": "DOMESTIC_TRANSFER",
    }
    tx_hash = compute_transaction_intent_hash(tx_intent)
    auth_payload = {
        "credential_id": cred_id,
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": f"nonce_{uuid.uuid4().hex}",
        "request_timestamp": datetime.now(UTC).isoformat(),
        "transaction_hash": tx_hash,
    }
    # Even if signed by priv_pem_v2, the credential record has key_version=1
    # while agent has key_version=2
    sig_hex = sign_payload(priv_pem_v2, auth_payload)

    verify_res = await client_with_db.post(
        "/api/v1/authorizations/verify",
        json={
            **auth_payload,
            "transaction": tx_intent,
            "signature": sig_hex,
        },
    )
    assert verify_res.status_code == 200
    data = verify_res.json()
    assert data["authorized"] is False
    assert "KEY_VERSION_MISMATCH" in data["reasons"]


@pytest.mark.asyncio
async def test_unknown_agent_and_institution_fail_closed_without_500(
    client_with_db: AsyncClient,
    active_institution: dict[str, Any],
) -> None:
    """Verify non-existent agent or institution fails closed gracefully without 500 error."""
    inst_id = active_institution["id"]
    fake_agent_id = str(uuid.uuid4())
    fake_inst_id = str(uuid.uuid4())

    tx_intent = {
        "amount": "100.00",
        "currency": "USD",
        "origin_institution_code": "APEX_BANK",
        "origin_account_number": "ACC10001",
        "destination_institution_code": "GLOBAL_BANK",
        "destination_account_number": "ACC20002",
        "transaction_type": "DOMESTIC_TRANSFER",
    }
    verify_req_unknown_agent = {
        "credential_id": "cred_dummy",
        "agent_id": fake_agent_id,
        "institution_id": inst_id,
        "nonce": f"nonce_{uuid.uuid4().hex}",
        "request_timestamp": datetime.now(UTC).isoformat(),
        "transaction": tx_intent,
        "signature": "00" * 64,
    }
    res_agent = await client_with_db.post(
        "/api/v1/authorizations/verify", json=verify_req_unknown_agent
    )
    assert res_agent.status_code == 200
    data_agent = res_agent.json()
    assert data_agent["authorized"] is False
    assert "AGENT_NOT_FOUND" in data_agent["reasons"]

    verify_req_unknown_inst = {
        "credential_id": "cred_dummy",
        "agent_id": fake_agent_id,
        "institution_id": fake_inst_id,
        "nonce": f"nonce_{uuid.uuid4().hex}",
        "request_timestamp": datetime.now(UTC).isoformat(),
        "transaction": tx_intent,
        "signature": "00" * 64,
    }
    res_inst = await client_with_db.post(
        "/api/v1/authorizations/verify", json=verify_req_unknown_inst
    )
    assert res_inst.status_code == 200
    data_inst = res_inst.json()
    assert data_inst["authorized"] is False
    assert "INSTITUTION_NOT_FOUND" in data_inst["reasons"]


@pytest.mark.asyncio
async def test_multi_currency_velocity_isolation(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify that transactions in USD do not consume EUR 24-hour spending velocity."""
    agent_data, priv_pem = active_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]
    now = datetime.now(UTC)

    # Capability allows USD and EUR, max single 1000, max daily 1500
    await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/capabilities",
        json={
            "agent_id": agent_id,
            "name": "Multi Currency Cap",
            "permitted_transaction_types": ["DOMESTIC_TRANSFER"],
            "permitted_currencies": ["USD", "EUR"],
            "max_amount_per_transaction": "1000.00",
            "max_daily_cumulative_amount": "1500.00",
            "valid_until": (now + timedelta(days=30)).isoformat(),
            "created_by": "sec",
        },
    )
    cred_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/credentials",
        json={
            "agent_id": agent_id,
            "institution_id": inst_id,
            "valid_hours": 24,
            "signature": "mock_sig",
        },
    )
    cred_id = cred_res.json()["credential_id"]

    # 1. Authorize 1000 USD transfer
    tx_usd = {
        "amount": "1000.00",
        "currency": "USD",
        "origin_institution_code": "APEX_BANK",
        "origin_account_number": "ACC10001",
        "destination_institution_code": "GLOBAL_BANK",
        "destination_account_number": "ACC20002",
        "transaction_type": "DOMESTIC_TRANSFER",
    }
    tx_hash_usd = compute_transaction_intent_hash(tx_usd)
    req_ts = datetime.now(UTC)
    payload_usd = {
        "credential_id": cred_id,
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": f"nonce_{uuid.uuid4().hex}",
        "request_timestamp": req_ts.isoformat(),
        "transaction_hash": tx_hash_usd,
    }
    sig_usd = sign_payload(priv_pem, payload_usd)
    res_usd = await client_with_db.post(
        "/api/v1/authorizations/verify",
        json={**payload_usd, "transaction": tx_usd, "signature": sig_usd},
    )
    assert res_usd.status_code == 200
    assert res_usd.json()["authorized"] is True

    # 2. Authorize 800 EUR transfer (should SUCCEED because EUR spend is 0, not mixed with USD 1000)
    tx_eur = {
        "amount": "800.00",
        "currency": "EUR",
        "origin_institution_code": "APEX_BANK",
        "origin_account_number": "ACC10001",
        "destination_institution_code": "GLOBAL_BANK",
        "destination_account_number": "ACC20002",
        "transaction_type": "DOMESTIC_TRANSFER",
    }
    tx_hash_eur = compute_transaction_intent_hash(tx_eur)
    payload_eur = {
        "credential_id": cred_id,
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": f"nonce_{uuid.uuid4().hex}",
        "request_timestamp": req_ts.isoformat(),
        "transaction_hash": tx_hash_eur,
    }
    sig_eur = sign_payload(priv_pem, payload_eur)
    res_eur = await client_with_db.post(
        "/api/v1/authorizations/verify",
        json={**payload_eur, "transaction": tx_eur, "signature": sig_eur},
    )
    assert res_eur.status_code == 200
    assert res_eur.json()["authorized"] is True

    # 3. Submit another 800 USD transfer:
    # USD spend would be 1000 + 800 = 1800 > 1500 daily limit -> REJECTED!
    tx_usd2 = dict(tx_usd)
    tx_usd2["amount"] = "800.00"
    tx_hash_usd2 = compute_transaction_intent_hash(tx_usd2)
    payload_usd2 = {
        "credential_id": cred_id,
        "agent_id": agent_id,
        "institution_id": inst_id,
        "nonce": f"nonce_{uuid.uuid4().hex}",
        "request_timestamp": req_ts.isoformat(),
        "transaction_hash": tx_hash_usd2,
    }
    sig_usd2 = sign_payload(priv_pem, payload_usd2)
    res_usd2 = await client_with_db.post(
        "/api/v1/authorizations/verify",
        json={**payload_usd2, "transaction": tx_usd2, "signature": sig_usd2},
    )
    assert res_usd2.status_code == 200
    data_usd2 = res_usd2.json()
    assert data_usd2["authorized"] is False
    assert any("exceeds daily limit" in r for r in data_usd2["reasons"])


@pytest.mark.asyncio
async def test_cannot_assign_capability_to_non_active_agent(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify attempting to assign capability to a SUSPENDED agent is rejected."""
    agent_data, _ = active_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]

    # Suspend agent
    await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/agents/{agent_id}/status",
        json={"status": "SUSPENDED", "reason": "Audit review"},
    )

    # Try assigning capability
    now = datetime.now(UTC)
    res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/capabilities",
        json={
            "agent_id": agent_id,
            "name": "Cap for Suspended Agent",
            "permitted_transaction_types": ["DOMESTIC_TRANSFER"],
            "permitted_currencies": ["USD"],
            "max_amount_per_transaction": "1000.00",
            "max_daily_cumulative_amount": "5000.00",
            "valid_until": (now + timedelta(days=30)).isoformat(),
            "created_by": "sec",
        },
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_AGENT_STATUS"


@pytest.mark.asyncio
async def test_capability_update_enforces_limits_invariant(
    client_with_db: AsyncClient,
    active_agent: tuple[dict[str, Any], str],
) -> None:
    """Verify updating a capability to single > daily is rejected by the service."""
    agent_data, _ = active_agent
    inst_id = agent_data["institution_id"]
    agent_id = agent_data["id"]
    now = datetime.now(UTC)

    create_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_id}/capabilities",
        json={
            "agent_id": agent_id,
            "name": "Limit Cap",
            "permitted_transaction_types": ["DOMESTIC_TRANSFER"],
            "permitted_currencies": ["USD"],
            "max_amount_per_transaction": "1000.00",
            "max_daily_cumulative_amount": "2000.00",
            "valid_until": (now + timedelta(days=30)).isoformat(),
            "created_by": "sec",
        },
    )
    cap_id = create_res.json()["id"]

    # Update single limit to 3000 without updating daily limit (remains 2000)
    update_res = await client_with_db.patch(
        f"/api/v1/institutions/{inst_id}/capabilities/{cap_id}",
        json={"max_amount_per_transaction": "3000.00"},
    )
    assert update_res.status_code == 400
    assert update_res.json()["error"]["code"] == "INVALID_CAPABILITY_LIMITS"
