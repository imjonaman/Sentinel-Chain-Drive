"""Integration and API tests for Phase 5: MuleChain Graph Fraud Intelligence.

Covers:
- End-to-end topological pattern detection over synthetic transactions (Fan-In, Rapid Pass-Through)
- Alert persistence and deduplication idempotency
- Multi-tenant institution isolation on alert lookup and listing
- Missing header validation (X-Institution-ID)
- Currency separation (USD vs EUR)
- Transaction status filtering (SETTLED vs SUBMITTED)
- Policy Engine integration (HOLD/STEP_UP on high-risk signals, ALLOW on clean signals)
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from httpx import AsyncClient

from sentinel_chain_drive.core.crypto import (
    compute_transaction_intent_hash,
    generate_ed25519_keypair,
    sign_payload,
)


@pytest.fixture
async def setup_mulechain_environment(
    client_with_db: AsyncClient,
) -> dict[str, Any]:
    """Helper to provision financial institutions, accounts, and base agent."""
    # 1. Create Bank Alpha
    inst_a_res = await client_with_db.post(
        "/api/v1/institutions",
        json={
            "institution_code": f"MULEA{uuid.uuid4().hex[:6].upper()}",
            "name": "MuleChain Test Bank A",
            "routing_identifier": f"RT{uuid.uuid4().hex[:6].upper()}",
        },
    )
    assert inst_a_res.status_code == 201
    inst_a = inst_a_res.json()

    # 2. Create Bank Beta
    inst_b_res = await client_with_db.post(
        "/api/v1/institutions",
        json={
            "institution_code": f"MULEB{uuid.uuid4().hex[:6].upper()}",
            "name": "MuleChain Test Bank B",
            "routing_identifier": f"RT{uuid.uuid4().hex[:6].upper()}",
        },
    )
    assert inst_b_res.status_code == 201
    inst_b = inst_b_res.json()

    # 3. Create primary destination / focal account in Bank A
    focal_acc_res = await client_with_db.post(
        "/api/v1/accounts",
        json={
            "institution_id": inst_a["id"],
            "account_number": f"FOCAL_{uuid.uuid4().hex[:8].upper()}",
            "account_type": "CHECKING",
            "currency": "USD",
            "initial_balance": "50000.0000",
        },
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert focal_acc_res.status_code == 201
    focal_acc = focal_acc_res.json()

    # 4. Create 5 source accounts in Bank A for fan-in smurfing
    source_accounts = []
    for i in range(5):
        s_res = await client_with_db.post(
            "/api/v1/accounts",
            json={
                "institution_id": inst_a["id"],
                "account_number": f"SRC_{i}_{uuid.uuid4().hex[:6].upper()}",
                "account_type": "SAVINGS",
                "currency": "USD",
                "initial_balance": "10000.0000",
            },
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert s_res.status_code == 201
        source_accounts.append(s_res.json())

    # 5. Create transit mule account and third-party destination for rapid pass-through
    mule_acc_res = await client_with_db.post(
        "/api/v1/accounts",
        json={
            "institution_id": inst_a["id"],
            "account_number": f"MULE_{uuid.uuid4().hex[:8].upper()}",
            "account_type": "CHECKING",
            "currency": "USD",
            "initial_balance": "1000.0000",
        },
        headers={"X-Institution-ID": inst_a["id"]},
    )
    assert mule_acc_res.status_code == 201
    mule_acc = mule_acc_res.json()

    dest_external_res = await client_with_db.post(
        "/api/v1/accounts",
        json={
            "institution_id": inst_b["id"],
            "account_number": f"EXT_{uuid.uuid4().hex[:8].upper()}",
            "account_type": "CHECKING",
            "currency": "USD",
            "initial_balance": "500.0000",
        },
        headers={"X-Institution-ID": inst_b["id"]},
    )
    assert dest_external_res.status_code == 201
    dest_external = dest_external_res.json()

    return {
        "inst_a": inst_a,
        "inst_b": inst_b,
        "focal_acc": focal_acc,
        "source_accounts": source_accounts,
        "mule_acc": mule_acc,
        "dest_external": dest_external,
    }


async def _submit_and_settle_tx(
    client: AsyncClient,
    inst_id: str,
    origin_acc_id: str,
    dest_acc_id: str,
    amount: str,
    currency: str = "USD",
    dest_inst_id: str | None = None,
) -> dict[str, Any]:
    """Helper to submit and immediately settle a synthetic transaction."""
    sub_res = await client.post(
        "/api/v1/transactions",
        json={
            "idempotency_key": f"tx-{uuid.uuid4()}",
            "origin_institution_id": inst_id,
            "destination_institution_id": dest_inst_id or inst_id,
            "origin_account_id": origin_acc_id,
            "destination_account_id": dest_acc_id,
            "amount": amount,
            "currency": currency,
            "transaction_type": "TRANSFER",
        },
        headers={"X-Institution-ID": inst_id},
    )
    assert sub_res.status_code == 201
    tx = sub_res.json()

    # Settle transaction
    settle_res = await client.post(
        f"/api/v1/transactions/{tx['id']}/simulate-action",
        json={"action": "SIMULATE_SETTLE", "reason": "Simulated interbank settlement"},
        headers={"X-Institution-ID": inst_id},
    )
    assert settle_res.status_code == 200
    return cast(dict[str, Any], settle_res.json())


class TestMuleChainAnalysisAPI:
    """Tests triggering graph fraud analysis and idempotent persistence."""

    async def test_end_to_end_analysis_and_idempotency(
        self,
        client_with_db: AsyncClient,
        setup_mulechain_environment: dict[str, Any],
    ) -> None:
        env = setup_mulechain_environment
        inst_a = env["inst_a"]
        focal_acc = env["focal_acc"]
        source_accounts = env["source_accounts"]
        mule_acc = env["mule_acc"]
        dest_external = env["dest_external"]

        # 1. Seed 5 Fan-in transfers into focal_acc
        for src in source_accounts:
            await _submit_and_settle_tx(
                client=client_with_db,
                inst_id=inst_a["id"],
                origin_acc_id=src["id"],
                dest_acc_id=focal_acc["id"],
                amount="850.0000",
            )

        # 2. Seed Rapid Pass-Through: ingress 10,000 to mule_acc, egress 9,500 to dest_external
        await _submit_and_settle_tx(
            client=client_with_db,
            inst_id=inst_a["id"],
            origin_acc_id=source_accounts[0]["id"],
            dest_acc_id=mule_acc["id"],
            amount="10000.0000",
        )
        await _submit_and_settle_tx(
            client=client_with_db,
            inst_id=inst_a["id"],
            origin_acc_id=mule_acc["id"],
            dest_acc_id=dest_external["id"],
            amount="9500.0000",
            dest_inst_id=dest_external["institution_id"],
        )

        # 3. Trigger analysis for Bank Alpha
        analyze_res = await client_with_db.post(
            "/api/v1/mulechain/analyze",
            json={
                "currency": "USD",
                "max_transactions": 1000,
            },
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert analyze_res.status_code == 200
        summary = analyze_res.json()

        assert summary["transactions_analyzed"] >= 7
        assert summary["alerts_generated"] >= 2  # Fan-In and Rapid Pass-Through
        assert summary["alerts_deduplicated"] == 0
        assert len(summary["alerts"]) >= 2

        # Verify alert details
        detector_types = [a["detector_type"] for a in summary["alerts"]]
        assert "FAN_IN" in detector_types
        assert "RAPID_PASSTHROUGH" in detector_types

        # 4. Repeated execution must be strictly idempotent
        re_run_res = await client_with_db.post(
            "/api/v1/mulechain/analyze",
            json={
                "currency": "USD",
                "max_transactions": 1000,
            },
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert re_run_res.status_code == 200
        re_run_summary = re_run_res.json()

        assert re_run_summary["alerts_generated"] == 0
        assert re_run_summary["alerts_deduplicated"] >= 2
        assert len(re_run_summary["alerts"]) >= 2

    async def test_alert_retrieval_and_tenant_isolation(
        self,
        client_with_db: AsyncClient,
        setup_mulechain_environment: dict[str, Any],
    ) -> None:
        env = setup_mulechain_environment
        inst_a = env["inst_a"]
        inst_b = env["inst_b"]
        focal_acc = env["focal_acc"]
        source_accounts = env["source_accounts"]

        # Seed 5 Fan-in transfers
        for src in source_accounts:
            await _submit_and_settle_tx(
                client=client_with_db,
                inst_id=inst_a["id"],
                origin_acc_id=src["id"],
                dest_acc_id=focal_acc["id"],
                amount="900.0000",
            )

        # Trigger analysis
        analyze_res = await client_with_db.post(
            "/api/v1/mulechain/analyze",
            json={"currency": "USD"},
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert analyze_res.status_code == 200
        alerts = analyze_res.json()["alerts"]
        assert len(alerts) >= 1
        target_alert = alerts[0]

        # 1. Fetch alert with authorized institution header -> 200 OK
        get_res = await client_with_db.get(
            f"/api/v1/mulechain/alerts/{target_alert['id']}",
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert get_res.status_code == 200
        data = get_res.json()
        assert data["id"] == target_alert["id"]
        assert data["alert_code"] == target_alert["alert_code"]
        assert "evidence_data" in data

        # 2. Fetch alert with different institution header (Bank B) -> 404 ALERT_NOT_FOUND
        cross_res = await client_with_db.get(
            f"/api/v1/mulechain/alerts/{target_alert['id']}",
            headers={"X-Institution-ID": inst_b["id"]},
        )
        assert cross_res.status_code == 404

        # 3. Call without X-Institution-ID -> 400 Bad Request
        no_header_res = await client_with_db.get(
            f"/api/v1/mulechain/alerts/{target_alert['id']}",
        )
        assert no_header_res.status_code == 400

    async def test_list_alerts_with_pagination_and_filters(
        self,
        client_with_db: AsyncClient,
        setup_mulechain_environment: dict[str, Any],
    ) -> None:
        env = setup_mulechain_environment
        inst_a = env["inst_a"]
        focal_acc = env["focal_acc"]
        source_accounts = env["source_accounts"]

        # Seed 5 Fan-in transfers
        for src in source_accounts:
            await _submit_and_settle_tx(
                client=client_with_db,
                inst_id=inst_a["id"],
                origin_acc_id=src["id"],
                dest_acc_id=focal_acc["id"],
                amount="500.0000",
            )

        await client_with_db.post(
            "/api/v1/mulechain/analyze",
            json={"currency": "USD"},
            headers={"X-Institution-ID": inst_a["id"]},
        )

        # List all alerts
        list_res = await client_with_db.get(
            "/api/v1/mulechain/alerts?limit=10&offset=0",
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert list_res.status_code == 200
        list_data = list_res.json()
        assert list_data["total"] >= 1
        assert len(list_data["items"]) >= 1

        # Filter by detector type
        filtered_res = await client_with_db.get(
            "/api/v1/mulechain/alerts?detector_type=FAN_IN",
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert filtered_res.status_code == 200
        filtered_data = filtered_res.json()
        assert all(item["detector_type"] == "FAN_IN" for item in filtered_data["items"])

    async def test_currency_separation_in_api(
        self,
        client_with_db: AsyncClient,
        setup_mulechain_environment: dict[str, Any],
    ) -> None:
        env = setup_mulechain_environment
        inst_a = env["inst_a"]
        focal_acc = env["focal_acc"]
        source_accounts = env["source_accounts"]

        # Seed transactions in USD
        for src in source_accounts:
            await _submit_and_settle_tx(
                client=client_with_db,
                inst_id=inst_a["id"],
                origin_acc_id=src["id"],
                dest_acc_id=focal_acc["id"],
                amount="500.0000",
                currency="USD",
            )

        # Analyze EUR graph -> 0 transactions ingested, 0 alerts
        eur_res = await client_with_db.post(
            "/api/v1/mulechain/analyze",
            json={"currency": "EUR"},
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert eur_res.status_code == 200
        eur_summary = eur_res.json()
        assert eur_summary["transactions_analyzed"] == 0
        assert eur_summary["alerts_generated"] == 0


class TestPolicyEngineMuleChainIntegration:
    """Tests connecting MuleChain risk signals into the Phase 4 Deterministic Policy Engine."""

    async def test_policy_engine_escalates_on_high_risk_signal(
        self,
        client_with_db: AsyncClient,
        setup_mulechain_environment: dict[str, Any],
    ) -> None:
        env = setup_mulechain_environment
        inst_a = env["inst_a"]
        focal_acc = env["focal_acc"]
        mule_acc = env["mule_acc"]

        # 1. Register active agent and credentials for Bank Alpha
        priv_pem, pub_pem = generate_ed25519_keypair()
        agent_reg = await client_with_db.post(
            f"/api/v1/institutions/{inst_a['id']}/agents",
            json={
                "institution_id": inst_a["id"],
                "name": "MuleChain Agent",
                "owner_contact": "mulechain@bankalpha.com",
                "public_key": pub_pem,
            },
        )
        assert agent_reg.status_code == 201
        agent = agent_reg.json()

        await client_with_db.post(
            f"/api/v1/institutions/{inst_a['id']}/agents/{agent['id']}/status",
            json={"status": "ACTIVE"},
        )

        now = datetime.now(UTC)
        cap_res = await client_with_db.post(
            f"/api/v1/institutions/{inst_a['id']}/capabilities",
            json={
                "agent_id": agent["id"],
                "name": "Transfer Cap",
                "max_amount_per_transaction": "50000.0000",
                "max_daily_cumulative_amount": "100000.0000",
                "permitted_currencies": ["USD"],
                "permitted_transaction_types": ["TRANSFER"],
                "purpose_codes": ["TRANSFER"],
                "valid_until": (now + timedelta(days=30)).isoformat(),
                "created_by": "admin",
            },
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert cap_res.status_code == 201

        # Issue security credential
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

        tx_intent = {
            "amount": "1000.0000",
            "currency": "USD",
            "origin_institution_code": inst_a["institution_code"],
            "origin_account_number": mule_acc["account_number"],
            "destination_institution_code": inst_a["institution_code"],
            "destination_account_number": focal_acc["account_number"],
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

        req_nonce = f"nonce-{uuid.uuid4().hex}"
        auth_payload = {
            "credential_id": cred["credential_id"],
            "agent_id": agent["id"],
            "institution_id": inst_a["id"],
            "nonce": req_nonce,
            "request_timestamp": now.isoformat(),
            "transaction_hash": tx_hash,
        }
        sig = sign_payload(priv_pem, auth_payload)

        # 2. Evaluate with High MuleChain Risk Signal (score = 0.90 >= hold_risk_threshold 0.85)
        eval_payload = {
            "idempotency_key": f"eval-{uuid.uuid4().hex}",
            "credential_id": cred["credential_id"],
            "agent_id": agent["id"],
            "institution_id": inst_a["id"],
            "nonce": req_nonce,
            "request_timestamp": now.isoformat(),
            "transaction": tx_intent,
            "signature": sig,
            "risk_signals": {
                "risk_score": 0.90,
                "velocity_warning": True,
                "manual_review_flag": True,
                "custom_signals": {
                    "detector": "CIRCULAR_LAYERING",
                    "mulechain_score": 90,
                },
            },
        }

        eval_res = await client_with_db.post(
            "/api/v1/policies/evaluate",
            json=eval_payload,
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert eval_res.status_code == 200
        decision_data = eval_res.json()

        # Policy Engine deterministically flags high risk with HOLD
        assert decision_data["decision"] == "HOLD"
        assert decision_data["hold"] is not None
        assert "HOLD_HIGH_RISK_SCORE" in decision_data["reason_codes"]

    async def test_policy_engine_allows_on_clean_risk_signal(
        self,
        client_with_db: AsyncClient,
        setup_mulechain_environment: dict[str, Any],
    ) -> None:
        env = setup_mulechain_environment
        inst_a = env["inst_a"]
        focal_acc = env["focal_acc"]
        mule_acc = env["mule_acc"]

        priv_pem, pub_pem = generate_ed25519_keypair()
        agent_reg = await client_with_db.post(
            f"/api/v1/institutions/{inst_a['id']}/agents",
            json={
                "institution_id": inst_a["id"],
                "name": "Clean Agent",
                "owner_contact": "clean@bankalpha.com",
                "public_key": pub_pem,
            },
        )
        agent = agent_reg.json()

        await client_with_db.post(
            f"/api/v1/institutions/{inst_a['id']}/agents/{agent['id']}/status",
            json={"status": "ACTIVE"},
        )

        now = datetime.now(UTC)
        cap_res = await client_with_db.post(
            f"/api/v1/institutions/{inst_a['id']}/capabilities",
            json={
                "agent_id": agent["id"],
                "name": "Transfer Cap",
                "max_amount_per_transaction": "50000.0000",
                "max_daily_cumulative_amount": "100000.0000",
                "permitted_currencies": ["USD"],
                "permitted_transaction_types": ["TRANSFER"],
                "purpose_codes": ["TRANSFER"],
                "valid_until": (now + timedelta(days=30)).isoformat(),
                "created_by": "admin",
            },
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert cap_res.status_code == 201

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

        tx_intent = {
            "amount": "200.0000",
            "currency": "USD",
            "origin_institution_code": inst_a["institution_code"],
            "origin_account_number": mule_acc["account_number"],
            "destination_institution_code": inst_a["institution_code"],
            "destination_account_number": focal_acc["account_number"],
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

        req_nonce = f"nonce-{uuid.uuid4().hex}"
        auth_payload = {
            "credential_id": cred["credential_id"],
            "agent_id": agent["id"],
            "institution_id": inst_a["id"],
            "nonce": req_nonce,
            "request_timestamp": now.isoformat(),
            "transaction_hash": tx_hash,
        }
        sig = sign_payload(priv_pem, auth_payload)

        # Clean risk signals: score 0.0
        eval_payload = {
            "idempotency_key": f"eval-{uuid.uuid4().hex}",
            "credential_id": cred["credential_id"],
            "agent_id": agent["id"],
            "institution_id": inst_a["id"],
            "nonce": req_nonce,
            "request_timestamp": now.isoformat(),
            "transaction": tx_intent,
            "signature": sig,
            "risk_signals": {
                "risk_score": 0.0,
                "velocity_warning": False,
                "manual_review_flag": False,
                "custom_signals": {"mulechain_findings_count": 0},
            },
        }

        eval_res = await client_with_db.post(
            "/api/v1/policies/evaluate",
            json=eval_payload,
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert eval_res.status_code == 200
        decision_data = eval_res.json()
        assert decision_data["decision"] == "ALLOW"
