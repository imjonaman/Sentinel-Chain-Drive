"""Integration and API tests for Phase 6: Privacy Gateway and Cross-Institution Intelligence.

Validates:
- Field-level disclosure allowlists and prohibited-field rejection
- Purpose-bound, epoch-keyed HMAC-SHA256 pseudonymization (MeshID)
- Multi-tenant boundary isolation and authorized recipient targeting
- Cross-tenant access protection and forged caller prevention
- Anti-enumeration sliding window rate limiting
- Alert-to-indicator sanitization without PII/account leaks
- Revocation lifecycle and exclusion of stale/revoked indicators
- Audit log consistency and summary statistics
- Deterministic Policy Engine integration (HOLD on CRITICAL cross-bank indicator)
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sentinel_chain_drive.core.crypto import (
    compute_transaction_intent_hash,
    generate_ed25519_keypair,
    sign_payload,
)
from sentinel_chain_drive.core.privacy import compute_mesh_id
from sentinel_chain_drive.db.models.alert import (
    AlertSeverity,
    AlertStatus,
    DetectorType,
    FraudAlert,
)
from sentinel_chain_drive.services.privacy_gateway.service import (
    default_privacy_rate_limiter,
)


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    """Reset rate limiter state before each test run."""
    default_privacy_rate_limiter.reset_for_test()


@pytest.fixture
async def setup_institutions(
    client_with_db: AsyncClient,
) -> dict[str, Any]:
    """Helper to provision three isolated simulated institutions."""
    code_a = f"BKAL{uuid.uuid4().hex[:4].upper()}"
    inst_a_res = await client_with_db.post(
        "/api/v1/institutions",
        json={
            "institution_code": code_a,
            "name": "Bank Alpha Privacy Test",
            "routing_identifier": f"RT{uuid.uuid4().hex[:6].upper()}",
        },
    )
    assert inst_a_res.status_code == 201
    inst_a = inst_a_res.json()

    code_b = f"BKBE{uuid.uuid4().hex[:4].upper()}"
    inst_b_res = await client_with_db.post(
        "/api/v1/institutions",
        json={
            "institution_code": code_b,
            "name": "Bank Beta Privacy Test",
            "routing_identifier": f"RT{uuid.uuid4().hex[:6].upper()}",
        },
    )
    assert inst_b_res.status_code == 201
    inst_b = inst_b_res.json()

    code_c = f"BKGA{uuid.uuid4().hex[:4].upper()}"
    inst_c_res = await client_with_db.post(
        "/api/v1/institutions",
        json={
            "institution_code": code_c,
            "name": "Bank Gamma Privacy Test",
            "routing_identifier": f"RT{uuid.uuid4().hex[:6].upper()}",
        },
    )
    assert inst_c_res.status_code == 201
    inst_c = inst_c_res.json()

    return {"inst_a": inst_a, "inst_b": inst_b, "inst_c": inst_c}


@pytest.mark.asyncio
async def test_publish_indicator_success_and_idempotency(
    client_with_db: AsyncClient,
    setup_institutions: dict[str, Any],
) -> None:
    """Publish pre-sanitized indicator and verify idempotent update on duplicate publication."""
    inst_a = setup_institutions["inst_a"]
    inst_a_id = inst_a["id"]
    mesh_id = "0123456789abcdef" * 4

    payload = {
        "pseudonymous_mesh_id": mesh_id,
        "indicator_type": "MULE_BURST_INGRESS",
        "severity": "HIGH",
        "confidence_score": 0.85,
        "pattern_category": "TOPOLOGICAL_FAN_IN",
        "evidence_summary": {
            "pattern_type": "FAN_IN",
            "burst_count": 7,
            "anonymized_volume_tier": "TIER_MEDIUM_10K_TO_100K",
            "mulechain_rule_version": "v1.0",
        },
        "provenance": {"source": "UNIT_TEST"},
        "validity_hours": 48,
        "sharing_policy_version": "v1.0",
    }

    # 1. Publish indicator
    res1 = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json=payload,
        headers={"X-Institution-ID": inst_a_id},
    )
    assert res1.status_code == 201
    data1 = res1.json()
    assert data1["pseudonymous_mesh_id"] == mesh_id
    assert data1["originating_institution_id"] == inst_a_id
    assert data1["status"] == "ACTIVE"
    code = data1["indicator_code"]

    # 2. Publish updated indicator for same mesh_id and type (idempotency check)
    payload["confidence_score"] = 0.95
    res2 = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json=payload,
        headers={"X-Institution-ID": inst_a_id},
    )
    assert res2.status_code == 201
    data2 = res2.json()
    assert data2["indicator_code"] == code  # Same unique indicator code updated
    assert data2["confidence_score"] == 0.95


@pytest.mark.asyncio
async def test_publish_prohibited_and_unapproved_fields_rejected(
    client_with_db: AsyncClient,
    setup_institutions: dict[str, Any],
) -> None:
    """Outbound payloads containing sensitive or unallowlisted fields are rejected."""
    inst_a_id = setup_institutions["inst_a"]["id"]
    mesh_id = "f" * 64

    # 1. Prohibited raw account number
    prohibited_payload = {
        "pseudonymous_mesh_id": mesh_id,
        "indicator_type": "MULE_FAN_OUT",
        "severity": "HIGH",
        "confidence_score": 0.8,
        "pattern_category": "TOPOLOGICAL_FAN_OUT",
        "evidence_summary": {
            "account_number": "ACC-LEAKED-12345",
            "pattern_type": "FAN_OUT",
        },
    }
    res_prohibited = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json=prohibited_payload,
        headers={"X-Institution-ID": inst_a_id},
    )
    assert res_prohibited.status_code == 422

    # 2. Unapproved field not in allowlist
    unapproved_payload = {
        "pseudonymous_mesh_id": mesh_id,
        "indicator_type": "MULE_FAN_OUT",
        "severity": "HIGH",
        "confidence_score": 0.8,
        "pattern_category": "TOPOLOGICAL_FAN_OUT",
        "evidence_summary": {
            "unapproved_field_custom": "unapproved",
        },
    }
    res_unapproved = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json=unapproved_payload,
        headers={"X-Institution-ID": inst_a_id},
    )
    assert res_unapproved.status_code == 422


@pytest.mark.asyncio
async def test_missing_institution_header_rejected(
    client_with_db: AsyncClient,
) -> None:
    """Missing X-Institution-ID header is rejected with 400 Bad Request."""
    valid_payload = {
        "pseudonymous_mesh_id": "a" * 64,
        "indicator_type": "MULE_BURST_INGRESS",
        "severity": "HIGH",
        "confidence_score": 0.8,
        "pattern_category": "TOPOLOGICAL_FAN_IN",
        "evidence_summary": {"pattern_type": "FAN_IN"},
    }
    res = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json=valid_payload,
    )
    assert res.status_code == 400
    assert "X-Institution-ID" in res.json()["error"]["message"]


@pytest.mark.asyncio
async def test_cross_tenant_isolation_targeted_sharing(
    client_with_db: AsyncClient,
    setup_institutions: dict[str, Any],
) -> None:
    """Targeted indicator is visible only to originator and recipient, not third party."""
    inst_a = setup_institutions["inst_a"]
    inst_b = setup_institutions["inst_b"]
    inst_c = setup_institutions["inst_c"]

    mesh_id = "1" * 64

    # Bank A publishes an indicator specifically targeted to Bank B
    publish_res = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json={
            "pseudonymous_mesh_id": mesh_id,
            "indicator_type": "MULE_BURST_INGRESS",
            "severity": "CRITICAL",
            "confidence_score": 0.99,
            "pattern_category": "TOPOLOGICAL_FAN_IN",
            "target_institution_id": inst_b["id"],
            "evidence_summary": {
                "pattern_type": "FAN_IN",
                "burst_count": 8,
                "anonymized_volume_tier": "TIER_HIGH_OVER_100K",
            },
        },
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert publish_res.status_code == 201
    indicator_id = publish_res.json()["id"]

    # 1. Bank B (recipient) queries mesh_id -> finds 1 indicator
    query_b = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/query",
        json={"pseudonymous_mesh_id": mesh_id, "purpose": "FRAUD_SHARING"},
        headers={"X-Institution-ID": inst_b["id"]},
    )
    assert query_b.status_code == 200
    assert query_b.json()["total"] == 1

    # 2. Bank C (unauthorized third party) queries mesh_id -> finds 0 indicators
    query_c = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/query",
        json={"pseudonymous_mesh_id": mesh_id, "purpose": "FRAUD_SHARING"},
        headers={"X-Institution-ID": inst_c["id"]},
    )
    assert query_c.status_code == 200
    assert query_c.json()["total"] == 0

    # 3. Bank C attempts direct GET by ID -> returns 404 (scoped multi-tenant check)
    get_c = await client_with_db.get(
        f"/api/v1/privacy-gateway/indicators/{indicator_id}",
        headers={"X-Institution-ID": inst_c["id"]},
    )
    assert get_c.status_code == 404


@pytest.mark.asyncio
async def test_broadcast_sharing_and_raw_account_non_disclosure(
    client_with_db: AsyncClient,
    setup_institutions: dict[str, Any],
) -> None:
    """Broadcast indicators visible across network, with zero raw account exposure."""
    inst_a = setup_institutions["inst_a"]
    inst_b = setup_institutions["inst_b"]
    raw_account = "ACC-CONFIDENTIAL-8888"

    # Compute MeshID using Bank A's code
    mesh_id = compute_mesh_id(
        institution_code=inst_a["institution_code"],
        account_number=raw_account,
        purpose="FRAUD_SHARING",
    )

    # Publish broadcast (target_institution_id is None)
    pub_res = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json={
            "pseudonymous_mesh_id": mesh_id,
            "indicator_type": "SUSPICIOUS_MULE_ACCOUNT",
            "severity": "HIGH",
            "confidence_score": 0.88,
            "pattern_category": "TOPOLOGICAL_SUSPICIOUS",
            "target_institution_id": None,
            "evidence_summary": {
                "pattern_type": "SUSPICIOUS",
                "burst_count": 4,
                "anonymized_volume_tier": "TIER_MEDIUM_10K_TO_100K",
            },
        },
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert pub_res.status_code == 201

    # Bank B queries the broadcast indicator
    query_res = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/query",
        json={"pseudonymous_mesh_id": mesh_id, "purpose": "FRAUD_SHARING"},
        headers={"X-Institution-ID": inst_b["id"]},
    )
    assert query_res.status_code == 200
    items = query_res.json()["items"]
    assert len(items) == 1

    # Invariant: Raw account number must never be in payload or evidence
    raw_response_text = query_res.text
    assert raw_account not in raw_response_text
    assert items[0]["pseudonymous_mesh_id"] == mesh_id


@pytest.mark.asyncio
async def test_anti_enumeration_rate_limiting(
    client_with_db: AsyncClient,
    setup_institutions: dict[str, Any],
) -> None:
    """Excessive queries trigger anti-enumeration 429 Too Many Requests."""
    inst_a_id = setup_institutions["inst_a"]["id"]
    mesh_id = "2" * 64

    # Set tight quota on singleton limiter for testing
    default_privacy_rate_limiter.max_queries = 5

    for _ in range(5):
        res = await client_with_db.post(
            "/api/v1/privacy-gateway/indicators/query",
            json={"pseudonymous_mesh_id": mesh_id, "purpose": "FRAUD_SHARING"},
            headers={"X-Institution-ID": inst_a_id},
        )
        assert res.status_code == 200

    # 6th query must be rejected with 429
    blocked_res = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/query",
        json={"pseudonymous_mesh_id": mesh_id, "purpose": "FRAUD_SHARING"},
        headers={"X-Institution-ID": inst_a_id},
    )
    assert blocked_res.status_code == 429
    assert "rate limit exceeded" in blocked_res.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_revocation_lifecycle_and_unauthorized_withdrawal(
    client_with_db: AsyncClient,
    setup_institutions: dict[str, Any],
) -> None:
    """Only the originating institution can revoke an indicator."""
    inst_a = setup_institutions["inst_a"]
    inst_b = setup_institutions["inst_b"]
    mesh_id = "3" * 64

    # 1. Bank A publishes
    pub_res = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json={
            "pseudonymous_mesh_id": mesh_id,
            "indicator_type": "MULE_FAN_OUT",
            "severity": "HIGH",
            "confidence_score": 0.8,
            "pattern_category": "TOPOLOGICAL_FAN_OUT",
            "evidence_summary": {"pattern_type": "FAN_OUT"},
        },
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert pub_res.status_code == 201
    indicator_id = pub_res.json()["id"]

    # 2. Bank B attempts to revoke Bank A's indicator -> 403 Forbidden
    revoke_b = await client_with_db.post(
        f"/api/v1/privacy-gateway/indicators/{indicator_id}/revoke",
        json={"reason": "Unauthorized revocation attempt"},
        headers={"X-Institution-ID": inst_b["id"]},
    )
    assert revoke_b.status_code == 403

    # 3. Bank A revokes legitimately -> 200 OK
    revoke_a = await client_with_db.post(
        f"/api/v1/privacy-gateway/indicators/{indicator_id}/revoke",
        json={"reason": "Customer verified as false positive"},
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert revoke_a.status_code == 200
    assert revoke_a.json()["status"] == "REVOKED"

    # 4. Query for mesh_id no longer returns the revoked indicator
    query_res = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/query",
        json={"pseudonymous_mesh_id": mesh_id, "purpose": "FRAUD_SHARING"},
        headers={"X-Institution-ID": inst_b["id"]},
    )
    assert query_res.status_code == 200
    assert query_res.json()["total"] == 0


@pytest.mark.asyncio
async def test_audit_summary_counts_and_retrieval(
    client_with_db: AsyncClient,
    setup_institutions: dict[str, Any],
) -> None:
    """Privacy audit summary aggregates events correctly for an institution."""
    inst_a_id = setup_institutions["inst_a"]["id"]
    mesh_id = "4" * 64

    # Perform a publish
    await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json={
            "pseudonymous_mesh_id": mesh_id,
            "indicator_type": "MULE_RAPID_PASSTHROUGH",
            "severity": "MEDIUM",
            "confidence_score": 0.6,
            "pattern_category": "TOPOLOGICAL_TRANSIT",
            "evidence_summary": {"pattern_type": "TRANSIT"},
        },
        headers={"X-Institution-ID": inst_a_id},
    )

    # Perform a query
    await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/query",
        json={"pseudonymous_mesh_id": mesh_id, "purpose": "FRAUD_SHARING"},
        headers={"X-Institution-ID": inst_a_id},
    )

    # Get audit summary
    sum_res = await client_with_db.get(
        "/api/v1/privacy-gateway/audit-summary",
        headers={"X-Institution-ID": inst_a_id},
    )
    assert sum_res.status_code == 200
    summary = sum_res.json()
    assert summary["published_count"] >= 1
    assert summary["queried_count"] >= 1
    assert len(summary["recent_events"]) >= 2


@pytest.mark.asyncio
async def test_end_to_end_cross_institution_policy_hold(
    client_with_db: AsyncClient,
    setup_institutions: dict[str, Any],
) -> None:
    """Demonstrate cross-institution indicator triggering deterministic HOLD
    in Phase 4 Policy Engine.


    Scenario:
    - Bank B has an account and active agent with capability.
    - Bank A publishes a CRITICAL cross-institution indicator matching the account's MeshID.
    - Bank B queries the gateway during authorization evaluation.
    - Policy engine receives elevated risk signals and deterministically outputs HOLD.
    """
    inst_b = setup_institutions["inst_b"]
    inst_b_id = inst_b["id"]
    inst_b_code = inst_b["institution_code"]

    # 1. Create origin account in Bank B
    origin_acc_res = await client_with_db.post(
        "/api/v1/accounts",
        json={
            "institution_id": inst_b_id,
            "account_number": "ACC-FRAUD-VICTIM-01",
            "account_type": "CHECKING",
            "currency": "USD",
            "initial_balance": "50000.0000",
        },
    )
    assert origin_acc_res.status_code == 201
    origin_acc = origin_acc_res.json()

    # 2. Create destination account in Bank B
    dest_acc_res = await client_with_db.post(
        "/api/v1/accounts",
        json={
            "institution_id": inst_b_id,
            "account_number": "ACC-DESTINATION-01",
            "account_type": "CHECKING",
            "currency": "USD",
            "initial_balance": "1000.0000",
        },
    )
    assert dest_acc_res.status_code == 201
    dest_acc = dest_acc_res.json()

    # 3. Create agent and keypair in Bank B
    priv_key, pub_key = generate_ed25519_keypair()
    agent_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_b_id}/agents",
        json={
            "institution_id": inst_b_id,
            "name": "Payment Processing Agent",
            "owner_contact": "admin@bankbeta.com",
            "public_key": pub_key,
        },
    )
    assert agent_res.status_code == 201
    agent = agent_res.json()

    # Activate agent
    act_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_b_id}/agents/{agent['id']}/status",
        json={"status": "ACTIVE", "reason": "Approved for testing"},
    )
    assert act_res.status_code == 200
    agent = act_res.json()

    # 4. Issue capability
    cap_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_b_id}/capabilities",
        json={
            "agent_id": agent["id"],
            "name": "Standard Transfer Cap",
            "max_amount_per_transaction": "10000.0000",
            "max_daily_cumulative_amount": "50000.0000",
            "permitted_currencies": ["USD"],
            "permitted_transaction_types": ["WIRE", "INTERNAL"],
            "valid_from": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            "valid_until": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "created_by": "sec_admin",
        },
    )
    assert cap_res.status_code == 201

    # 5. Create active institutional policy in Bank B (automatically active)
    policy_res = await client_with_db.post(
        "/api/v1/policies",
        json={
            "institution_id": inst_b_id,
            "policy_code": f"POL-{uuid.uuid4().hex[:6].upper()}",
            "name": "Standard Fraud Policy",
            "version": "1.0",
            "rules": {
                "max_single_transaction_cap": "25000.0000",
                "allowed_currencies": ["USD"],
                "hold_risk_threshold": 0.85,
                "step_up_risk_threshold": 0.65,
            },
        },
    )
    assert policy_res.status_code == 201
    policy = policy_res.json()
    assert policy["is_active"] is True

    # 6. Issue Agent Credential
    cred_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_b_id}/credentials",
        json={
            "agent_id": agent["id"],
            "institution_id": inst_b_id,
            "valid_hours": 24,
            "signature": "dummy_cred_sig",
        },
    )
    assert cred_res.status_code == 201

    cred = cred_res.json()

    # 7. Bank A publishes CRITICAL indicator on the origin account
    mesh_id = compute_mesh_id(
        institution_code=inst_b_code,
        account_number=origin_acc["account_number"],
        purpose="FRAUD_SHARING",
    )
    inst_a_id = setup_institutions["inst_a"]["id"]
    pub_res = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json={
            "pseudonymous_mesh_id": mesh_id,
            "indicator_type": "MULE_CIRCULAR_LAYERING",
            "severity": "CRITICAL",
            "confidence_score": 0.96,
            "pattern_category": "STRUCTURING_FAN_OUT",
            "evidence_summary": {
                "pattern_type": "CIRCULAR_LAYERING",
                "burst_count": 6,
                "anonymized_volume_tier": "TIER_HIGH_OVER_100K",
            },
        },
        headers={"X-Institution-ID": inst_a_id},
    )
    assert pub_res.status_code == 201

    # 8. Bank B queries gateway for indicators matching this account
    query_res = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/query",
        json={"pseudonymous_mesh_id": mesh_id, "purpose": "FRAUD_SHARING"},
        headers={"X-Institution-ID": inst_b_id},
    )
    assert query_res.status_code == 200
    matched_items = query_res.json()["items"]
    assert len(matched_items) == 1

    # 9. Evaluate policy request with derived RiskSignals (score 0.90, manual review flag)
    amount = "2500.0000"
    tx_intent = {
        "amount": amount,
        "currency": "USD",
        "origin_institution_code": inst_b_code,
        "origin_account_number": origin_acc["account_number"],
        "destination_institution_code": inst_b_code,
        "destination_account_number": dest_acc["account_number"],
        "transaction_type": "WIRE",
        "purpose_code": "TRANSFER",
    }
    tx_hash = compute_transaction_intent_hash(
        intent_or_origin_institution_code=tx_intent["origin_institution_code"],
        origin_account_number=tx_intent["origin_account_number"],
        destination_institution_code=tx_intent["destination_institution_code"],
        destination_account_number=tx_intent["destination_account_number"],
        amount=tx_intent["amount"],
        currency=tx_intent["currency"],
        transaction_type=tx_intent["transaction_type"],
        purpose_code=tx_intent["purpose_code"],
    )

    req_nonce = f"nonce-{uuid.uuid4().hex}"
    now = datetime.now(UTC)
    auth_payload = {
        "credential_id": cred["credential_id"],
        "agent_id": agent["id"],
        "institution_id": inst_b_id,
        "nonce": req_nonce,
        "request_timestamp": now.isoformat(),
        "transaction_hash": tx_hash,
    }
    sig = sign_payload(priv_key, auth_payload)

    eval_payload = {
        "idempotency_key": f"idemp-{uuid.uuid4().hex}",
        "credential_id": cred["credential_id"],
        "agent_id": agent["id"],
        "institution_id": inst_b_id,
        "nonce": req_nonce,
        "request_timestamp": now.isoformat(),
        "transaction": tx_intent,
        "signature": sig,
        # Monotonically elevated risk signals from cross-institution intelligence
        "risk_signals": {
            "risk_score": 0.90,
            "manual_review_flag": True,
            "velocity_warning": True,
            "custom_signals": {
                "cross_institution_intel": {
                    "status": "MATCH",
                    "max_severity": "CRITICAL",
                }
            },
        },
    }

    eval_res = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=eval_payload,
        headers={"X-Institution-ID": inst_b_id},
    )
    assert eval_res.status_code == 200

    decision = eval_res.json()

    # Deterministic result MUST be HOLD due to CRITICAL risk score >= 0.85
    assert decision["decision"] == "HOLD"
    assert "HOLD_HIGH_RISK_SCORE" in decision["reason_codes"]
    assert decision["hold"] is not None
    assert decision["hold"]["review_workflow"] == "FRAUD_INVESTIGATION"


@pytest.mark.asyncio
async def test_republish_revoked_indicator_fails_with_409_conflict(
    client_with_db: AsyncClient,
    setup_institutions: dict[str, Any],
) -> None:
    """Audit 5 (SEC-P6-01): Revocation cannot be silently undone by duplicate publication."""
    inst_a_id = setup_institutions["inst_a"]["id"]
    mesh_id = "a1b2c3d4e5f67890" * 4

    payload = {
        "pseudonymous_mesh_id": mesh_id,
        "indicator_type": "MULE_FAN_OUT",
        "severity": "HIGH",
        "confidence_score": 0.82,
        "pattern_category": "TOPOLOGICAL_FAN_OUT",
        "evidence_summary": {
            "pattern_type": "FAN_OUT",
            "burst_count": 5,
            "anonymized_volume_tier": "TIER_MEDIUM_10K_TO_100K",
            "mulechain_rule_version": "v1.0",
        },
        "provenance": {"source": "FRAUD_OPS"},
        "validity_hours": 24,
        "sharing_policy_version": "v1.0",
    }

    # 1. Publish indicator
    res = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json=payload,
        headers={"X-Institution-ID": inst_a_id},
    )
    assert res.status_code == 201
    indicator_id = res.json()["id"]

    # 2. Revoke indicator
    del_res = await client_with_db.post(
        f"/api/v1/privacy-gateway/indicators/{indicator_id}/revoke",
        json={"reason": "False positive identified by fraud team"},
        headers={"X-Institution-ID": inst_a_id},
    )
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "REVOKED"

    # 3. Attempt republish with same policy version -> MUST return 409 Conflict
    repub_res = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json=payload,
        headers={"X-Institution-ID": inst_a_id},
    )
    assert repub_res.status_code == 409
    res_json = repub_res.json()
    error_msg = res_json.get("detail") or res_json.get("error", {}).get("message", "")
    assert "revoked" in error_msg.lower()


@pytest.mark.asyncio
async def test_republish_revoked_indicator_with_new_policy_version_succeeds(
    client_with_db: AsyncClient,
    setup_institutions: dict[str, Any],
) -> None:
    """Audit 5 (SEC-P6-01): Advancing policy version allows new active indicator lifecycle."""
    inst_a_id = setup_institutions["inst_a"]["id"]
    mesh_id = "b2c3d4e5f67890a1" * 4

    payload_v1 = {
        "pseudonymous_mesh_id": mesh_id,
        "indicator_type": "MULE_FAN_OUT",
        "severity": "HIGH",
        "confidence_score": 0.80,
        "pattern_category": "TOPOLOGICAL_FAN_OUT",
        "evidence_summary": {
            "pattern_type": "FAN_OUT",
            "burst_count": 4,
            "anonymized_volume_tier": "TIER_LOW_UNDER_10K",
            "mulechain_rule_version": "v1.0",
        },
        "provenance": {"source": "FRAUD_OPS"},
        "validity_hours": 24,
        "sharing_policy_version": "v1.0",
    }

    # Publish v1.0
    res1 = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json=payload_v1,
        headers={"X-Institution-ID": inst_a_id},
    )
    assert res1.status_code == 201
    indicator_id_v1 = res1.json()["id"]

    # Revoke v1.0
    del_res = await client_with_db.post(
        f"/api/v1/privacy-gateway/indicators/{indicator_id_v1}/revoke",
        json={"reason": "Rule update requiring new policy version"},
        headers={"X-Institution-ID": inst_a_id},
    )
    assert del_res.status_code == 200

    # Publish v2.0 with updated findings under explicit versioning policy
    payload_v2 = dict(payload_v1)
    payload_v2["sharing_policy_version"] = "v2.0"
    payload_v2["confidence_score"] = 0.92

    res2 = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json=payload_v2,
        headers={"X-Institution-ID": inst_a_id},
    )
    assert res2.status_code == 201
    data_v2 = res2.json()
    assert data_v2["sharing_policy_version"] == "v2.0"
    assert data_v2["status"] == "ACTIVE"
    assert data_v2["confidence_score"] == 0.92


@pytest.mark.asyncio
async def test_publish_overwrites_forged_origin_in_provenance(
    client_with_db: AsyncClient,
    setup_institutions: dict[str, Any],
) -> None:
    """Audit 2 & 3 (SEC-P6-02): Submitter cannot forge origin inside provenance."""
    inst_a_id = setup_institutions["inst_a"]["id"]
    mesh_id = "c3d4e5f67890a1b2" * 4

    payload = {
        "pseudonymous_mesh_id": mesh_id,
        "indicator_type": "MULE_RAPID_PASSTHROUGH",
        "severity": "CRITICAL",
        "confidence_score": 0.95,
        "pattern_category": "RAPID_DISPERSAL",
        "evidence_summary": {
            "pattern_type": "RAPID_DRAIN",
            "anonymized_volume_tier": "TIER_HIGH_100K_TO_1M",
            "mulechain_rule_version": "v1.0",
        },
        "provenance": {
            "originating_institution_id": "forged-inst-id-999",
            "source": "SIMULATION",
        },
        "validity_hours": 12,
        "sharing_policy_version": "v1.0",
    }

    res = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json=payload,
        headers={"X-Institution-ID": inst_a_id, "X-Actor": "sec-ops-analyst"},
    )
    assert res.status_code == 201
    data = res.json()
    # Verified origin must be stamped, overriding forged field
    assert data["provenance"]["originating_institution_id"] == inst_a_id
    assert data["provenance"]["submitter_actor"] == "sec-ops-analyst"


@pytest.mark.asyncio
async def test_active_indicator_duplicate_updates_recipient_scope(
    client_with_db: AsyncClient,
    setup_institutions: dict[str, Any],
) -> None:
    """Audit 5: Updating active indicator cleanly updates target recipient scope."""
    inst_a_id = setup_institutions["inst_a"]["id"]
    inst_b_id = setup_institutions["inst_b"]["id"]
    mesh_id = "d4e5f67890a1b2c3" * 4

    payload = {
        "pseudonymous_mesh_id": mesh_id,
        "indicator_type": "MULE_BURST_INGRESS",
        "severity": "MEDIUM",
        "confidence_score": 0.65,
        "pattern_category": "TOPOLOGICAL_FAN_IN",
        "evidence_summary": {
            "pattern_type": "FAN_IN",
            "burst_count": 3,
            "anonymized_volume_tier": "TIER_LOW_UNDER_10K",
            "mulechain_rule_version": "v1.0",
        },
        "target_institution_id": None,  # Broadcast originally
        "validity_hours": 24,
        "sharing_policy_version": "v1.0",
    }

    # Publish broadcast
    res1 = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json=payload,
        headers={"X-Institution-ID": inst_a_id},
    )
    assert res1.status_code == 201
    assert res1.json()["target_institution_id"] is None

    # Update targeting Bank B specifically
    payload["target_institution_id"] = inst_b_id
    payload["severity"] = "HIGH"
    payload["confidence_score"] = 0.85

    res2 = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish",
        json=payload,
        headers={"X-Institution-ID": inst_a_id},
    )
    assert res2.status_code == 201
    data2 = res2.json()
    assert data2["target_institution_id"] == inst_b_id
    assert data2["severity"] == "HIGH"
    assert data2["confidence_score"] == 0.85


@pytest.mark.asyncio
async def test_publish_from_alert_account_validation_and_publishing(
    client_with_db: AsyncClient,
    sqlite_engine: AsyncEngine,
    setup_institutions: dict[str, Any],
) -> None:
    """Audit 3 & 4 (SEC-P6-04): Alert focal account is strictly verified against DB."""
    inst_a = setup_institutions["inst_a"]
    inst_a_id = uuid.UUID(inst_a["id"])
    inst_a_code = inst_a["institution_code"]

    # 1. Create account
    acc_res = await client_with_db.post(
        "/api/v1/accounts",
        json={
            "institution_id": str(inst_a_id),
            "account_number": "ACC-ALERT-FOCAL-01",
            "account_type": "CHECKING",
            "currency": "USD",
            "initial_balance": "50000.0000",
        },
    )
    assert acc_res.status_code == 201
    acc = acc_res.json()
    acc_id = uuid.UUID(acc["id"])

    # 2. Insert alert directly into DB
    now = datetime.now(UTC)
    session_factory = async_sessionmaker(
        bind=sqlite_engine, class_=AsyncSession, expire_on_commit=False
    )
    alert_id = uuid.uuid4()
    async with session_factory() as session:
        alert = FraudAlert(
            id=alert_id,
            alert_code="MULE_FAN_OUT",
            detector_type=DetectorType.FAN_OUT,
            severity=AlertSeverity.HIGH,
            status=AlertStatus.NEW,
            risk_score=85,
            primary_institution_id=inst_a_id,
            primary_account_id=acc_id,
            currency="USD",
            analysis_window_start=now - timedelta(hours=24),
            analysis_window_end=now,
            evidence_data={
                "pattern_type": "FAN_OUT",
                "burst_count": 8,
                "anonymized_volume_tier": "TIER_MEDIUM_10K_TO_100K",
                "mulechain_rule_version": "v1.0",
            },
            dedup_fingerprint=f"dedup-{uuid.uuid4().hex}",
            detection_rule_version="v1.0",
        )
        session.add(alert)
        await session.commit()

    # 3. Mismatch account_number -> MUST return 400 Bad Request
    mismatch_res = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish-from-alert",
        json={
            "alert_id": str(alert_id),
            "account_number": "ACC-WRONG-NUMBER",
        },
        headers={"X-Institution-ID": str(inst_a_id)},
    )
    assert mismatch_res.status_code == 400
    res_err = mismatch_res.json()
    error_msg = res_err.get("detail") or res_err.get("error", {}).get("message", "")
    assert "does not match primary account" in error_msg

    # 4. Correct account_number -> MUST succeed (201 Created)
    valid_res = await client_with_db.post(
        "/api/v1/privacy-gateway/indicators/publish-from-alert",
        json={
            "alert_id": str(alert_id),
            "account_number": "ACC-ALERT-FOCAL-01",
        },
        headers={"X-Institution-ID": str(inst_a_id)},
    )
    assert valid_res.status_code == 201
    ind_data = valid_res.json()
    assert ind_data["severity"] == "HIGH"
    assert ind_data["confidence_score"] == 0.85
    assert ind_data["originating_institution_id"] == str(inst_a_id)

    # Verify MeshID matches focal account under home institution code
    expected_mesh = compute_mesh_id(
        institution_code=inst_a_code,
        account_number="ACC-ALERT-FOCAL-01",
        purpose="FRAUD_SHARING",
    )
    assert ind_data["pseudonymous_mesh_id"] == expected_mesh
