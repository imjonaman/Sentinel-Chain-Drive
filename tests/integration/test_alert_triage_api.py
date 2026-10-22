"""Integration tests for Phase 9 Alert Triage and Automated Case Opening API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sentinel_chain_drive.db.models.account import Account, AccountType
from sentinel_chain_drive.db.models.alert import (
    AlertSeverity,
    DetectorType,
    FraudAlert,
)
from sentinel_chain_drive.db.models.institution import Institution, InstitutionStatus


async def _seed_alert_fixtures(
    sqlite_engine: AsyncEngine,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed test institution, account, and fraud alert."""
    session_factory = async_sessionmaker(
        bind=sqlite_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        inst = Institution(
            name="Bank Triage Alpha",
            institution_code=f"TA-{uuid.uuid4().hex[:6].upper()}",
            routing_identifier=f"021{uuid.uuid4().hex[:6]}",
            status=InstitutionStatus.ACTIVE,
        )
        session.add(inst)
        await session.flush()

        acct = Account(
            institution_id=inst.id,
            account_number=f"ACCT-{uuid.uuid4().hex[:8]}",
            account_type=AccountType.CHECKING,
            currency="USD",
        )
        session.add(acct)
        await session.flush()

        now = datetime.now(UTC)
        alert = FraudAlert(
            primary_institution_id=inst.id,
            alert_code=f"MC-ALT-{uuid.uuid4().hex[:8].upper()}",
            detector_type=DetectorType.FAN_IN,
            severity=AlertSeverity.HIGH,
            risk_score=78,
            primary_account_id=acct.id,
            currency="USD",
            dedup_fingerprint=f"fp-{uuid.uuid4().hex}",
            detection_rule_version="1.0.0",
            analysis_window_start=now - timedelta(hours=24),
            analysis_window_end=now,
            evidence_data={"inbound_velocity": 12, "distinct_senders": 10},
        )
        session.add(alert)
        await session.commit()

        return inst.id, acct.id, alert.id


@pytest.mark.asyncio
async def test_alert_triage_and_automated_case_generation(
    client_with_db: AsyncClient,
    sqlite_engine: AsyncEngine,
) -> None:
    """Verify listing alerts, triaging an alert, and automatically generating a case."""
    inst_id, _, alert_id = await _seed_alert_fixtures(sqlite_engine)
    headers = {
        "X-Institution-ID": str(inst_id),
        "X-Actor-ID": "triage_analyst_1",
    }

    # 1. List alerts for triage
    list_resp = await client_with_db.get(
        "/api/v1/alerts?min_risk_score=50",
        headers=headers,
    )
    assert list_resp.status_code == 200
    alerts_data = list_resp.json()
    assert alerts_data["total"] >= 1
    assert any(a["id"] == str(alert_id) for a in alerts_data["items"])

    # 2. Triage alert with automated case creation
    triage_resp = await client_with_db.patch(
        f"/api/v1/alerts/{alert_id}/triage",
        headers=headers,
        json={
            "escalate_severity": "CRITICAL",
            "escalation_reason": "Escalating severity due to corroborating velocity pattern.",
            "notes": "Opened investigation case for urgent AML review.",
            "create_case": True,
        },
    )
    assert triage_resp.status_code == 200
    triage_data = triage_resp.json()
    assert triage_data["alert"]["severity"] == "CRITICAL"
    assert triage_data["case_id"] is not None

    # 3. Verify case was created and linked to the alert
    case_id = triage_data["case_id"]
    case_resp = await client_with_db.get(f"/api/v1/cases/{case_id}", headers=headers)
    assert case_resp.status_code == 200
    case_json = case_resp.json()
    assert case_json["priority"] == "CRITICAL"
    assert case_json["source_type"] == "FRAUD_ALERT"
    assert case_json["source_id"] == str(alert_id)
