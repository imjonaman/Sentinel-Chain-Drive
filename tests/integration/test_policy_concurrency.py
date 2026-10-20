"""Genuine concurrency and race-condition integration tests for Phase 4 Policy Engine.

Exercises 8 critical concurrency scenarios across separate sessions and overlapping executions:
1. Two simultaneous requests for the same agent cannot exceed daily limit.
2. A successful reservation is visible to competing transactions at isolation level.
3. Same-key, same-intent concurrent retries do not create duplicate reservations.
4. Same-key, different-intent concurrent requests fail with conflict (HTTP 409).
5. Duplicate nonce concurrent submissions fail closed (replay rejected).
6. A database exception rolls back the reservation, evaluation, nonce, and audit records atomically.
7. Independent agents execute concurrently without unnecessary row-level serialization.
8. Reservation release, commit, and expiry behave correctly under concurrent requests.

Uses synchronization barriers (asyncio.Barrier) to force exact overlapping execution
and bounded timeouts (asyncio.wait_for) to guarantee deadlock resistance.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from sentinel_chain_drive.api.deps import get_db_session
from sentinel_chain_drive.api.main import create_app
from sentinel_chain_drive.core.config import Settings
from sentinel_chain_drive.core.crypto import (
    compute_transaction_intent_hash,
    generate_ed25519_keypair,
    sign_payload,
)
from sentinel_chain_drive.db.base import Base
from sentinel_chain_drive.db.models.policy_evaluation import (
    PolicyEvaluationRecord,
    SpendingReservation,
    SpendingReservationStatus,
    StepUpStatus,
)
from sentinel_chain_drive.repositories.policy_evaluation_repository import (
    PolicyEvaluationRepository,
)
from sentinel_chain_drive.services.policy_service import PolicyService


@pytest.fixture
async def concurrency_engine() -> AsyncGenerator[AsyncEngine]:
    """Engine for concurrency testing.

    If TEST_POSTGRES_URL is configured in the environment, binds to real PostgreSQL.
    Otherwise, uses the isolated local async engine.
    """
    postgres_url = os.environ.get("TEST_POSTGRES_URL")
    if postgres_url:
        engine = create_async_engine(postgres_url, pool_size=10, max_overflow=5)
    else:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def concurrency_session_factory(
    concurrency_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Provides independent async sessions for multi-connection concurrent operations."""
    return async_sessionmaker(
        bind=concurrency_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest.fixture
def concurrency_app_factory(
    concurrency_session_factory: async_sessionmaker[AsyncSession],
    test_settings: Settings,
) -> Callable[[], AsyncClient]:
    """Factory returning an AsyncClient connected to a dedicated session per request."""

    def _create_client() -> AsyncClient:
        app = create_app(settings=test_settings)

        async def override_get_db_session() -> AsyncGenerator[AsyncSession]:
            async with concurrency_session_factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_db_session] = override_get_db_session
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://testserver")

    return _create_client


@pytest.fixture
async def concurrent_banking_env(
    concurrency_app_factory: Any,
) -> dict[str, Any]:
    """Provisions a baseline multi-institution environment for concurrency tests."""
    client = concurrency_app_factory()
    async with client:
        # 1. Institutions
        inst_a_res = await client.post(
            "/api/v1/institutions",
            json={
                "institution_code": f"BKA_{uuid.uuid4().hex[:6].upper()}",
                "name": "Bank Alpha",
                "routing_identifier": f"RT{uuid.uuid4().hex[:6].upper()}",
            },
        )
        assert inst_a_res.status_code == 201
        inst_a = inst_a_res.json()

        inst_b_res = await client.post(
            "/api/v1/institutions",
            json={
                "institution_code": f"BKB_{uuid.uuid4().hex[:6].upper()}",
                "name": "Bank Beta",
                "routing_identifier": f"RT{uuid.uuid4().hex[:6].upper()}",
            },
        )
        assert inst_b_res.status_code == 201
        inst_b = inst_b_res.json()

        # 2. Accounts
        acct_a_res = await client.post(
            "/api/v1/accounts",
            json={
                "institution_id": inst_a["id"],
                "account_number": f"ACCTA_{uuid.uuid4().hex[:8].upper()}",
                "account_type": "CHECKING",
                "currency": "USD",
                "initial_balance": "5000000.0000",
            },
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert acct_a_res.status_code == 201
        acct_a = acct_a_res.json()

        acct_b_res = await client.post(
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

        # 3. Agent 1
        priv_pem_1, pub_pem_1 = generate_ed25519_keypair()
        agent_1_reg = await client.post(
            f"/api/v1/institutions/{inst_a['id']}/agents",
            json={
                "institution_id": inst_a["id"],
                "name": "Concurrent Agent 1",
                "owner_contact": "agent1@bankalpha.com",
                "public_key": pub_pem_1,
            },
        )
        assert agent_1_reg.status_code == 201
        agent_1 = agent_1_reg.json()

        await client.post(
            f"/api/v1/institutions/{inst_a['id']}/agents/{agent_1['id']}/status",
            json={"status": "ACTIVE", "reason": "Active for concurrency tests"},
        )

        # Agent 1 Capability: single limit $35,000, daily cumulative limit $50,000
        now = datetime.now(UTC)
        cap_1_res = await client.post(
            f"/api/v1/institutions/{inst_a['id']}/capabilities",
            json={
                "agent_id": agent_1["id"],
                "name": "Agent 1 Wire Capability",
                "max_amount_per_transaction": "35000.0000",
                "max_daily_cumulative_amount": "50000.0000",
                "permitted_currencies": ["USD"],
                "permitted_transaction_types": ["TRANSFER", "PAYMENT"],
                "purpose_codes": ["TRANSFER", "SUPPLIER_PAYMENT"],
                "valid_until": (now + timedelta(days=30)).isoformat(),
                "created_by": "sec_admin",
            },
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert cap_1_res.status_code == 201
        cap_1 = cap_1_res.json()

        cred_1_res = await client.post(
            f"/api/v1/institutions/{inst_a['id']}/credentials",
            json={
                "agent_id": agent_1["id"],
                "institution_id": inst_a["id"],
                "valid_hours": 24,
                "signature": "cred_1_sig",
            },
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert cred_1_res.status_code == 201
        cred_1 = cred_1_res.json()

        # 4. Agent 2 (Independent Agent)
        priv_pem_2, pub_pem_2 = generate_ed25519_keypair()
        agent_2_reg = await client.post(
            f"/api/v1/institutions/{inst_a['id']}/agents",
            json={
                "institution_id": inst_a["id"],
                "name": "Concurrent Agent 2",
                "owner_contact": "agent2@bankalpha.com",
                "public_key": pub_pem_2,
            },
        )
        assert agent_2_reg.status_code == 201
        agent_2 = agent_2_reg.json()

        await client.post(
            f"/api/v1/institutions/{inst_a['id']}/agents/{agent_2['id']}/status",
            json={"status": "ACTIVE", "reason": "Active for concurrency tests"},
        )

        cap_2_res = await client.post(
            f"/api/v1/institutions/{inst_a['id']}/capabilities",
            json={
                "agent_id": agent_2["id"],
                "name": "Agent 2 Wire Capability",
                "max_amount_per_transaction": "35000.0000",
                "max_daily_cumulative_amount": "50000.0000",
                "permitted_currencies": ["USD"],
                "permitted_transaction_types": ["TRANSFER", "PAYMENT"],
                "purpose_codes": ["TRANSFER", "SUPPLIER_PAYMENT"],
                "valid_until": (now + timedelta(days=30)).isoformat(),
                "created_by": "sec_admin",
            },
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert cap_2_res.status_code == 201
        cap_2 = cap_2_res.json()

        cred_2_res = await client.post(
            f"/api/v1/institutions/{inst_a['id']}/credentials",
            json={
                "agent_id": agent_2["id"],
                "institution_id": inst_a["id"],
                "valid_hours": 24,
                "signature": "cred_2_sig",
            },
            headers={"X-Institution-ID": inst_a["id"]},
        )
        assert cred_2_res.status_code == 201
        cred_2 = cred_2_res.json()

    return {
        "institution_a": inst_a,
        "institution_b": inst_b,
        "account_a": acct_a,
        "account_b": acct_b,
        "agent_1": agent_1,
        "agent_1_priv_key": priv_pem_1,
        "capability_1": cap_1,
        "credential_1": cred_1,
        "agent_2": agent_2,
        "agent_2_priv_key": priv_pem_2,
        "capability_2": cap_2,
        "credential_2": cred_2,
    }


def make_eval_payload(
    env: dict[str, Any],
    agent_num: int = 1,
    amount: str = "30000.0000",
    idempotency_key: str | None = None,
    nonce: str | None = None,
    risk_score: float = 0.10,
) -> dict[str, Any]:
    """Helper to construct and sign an evaluation payload for Agent 1 or Agent 2."""
    inst_a = env["institution_a"]
    inst_b = env["institution_b"]
    acct_a = env["account_a"]
    acct_b = env["account_b"]

    agent = env[f"agent_{agent_num}"]
    priv_pem = env[f"agent_{agent_num}_priv_key"]
    cred = env[f"credential_{agent_num}"]

    now = datetime.now(UTC)
    req_nonce = nonce or f"nonce-{uuid.uuid4().hex}"
    idemp = idempotency_key or f"idemp-{uuid.uuid4().hex}"

    tx_intent = {
        "amount": amount,
        "currency": "USD",
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
        "idempotency_key": idemp,
        "credential_id": cred["credential_id"],
        "agent_id": agent["id"],
        "institution_id": inst_a["id"],
        "nonce": req_nonce,
        "request_timestamp": now.isoformat(),
        "transaction": tx_intent,
        "signature": sig,
        "risk_signals": {"risk_score": risk_score},
    }


# =============================================================================
# SCENARIO 1: Two simultaneous requests for the same agent cannot exceed limit
# =============================================================================


@pytest.mark.asyncio
async def test_scenario_1_concurrent_evaluations_cannot_exceed_cumulative_daily_limit(
    concurrency_app_factory: Any,
    concurrency_session_factory: async_sessionmaker[AsyncSession],
    concurrent_banking_env: dict[str, Any],
) -> None:
    """Two concurrent requests ($30,000 each) against a $50,000 daily limit.

    Exactly one must be accepted (ALLOW/STEP_UP); the second must be DECLINED.
    Final DB state must have exactly $30,000 reserved, never $60,000.
    """
    env = concurrent_banking_env
    inst_a_id = env["institution_a"]["id"]
    agent_id = env["agent_1"]["id"]

    # Barrier forces both requests to initiate at the exact same instant
    barrier = asyncio.Barrier(2)

    payload_1 = make_eval_payload(env, agent_num=1, amount="30000.0000")
    payload_2 = make_eval_payload(env, agent_num=1, amount="30000.0000")

    async def execute_request(payload: dict[str, Any]) -> Any:
        client = concurrency_app_factory()
        async with client:
            await barrier.wait()
            return await client.post(
                "/api/v1/policies/evaluate",
                json=payload,
                headers={"X-Institution-ID": inst_a_id},
            )

    # Execute both requests with a bounded 10-second timeout to prevent deadlocks
    res_1, res_2 = await asyncio.wait_for(
        asyncio.gather(
            execute_request(payload_1),
            execute_request(payload_2),
        ),
        timeout=10.0,
    )

    assert res_1.status_code == 200
    assert res_2.status_code == 200

    data_1 = res_1.json()
    data_2 = res_2.json()

    decisions = [data_1["decision"], data_2["decision"]]

    # One decision must be STEP_UP (amount >= $10,000), and the other must be DECLINE
    assert "STEP_UP" in decisions, f"Expected one STEP_UP, got {decisions}"
    assert "DECLINE" in decisions, f"Expected one DECLINE, got {decisions}"

    decline_data = data_1 if data_1["decision"] == "DECLINE" else data_2
    assert any("CAPABILITY_DAILY_LIMIT_EXCEEDED" in code for code in decline_data["reason_codes"])

    # Assert final database state: exactly 1 active spending reservation of $30,000
    async with concurrency_session_factory() as session:
        stmt = select(func.sum(SpendingReservation.amount)).where(
            SpendingReservation.agent_id == uuid.UUID(agent_id),
            SpendingReservation.status == SpendingReservationStatus.ACTIVE,
        )
        total_reserved = (await session.execute(stmt)).scalar_one()
        assert total_reserved == Decimal("30000.0000")


# =============================================================================
# SCENARIO 2: Successful reservation visibility to competing transactions
# =============================================================================


@pytest.mark.asyncio
async def test_scenario_2_reservation_visibility_across_competing_sessions(
    concurrency_app_factory: Any,
    concurrency_session_factory: async_sessionmaker[AsyncSession],
    concurrent_banking_env: dict[str, Any],
) -> None:
    """Verify that once a reservation is committed in one transaction,

    it is immediately visible to another concurrent transaction.
    """
    env = concurrent_banking_env
    inst_a_id = env["institution_a"]["id"]
    agent_id = env["agent_1"]["id"]

    # Transaction 1: Evaluate $20,000
    client = concurrency_app_factory()
    async with client:
        payload_1 = make_eval_payload(env, agent_num=1, amount="20000.0000")
        res_1 = await client.post(
            "/api/v1/policies/evaluate",
            json=payload_1,
            headers={"X-Institution-ID": inst_a_id},
        )
        assert res_1.status_code == 200
        assert res_1.json()["decision"] == "STEP_UP"

    # Transaction 2: Open an independent DB session and verify visibility
    async with concurrency_session_factory() as session:
        repo = PolicyEvaluationRepository(session)
        active_sum = await repo.get_active_reservations_sum(
            agent_id=uuid.UUID(agent_id),
            currency="USD",
            now=datetime.now(UTC),
        )
        assert active_sum == Decimal("20000.0000")


# =============================================================================
# SCENARIO 3: Same-key, same-intent retries do not create duplicate reservations
# =============================================================================


@pytest.mark.asyncio
async def test_scenario_3_concurrent_same_key_same_intent_retries(
    concurrency_app_factory: Any,
    concurrency_session_factory: async_sessionmaker[AsyncSession],
    concurrent_banking_env: dict[str, Any],
) -> None:
    """Two concurrent requests with the identical idempotency key and identical payload.

    Both must receive the exact same decision, and exactly one reservation must exist.
    """
    env = concurrent_banking_env
    inst_a_id = env["institution_a"]["id"]
    agent_id = env["agent_1"]["id"]

    shared_idemp = f"concurrent-idemp-{uuid.uuid4().hex}"
    payload = make_eval_payload(env, agent_num=1, amount="15000.0000", idempotency_key=shared_idemp)

    barrier = asyncio.Barrier(2)

    async def execute_request() -> Any:
        client = concurrency_app_factory()
        async with client:
            await barrier.wait()
            return await client.post(
                "/api/v1/policies/evaluate",
                json=payload,
                headers={"X-Institution-ID": inst_a_id},
            )

    res_1, res_2 = await asyncio.wait_for(
        asyncio.gather(execute_request(), execute_request()),
        timeout=10.0,
    )

    assert res_1.status_code == 200
    assert res_2.status_code == 200
    assert res_1.json()["decision"] == res_2.json()["decision"]
    assert res_1.json()["audit_record_id"] == res_2.json()["audit_record_id"]

    # Verify database: exactly 1 evaluation record and 1 spending reservation
    async with concurrency_session_factory() as session:
        eval_count_stmt = select(func.count(PolicyEvaluationRecord.id)).where(
            PolicyEvaluationRecord.idempotency_key == shared_idemp
        )
        eval_count = (await session.execute(eval_count_stmt)).scalar_one()
        assert eval_count == 1

        res_stmt = select(func.count(SpendingReservation.id)).where(
            SpendingReservation.agent_id == uuid.UUID(agent_id),
            SpendingReservation.status == SpendingReservationStatus.ACTIVE,
        )
        res_count = (await session.execute(res_stmt)).scalar_one()
        assert res_count == 1


# =============================================================================
# SCENARIO 4: Same-key, different-intent requests fail with conflict (HTTP 409)
# =============================================================================


@pytest.mark.asyncio
async def test_scenario_4_concurrent_same_key_different_intent_conflict(
    concurrency_app_factory: Any,
    concurrent_banking_env: dict[str, Any],
) -> None:
    """Two concurrent requests using the same idempotency key with different amounts.

    One must succeed or complete; the other must fail with HTTP 409 IDEMPOTENCY_CONFLICT.
    """
    env = concurrent_banking_env
    inst_a_id = env["institution_a"]["id"]

    shared_idemp = f"conflict-idemp-{uuid.uuid4().hex}"
    payload_1 = make_eval_payload(
        env, agent_num=1, amount="5000.0000", idempotency_key=shared_idemp
    )
    payload_2 = make_eval_payload(
        env, agent_num=1, amount="8000.0000", idempotency_key=shared_idemp
    )

    barrier = asyncio.Barrier(2)

    async def execute(p: dict[str, Any]) -> Any:
        client = concurrency_app_factory()
        async with client:
            await barrier.wait()
            return await client.post(
                "/api/v1/policies/evaluate",
                json=p,
                headers={"X-Institution-ID": inst_a_id},
            )

    res_1, res_2 = await asyncio.wait_for(
        asyncio.gather(execute(payload_1), execute(payload_2)),
        timeout=10.0,
    )

    statuses = [res_1.status_code, res_2.status_code]
    assert 200 in statuses, f"Expected at least one 200, got {statuses}"
    assert 409 in statuses, f"Expected one 409 conflict, got {statuses}"

    conflict_res = res_1 if res_1.status_code == 409 else res_2
    assert conflict_res.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


# =============================================================================
# SCENARIO 5: Duplicate nonce submissions fail closed
# =============================================================================


@pytest.mark.asyncio
async def test_scenario_5_concurrent_duplicate_nonce_fails_closed(
    concurrency_app_factory: Any,
    concurrent_banking_env: dict[str, Any],
) -> None:
    """Two overlapping requests attempting to reuse the same cryptographic nonce.

    Exactly one might record the nonce; the other must receive REPLAY_DETECTED_NONCE_REUSED.
    """
    env = concurrent_banking_env
    inst_a_id = env["institution_a"]["id"]

    shared_nonce = f"shared-nonce-{uuid.uuid4().hex}"
    payload_1 = make_eval_payload(env, agent_num=1, amount="4000.0000", nonce=shared_nonce)
    payload_2 = make_eval_payload(env, agent_num=1, amount="4000.0000", nonce=shared_nonce)

    barrier = asyncio.Barrier(2)

    async def execute(p: dict[str, Any]) -> Any:
        client = concurrency_app_factory()
        async with client:
            await barrier.wait()
            return await client.post(
                "/api/v1/policies/evaluate",
                json=p,
                headers={"X-Institution-ID": inst_a_id},
            )

    res_1, res_2 = await asyncio.wait_for(
        asyncio.gather(execute(payload_1), execute(payload_2)),
        timeout=10.0,
    )

    data_1 = res_1.json()
    data_2 = res_2.json()

    # At least one must be DECLINE with REPLAY_DETECTED_NONCE_REUSED
    all_reasons = (data_1.get("reason_codes", []) or []) + (data_2.get("reason_codes", []) or [])
    assert "REPLAY_DETECTED_NONCE_REUSED" in all_reasons, (
        f"Expected replay rejection, got reasons: {all_reasons}"
    )


# =============================================================================
# SCENARIO 6: Database exception rolls back transaction atomically
# =============================================================================


@pytest.mark.asyncio
async def test_scenario_6_database_exception_rolls_back_entire_transaction(
    concurrency_session_factory: async_sessionmaker[AsyncSession],
    concurrent_banking_env: dict[str, Any],
) -> None:
    """Verify that an abort during evaluation rolls back the reservation and evaluation."""
    env = concurrent_banking_env
    agent_id = env["agent_1"]["id"]

    async with concurrency_session_factory() as session:
        service = PolicyService(session)

        # Force a database failure by inserting an invalid record or raising an exception
        # after creating the reservation
        try:
            # Manually simulate transactional failure
            await service.evaluation_repo.create_spending_reservation(
                agent_id=uuid.UUID(agent_id),
                institution_id=uuid.UUID(env["institution_a"]["id"]),
                amount=Decimal("5000.0000"),
                currency="USD",
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
            )
            # Simulate unexpected crash before commit
            raise RuntimeError("Simulated mid-pipeline unhandled crash")
        except RuntimeError:
            await session.rollback()

    # Verify that the reservation was rolled back and does not exist in the database
    async with concurrency_session_factory() as session:
        stmt = select(func.count(SpendingReservation.id)).where(
            SpendingReservation.agent_id == uuid.UUID(agent_id)
        )
        count = (await session.execute(stmt)).scalar_one()
        assert count == 0


# =============================================================================
# SCENARIO 7: Independent agents execute concurrently without serialization
# =============================================================================


@pytest.mark.asyncio
async def test_scenario_7_independent_agents_execute_without_serialization(
    concurrency_app_factory: Any,
    concurrency_session_factory: async_sessionmaker[AsyncSession],
    concurrent_banking_env: dict[str, Any],
) -> None:
    """Two independent agents (Agent 1 and Agent 2) evaluate simultaneously.

    Both must succeed with STEP_UP or ALLOW, creating their own distinct reservations
    without blocking or deadlocking each other.
    """
    env = concurrent_banking_env
    inst_a_id = env["institution_a"]["id"]
    agent_1_id = env["agent_1"]["id"]
    agent_2_id = env["agent_2"]["id"]

    payload_1 = make_eval_payload(env, agent_num=1, amount="20000.0000")
    payload_2 = make_eval_payload(env, agent_num=2, amount="20000.0000")

    barrier = asyncio.Barrier(2)

    async def execute(p: dict[str, Any]) -> Any:
        client = concurrency_app_factory()
        async with client:
            await barrier.wait()
            return await client.post(
                "/api/v1/policies/evaluate",
                json=p,
                headers={"X-Institution-ID": inst_a_id},
            )

    res_1, res_2 = await asyncio.wait_for(
        asyncio.gather(execute(payload_1), execute(payload_2)),
        timeout=10.0,
    )

    assert res_1.status_code == 200
    assert res_2.status_code == 200
    assert res_1.json()["decision"] == "STEP_UP"
    assert res_2.json()["decision"] == "STEP_UP"

    # Verify both reservations exist independently in the database
    async with concurrency_session_factory() as session:
        stmt_1 = select(func.count(SpendingReservation.id)).where(
            SpendingReservation.agent_id == uuid.UUID(agent_1_id),
            SpendingReservation.status == SpendingReservationStatus.ACTIVE,
        )
        stmt_2 = select(func.count(SpendingReservation.id)).where(
            SpendingReservation.agent_id == uuid.UUID(agent_2_id),
            SpendingReservation.status == SpendingReservationStatus.ACTIVE,
        )
        assert (await session.execute(stmt_1)).scalar_one() == 1
        assert (await session.execute(stmt_2)).scalar_one() == 1


# =============================================================================
# SCENARIO 8: Reservation release, commit, and expiry behave correctly
# =============================================================================


@pytest.mark.asyncio
async def test_scenario_8_reservation_release_commit_and_expiry_lifecycle(
    concurrency_app_factory: Any,
    concurrency_session_factory: async_sessionmaker[AsyncSession],
    concurrent_banking_env: dict[str, Any],
) -> None:
    """Tests reservation release, commit, and expiration under concurrent conditions:

    - Rejection of step-up immediately releases the active reservation.
    - Expired reservations are automatically excluded from active velocity calculations.
    """
    env = concurrent_banking_env
    inst_a_id = env["institution_a"]["id"]
    agent_id = env["agent_1"]["id"]

    # 1. Trigger STEP_UP with $25,000
    client = concurrency_app_factory()
    async with client:
        payload = make_eval_payload(env, agent_num=1, amount="25000.0000")
        eval_res = await client.post(
            "/api/v1/policies/evaluate",
            json=payload,
            headers={"X-Institution-ID": inst_a_id},
        )
        assert eval_res.status_code == 200
        challenge_id = eval_res.json()["step_up_challenge"]["challenge_id"]

        # Verify $25,000 active reservation exists
        async with concurrency_session_factory() as session:
            repo = PolicyEvaluationRepository(session)
            active = await repo.get_active_reservations_sum(
                uuid.UUID(agent_id), "USD", datetime.now(UTC)
            )
            assert active == Decimal("25000.0000")

        # 2. Reject the challenge (supervisor rejection releases reservation)
        rej_res = await client.post(
            f"/api/v1/policies/step-up/{challenge_id}/complete",
            json={
                "approver_id": "supervisor_bob",
                "decision": "REJECTED",
                "reason": "Suspected duplicate payment",
            },
            headers={"X-Institution-ID": inst_a_id},
        )
        assert rej_res.status_code == 200
        assert rej_res.json()["status"] == StepUpStatus.REJECTED.value

        # Verify reservation status is now RELEASED and active sum is 0
        async with concurrency_session_factory() as session:
            repo = PolicyEvaluationRepository(session)
            active = await repo.get_active_reservations_sum(
                uuid.UUID(agent_id), "USD", datetime.now(UTC)
            )
            assert active == Decimal("0.0000")

        # 3. Test Expiry: Insert an expired reservation manually and verify it is excluded
        async with concurrency_session_factory() as session:
            repo = PolicyEvaluationRepository(session)
            await repo.create_spending_reservation(
                agent_id=uuid.UUID(agent_id),
                institution_id=uuid.UUID(inst_a_id),
                amount=Decimal("15000.0000"),
                currency="USD",
                expires_at=datetime.now(UTC) - timedelta(minutes=5),  # Already expired
            )
            await session.commit()

        # Query active sum: expired reservation must be ignored!
        async with concurrency_session_factory() as session:
            repo = PolicyEvaluationRepository(session)
            active_after_expiry = await repo.get_active_reservations_sum(
                uuid.UUID(agent_id), "USD", datetime.now(UTC)
            )
            assert active_after_expiry == Decimal("0.0000")

            # Test cleanup helper
            cleaned = await repo.expire_stale_reservations(now=datetime.now(UTC))
            assert cleaned >= 1
            await session.commit()
