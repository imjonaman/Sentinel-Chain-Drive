"""Integration tests for Phase 4: Deterministic Policy Engine.

Covers all 4 outcomes (ALLOW, STEP_UP, HOLD, DECLINE), precedence rules, step-up resolution,
hold resolution, idempotency, replay protection, clock skew, spending reservation limits,
and multi-tenant isolation.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from sentinel_chain_drive.core.crypto import (
    compute_transaction_intent_hash,
    generate_ed25519_keypair,
    sign_payload,
)


@pytest.fixture
async def setup_banking_environment(
    client_with_db: AsyncClient,
) -> dict[str, Any]:
    """Helper to provision institutions, accounts, an active agent,
    capabilities, and a credential.
    """
    # 1. Create origin institution
    inst_a_res = await client_with_db.post(
        "/api/v1/institutions",
        json={
            "institution_code": f"BKA_{uuid.uuid4().hex[:6].upper()}",
            "name": "Bank Alpha",
            "routing_identifier": f"RT{uuid.uuid4().hex[:6].upper()}",
        },
    )
    assert inst_a_res.status_code == 201
    inst_a = inst_a_res.json()

    # 2. Create destination institution
    inst_b_res = await client_with_db.post(
        "/api/v1/institutions",
        json={
            "institution_code": f"BKB_{uuid.uuid4().hex[:6].upper()}",
            "name": "Bank Beta",
            "routing_identifier": f"RT{uuid.uuid4().hex[:6].upper()}",
        },
    )
    assert inst_b_res.status_code == 201
    inst_b = inst_b_res.json()

    # 3. Create origin account (USD)
    acct_a_res = await client_with_db.post(
        "/api/v1/accounts",
        json={
            "institution_id": inst_a["id"],
            "account_number": f"ACCTA_{uuid.uuid4().hex[:8].upper()}",
            "account_type": "CHECKING",
            "currency": "USD",
            "initial_balance": "1000000.0000",
        },
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert acct_a_res.status_code == 201
    acct_a = acct_a_res.json()

    # 4. Create destination account (USD)
    acct_b_res = await client_with_db.post(
        "/api/v1/accounts",
        json={
            "institution_id": inst_b["id"],
            "account_number": f"ACCTB_{uuid.uuid4().hex[:8].upper()}",
            "account_type": "CHECKING",
            "currency": "USD",
            "initial_balance": "100000.0000",
        },
        headers={"X-Institution-ID": inst_b["id"]},
    )
    assert acct_b_res.status_code == 201
    acct_b = acct_b_res.json()

    # 5. Register and activate Agent
    priv_pem, pub_pem = generate_ed25519_keypair()
    agent_reg = await client_with_db.post(
        f"/api/v1/institutions/{inst_a['id']}/agents",
        json={
            "institution_id": inst_a["id"],
            "name": "Autonomous Payment Agent X",
            "owner_contact": "admin@bankalpha.com",
            "public_key": pub_pem,
        },
    )
    assert agent_reg.status_code == 201
    agent = agent_reg.json()

    agent_act = await client_with_db.post(
        f"/api/v1/institutions/{inst_a['id']}/agents/{agent['id']}/status",
        json={"status": "ACTIVE", "reason": "Authorized for automated payments"},
    )
    assert agent_act.status_code == 200
    agent = agent_act.json()

    # 6. Assign capability envelope (single limit 25,000, daily limit 50,000)
    now = datetime.now(UTC)
    cap_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_a['id']}/capabilities",
        json={
            "agent_id": agent["id"],
            "name": "Standard Wire Capability",
            "max_amount_per_transaction": "25000.0000",
            "max_daily_cumulative_amount": "50000.0000",
            "permitted_currencies": ["USD"],
            "permitted_transaction_types": ["TRANSFER", "PAYMENT"],
            "purpose_codes": ["TRANSFER", "SUPPLIER_PAYMENT"],
            "valid_until": (now + timedelta(days=30)).isoformat(),
            "created_by": "sec_admin",
        },
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert cap_res.status_code == 201
    cap = cap_res.json()

    # 7. Issue Agent Credential
    cred_res = await client_with_db.post(
        f"/api/v1/institutions/{inst_a['id']}/credentials",
        json={
            "agent_id": agent["id"],
            "institution_id": inst_a["id"],
            "valid_hours": 24,
            "signature": "dummy_cred_sig",
        },
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert cred_res.status_code == 201
    cred = cred_res.json()

    return {
        "institution_a": inst_a,
        "institution_b": inst_b,
        "account_a": acct_a,
        "account_b": acct_b,
        "agent": agent,
        "agent_private_key": priv_pem,
        "capability": cap,
        "credential": cred,
    }


def create_signed_evaluation_payload(
    env: dict[str, Any],
    amount: str = "2500.0000",
    currency: str = "USD",
    nonce: str | None = None,
    timestamp: datetime | None = None,
    risk_score: float | None = None,
    velocity_warning: bool = False,
    manual_review_flag: bool = False,
    transaction_id: str | None = None,
) -> dict[str, Any]:
    """Helper to assemble and sign a valid PolicyEvaluationRequest."""
    inst_a = env["institution_a"]
    inst_b = env["institution_b"]
    acct_a = env["account_a"]
    acct_b = env["account_b"]
    agent = env["agent"]
    priv_pem = env["agent_private_key"]
    cred = env["credential"]

    now = timestamp or datetime.now(UTC)
    req_nonce = nonce or f"nonce-{uuid.uuid4().hex}"

    tx_intent = {
        "amount": amount,
        "currency": currency,
        "origin_institution_code": inst_a["institution_code"],
        "origin_account_number": acct_a["account_number"],
        "destination_institution_code": inst_b["institution_code"],
        "destination_account_number": acct_b["account_number"],
        "transaction_type": "TRANSFER",
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

    auth_payload = {
        "credential_id": cred["credential_id"],
        "agent_id": agent["id"],
        "institution_id": inst_a["id"],
        "nonce": req_nonce,
        "request_timestamp": now.isoformat(),
        "transaction_hash": tx_hash,
    }
    sig = sign_payload(priv_pem, auth_payload)

    return {
        "idempotency_key": f"idemp-{uuid.uuid4().hex}",
        "credential_id": cred["credential_id"],
        "agent_id": agent["id"],
        "institution_id": inst_a["id"],
        "nonce": req_nonce,
        "request_timestamp": now.isoformat(),
        "transaction": tx_intent,
        "signature": sig,
        "transaction_id": transaction_id,
        "risk_signals": {
            "risk_score": risk_score,
            "velocity_warning": velocity_warning,
            "manual_review_flag": manual_review_flag,
        },
    }


@pytest.mark.asyncio
async def test_policy_evaluation_allow_outcome(
    client_with_db: AsyncClient,
    setup_banking_environment: dict[str, Any],
) -> None:
    """Verify clean ALLOW outcome for standard benign transaction."""
    env = setup_banking_environment
    inst_a = env["institution_a"]

    req_payload = create_signed_evaluation_payload(env, amount="2500.0000", risk_score=0.10)
    res = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req_payload,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["decision"] == "ALLOW"
    assert "POLICY_EVALUATION_PASSED" in data["reason_codes"]
    assert data["step_up_challenge"] is None
    assert data["hold"] is None
    assert data["audit_record_id"] is not None


@pytest.mark.asyncio
async def test_policy_evaluation_step_up_and_completion_flow(
    client_with_db: AsyncClient,
    setup_banking_environment: dict[str, Any],
) -> None:
    """Verify STEP_UP trigger when amount >= $10,000 threshold, and supervisor completion."""
    env = setup_banking_environment
    inst_a = env["institution_a"]
    agent = env["agent"]

    req_payload = create_signed_evaluation_payload(env, amount="12000.0000", risk_score=0.20)
    eval_res = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req_payload,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert eval_data["decision"] == "STEP_UP"
    assert "STEP_UP_AMOUNT_THRESHOLD_REACHED" in eval_data["reason_codes"]

    challenge_info = eval_data["step_up_challenge"]
    assert challenge_info is not None
    challenge_id = challenge_info["challenge_id"]
    assert challenge_info["status"] == "PENDING"
    assert challenge_info["required_role"] == "SUPERVISOR"

    # Separation of duties: Agent cannot approve its own step-up challenge
    agent_approval = await client_with_db.post(
        f"/api/v1/policies/step-up/{challenge_id}/complete",
        json={
            "approver_id": agent["id"],  # Same as initiating agent!
            "decision": "APPROVED",
            "reason": "Self approval attempt",
        },
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert agent_approval.status_code == 403
    assert agent_approval.json()["error"]["code"] == "SEPARATION_OF_DUTIES_VIOLATION"

    # Authorized supervisor approves challenge
    sup_approval = await client_with_db.post(
        f"/api/v1/policies/step-up/{challenge_id}/complete",
        json={
            "approver_id": "supervisor_charles",
            "decision": "APPROVED",
            "reason": "Large invoice approved per contract #1234",
        },
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert sup_approval.status_code == 200
    sup_data = sup_approval.json()
    assert sup_data["status"] == "COMPLETED"
    assert sup_data["approver_id"] == "supervisor_charles"

    # Fetch updated evaluation decision: it is now ALLOW
    eval_id = eval_data["audit_record_id"]
    updated_eval = await client_with_db.get(
        f"/api/v1/policies/evaluations/{eval_id}",
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert updated_eval.status_code == 200
    assert updated_eval.json()["decision"] == "ALLOW"


@pytest.mark.asyncio
async def test_policy_evaluation_step_up_rejection(
    client_with_db: AsyncClient,
    setup_banking_environment: dict[str, Any],
) -> None:
    """Verify that a rejected step-up challenge transitions decision to DECLINE."""
    env = setup_banking_environment
    inst_a = env["institution_a"]

    req_payload = create_signed_evaluation_payload(env, amount="15000.0000")
    eval_res = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req_payload,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert eval_data["decision"] == "STEP_UP"
    challenge_id = eval_data["step_up_challenge"]["challenge_id"]

    # Supervisor rejects
    rej_res = await client_with_db.post(
        f"/api/v1/policies/step-up/{challenge_id}/complete",
        json={
            "approver_id": "supervisor_charles",
            "decision": "REJECTED",
            "reason": "Duplicate invoice suspected",
        },
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert rej_res.status_code == 200
    assert rej_res.json()["status"] == "REJECTED"

    # Verify decision is now DECLINE
    eval_id = eval_data["audit_record_id"]
    updated_eval = await client_with_db.get(
        f"/api/v1/policies/evaluations/{eval_id}",
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert updated_eval.status_code == 200
    assert updated_eval.json()["decision"] == "DECLINE"


@pytest.mark.asyncio
async def test_policy_evaluation_hold_and_resolution_flow(
    client_with_db: AsyncClient,
    setup_banking_environment: dict[str, Any],
) -> None:
    """Verify HOLD trigger on high risk score, and fraud analyst resolution."""
    env = setup_banking_environment
    inst_a = env["institution_a"]

    req_payload = create_signed_evaluation_payload(env, amount="1000.0000", risk_score=0.91)
    eval_res = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req_payload,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert eval_data["decision"] == "HOLD"
    assert "HOLD_HIGH_RISK_SCORE" in eval_data["reason_codes"]

    hold_info = eval_data["hold"]
    assert hold_info is not None
    hold_id = hold_info["hold_id"]
    assert hold_info["status"] == "ACTIVE"
    assert hold_info["review_workflow"] == "FRAUD_INVESTIGATION"

    # Fraud analyst resolves hold by releasing
    resolve_res = await client_with_db.post(
        f"/api/v1/policies/holds/{hold_id}/resolve",
        json={
            "resolution": "RELEASE",
            "resolved_by": "analyst_david",
            "notes": "Customer confirmed legitimate emergency wire.",
        },
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert resolve_res.status_code == 200
    assert resolve_res.json()["status"] == "RELEASED"

    # Evaluation decision updated to ALLOW
    eval_id = eval_data["audit_record_id"]
    updated_eval = await client_with_db.get(
        f"/api/v1/policies/evaluations/{eval_id}",
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert updated_eval.status_code == 200
    assert updated_eval.json()["decision"] == "ALLOW"


@pytest.mark.asyncio
async def test_idempotent_retry_and_conflict_rejection(
    client_with_db: AsyncClient,
    setup_banking_environment: dict[str, Any],
) -> None:
    """Verify exact idempotent retry returns identical response; conflicting intent returns 409."""
    env = setup_banking_environment
    inst_a = env["institution_a"]

    req_payload = create_signed_evaluation_payload(env, amount="1500.0000")
    res1 = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req_payload,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert res1.status_code == 200
    data1 = res1.json()

    # Exact duplicate submission
    res2 = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req_payload,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data1["decision"] == data2["decision"]
    assert data1["audit_record_id"] == data2["audit_record_id"]

    # Reusing idempotency key with different amount -> 409 Conflict
    conflict_payload = dict(req_payload)
    conflict_payload["transaction"] = dict(req_payload["transaction"])
    conflict_payload["transaction"]["amount"] = "9999.0000"

    res_conflict = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=conflict_payload,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert res_conflict.status_code == 409
    assert res_conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


@pytest.mark.asyncio
async def test_replay_attack_rejected(
    client_with_db: AsyncClient,
    setup_banking_environment: dict[str, Any],
) -> None:
    """Reusing a nonce in a new evaluation request must fail closed
    with REPLAY_DETECTED_NONCE_REUSED.
    """
    env = setup_banking_environment
    inst_a = env["institution_a"]

    fixed_nonce = f"nonce-{uuid.uuid4().hex}"
    req1 = create_signed_evaluation_payload(env, nonce=fixed_nonce)

    res1 = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req1,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert res1.status_code == 200

    # New request attempting to reuse the consumed nonce
    req2 = create_signed_evaluation_payload(env, nonce=fixed_nonce, amount="500.0000")
    res2 = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req2,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["decision"] == "DECLINE"
    assert "REPLAY_DETECTED_NONCE_REUSED" in data2["reason_codes"]


@pytest.mark.asyncio
async def test_clock_skew_rejected(
    client_with_db: AsyncClient,
    setup_banking_environment: dict[str, Any],
) -> None:
    """Request with timestamp skewed > 300 seconds must fail closed."""
    env = setup_banking_environment
    inst_a = env["institution_a"]

    stale_time = datetime.now(UTC) - timedelta(seconds=350)
    req = create_signed_evaluation_payload(env, timestamp=stale_time)

    res = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["decision"] == "DECLINE"
    assert any("CLOCK_SKEW_EXCEEDED" in r for r in data["reason_codes"])


@pytest.mark.asyncio
async def test_spending_reservation_concurrency_protection(
    client_with_db: AsyncClient,
    setup_banking_environment: dict[str, Any],
) -> None:
    """Verify that active spending reservations prevent concurrent
    transactions from exceeding daily limits.
    """
    env = setup_banking_environment
    inst_a = env["institution_a"]
    # Capability envelope has daily limit 50,000 and single limit 25,000

    # Tx 1: $24,000 -> ALLOW (creates active reservation of $24,000)
    req1 = create_signed_evaluation_payload(env, amount="24000.0000")
    res1 = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req1,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert res1.status_code == 200
    assert res1.json()["decision"] in ("ALLOW", "STEP_UP")

    # Tx 2: $24,000 -> ALLOW/STEP_UP (creates active reservation, total reserved = $48,000)
    req2 = create_signed_evaluation_payload(env, amount="24000.0000")
    res2 = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req2,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert res2.status_code == 200
    assert res2.json()["decision"] in ("ALLOW", "STEP_UP")

    # Tx 3: $5,000 -> Total velocity = $48,000 + $5,000 = $53,000 > $50,000 -> DECLINE!
    req3 = create_signed_evaluation_payload(env, amount="5000.0000")
    res3 = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req3,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["decision"] == "DECLINE"
    assert any("CAPABILITY_DAILY_LIMIT_EXCEEDED" in r for r in data3["reason_codes"])


@pytest.mark.asyncio
async def test_multi_tenant_boundary_isolation(
    client_with_db: AsyncClient,
    setup_banking_environment: dict[str, Any],
) -> None:
    """X-Institution-ID header mismatching request payload must be rejected with 403 Forbidden."""
    env = setup_banking_environment
    inst_b = env["institution_b"]

    req = create_signed_evaluation_payload(env)
    # Header says Bank B, but payload is for Bank A
    res = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req,
        headers={"X-Institution-ID": inst_b["id"]},
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "CROSS_INSTITUTION_ACCESS_FORBIDDEN"


@pytest.mark.asyncio
async def test_investigator_detail_shields_internals_on_public_endpoint(
    client_with_db: AsyncClient,
    setup_banking_environment: dict[str, Any],
) -> None:
    """Verify that public endpoints shield rule IDs, but investigator
    detail endpoint reveals them.
    """
    env = setup_banking_environment
    inst_a = env["institution_a"]

    req = create_signed_evaluation_payload(env, amount="1000.0000")
    eval_res = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert eval_res.status_code == 200
    pub_data = eval_res.json()
    # Public endpoint does not expose internal rule mechanics
    assert "applicable_rule_ids" not in pub_data
    assert "evaluation_evidence" not in pub_data

    # Investigator detail endpoint
    eval_id = pub_data["audit_record_id"]
    detail_res = await client_with_db.get(
        f"/api/v1/policies/evaluations/{eval_id}/detail",
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert "applicable_rule_ids" in detail_data
    assert "evaluation_evidence" in detail_data
    assert detail_data["applicable_rule_ids"] == ["RULE_DEFAULT_ALLOW"]


@pytest.mark.asyncio
async def test_policy_versioning_and_lifecycle(
    client_with_db: AsyncClient,
    setup_banking_environment: dict[str, Any],
) -> None:
    """Verify policy version creation, automatic deactivation of prior versions,
    and rule enforcement.
    """
    env = setup_banking_environment
    inst_a = env["institution_a"]

    # 1. Create custom policy v1 for Bank A with strict $3,000 limit
    p1_res = await client_with_db.post(
        "/api/v1/policies",
        json={
            "institution_id": inst_a["id"],
            "policy_code": "CUSTOM_STRICT_POLICY",
            "name": "Strict Bank A Policy v1",
            "priority": 10,
            "rules": {
                "max_transaction_amount": "3000.0000",
                "step_up_threshold_amount": "2000.0000",
            },
        },
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert p1_res.status_code == 201
    p1 = p1_res.json()
    assert p1["version"] == 1
    assert p1["is_active"] is True

    # Evaluate $4,000 transaction -> DECLINE (exceeds $3,000 cap)
    req1 = create_signed_evaluation_payload(env, amount="4000.0000")
    res_decl = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req1,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert res_decl.status_code == 200
    assert res_decl.json()["decision"] == "DECLINE"
    assert "POLICY_MAX_TRANSACTION_AMOUNT_EXCEEDED" in res_decl.json()["reason_codes"]

    # 2. Upgrade to policy v2 with higher $10,000 limit
    p2_res = await client_with_db.post(
        "/api/v1/policies",
        json={
            "institution_id": inst_a["id"],
            "policy_code": "CUSTOM_STRICT_POLICY",
            "name": "Relaxed Bank A Policy v2",
            "priority": 10,
            "rules": {
                "max_transaction_amount": "10000.0000",
                "step_up_threshold_amount": "5000.0000",
            },
        },
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert p2_res.status_code == 201
    p2 = p2_res.json()
    assert p2["version"] == 2
    assert p2["is_active"] is True

    # Prior version v1 should now be inactive
    p1_check = await client_with_db.get(
        f"/api/v1/policies/{p1['id']}",
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert p1_check.status_code == 200
    assert p1_check.json()["is_active"] is False

    # Evaluate $4,000 transaction under v2 -> ALLOW!
    req2 = create_signed_evaluation_payload(env, amount="4000.0000")
    res_allow = await client_with_db.post(
        "/api/v1/policies/evaluate",
        json=req2,
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert res_allow.status_code == 200
    assert res_allow.json()["decision"] == "ALLOW"
    assert res_allow.json()["policy_version"] == 2
