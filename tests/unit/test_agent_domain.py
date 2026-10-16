"""Unit tests for agent domain models, transitions, and capability schemas."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from sentinel_chain_drive.db.models.agent import VALID_AGENT_TRANSITIONS, AgentStatus
from sentinel_chain_drive.schemas.agent import AgentCreate
from sentinel_chain_drive.schemas.capability import CapabilityCreate


def test_agent_lifecycle_transitions() -> None:
    """Verify strictly defined legal transitions for agents."""
    # PENDING_APPROVAL can transition to ACTIVE or REVOKED
    assert AgentStatus.ACTIVE in VALID_AGENT_TRANSITIONS[AgentStatus.PENDING_APPROVAL]
    assert AgentStatus.REVOKED in VALID_AGENT_TRANSITIONS[AgentStatus.PENDING_APPROVAL]
    assert AgentStatus.SUSPENDED not in VALID_AGENT_TRANSITIONS[AgentStatus.PENDING_APPROVAL]

    # ACTIVE can transition to SUSPENDED, REVOKED, EXPIRED
    assert AgentStatus.SUSPENDED in VALID_AGENT_TRANSITIONS[AgentStatus.ACTIVE]
    assert AgentStatus.REVOKED in VALID_AGENT_TRANSITIONS[AgentStatus.ACTIVE]
    assert AgentStatus.EXPIRED in VALID_AGENT_TRANSITIONS[AgentStatus.ACTIVE]

    # SUSPENDED can transition to ACTIVE, REVOKED, EXPIRED
    assert AgentStatus.ACTIVE in VALID_AGENT_TRANSITIONS[AgentStatus.SUSPENDED]
    assert AgentStatus.REVOKED in VALID_AGENT_TRANSITIONS[AgentStatus.SUSPENDED]

    # REVOKED is terminal - no transitions allowed
    assert len(VALID_AGENT_TRANSITIONS[AgentStatus.REVOKED]) == 0


def test_agent_create_rejects_invalid_public_key() -> None:
    """Verify AgentCreate validator rejects non-Ed25519 public key."""
    with pytest.raises(ValidationError, match="Invalid Ed25519 public verification key"):
        AgentCreate(
            institution_id=uuid.uuid4(),
            name="Test Agent",
            owner_contact="agent-admin@bank.com",
            public_key="NOT_A_VALID_KEY",
        )


def test_capability_create_validates_amounts_and_windows() -> None:
    """Verify capability constraints enforce daily limit >= single limit."""
    now = datetime.now(UTC)
    agent_id = uuid.uuid4()

    # Daily limit < single limit must raise ValidationError
    with pytest.raises(ValidationError, match="max_daily_cumulative_amount"):
        CapabilityCreate(
            agent_id=agent_id,
            name="Daily Limit Too Low",
            permitted_transaction_types=["DOMESTIC_TRANSFER"],
            permitted_currencies=["USD"],
            max_amount_per_transaction=Decimal("5000.00"),
            max_daily_cumulative_amount=Decimal("1000.00"),
            valid_until=now + timedelta(days=30),
            created_by="admin",
        )

    # Incomplete operating window (start without end) must raise ValidationError
    with pytest.raises(ValidationError, match="operating_start_hour_utc"):
        CapabilityCreate(
            agent_id=agent_id,
            name="Incomplete Hours",
            permitted_transaction_types=["DOMESTIC_TRANSFER"],
            permitted_currencies=["USD"],
            max_amount_per_transaction=Decimal("1000.00"),
            max_daily_cumulative_amount=Decimal("5000.00"),
            operating_start_hour_utc=9,
            operating_end_hour_utc=None,
            valid_until=now + timedelta(days=30),
            created_by="admin",
        )


def test_capability_update_validates_amounts_and_windows() -> None:
    """Verify CapabilityUpdate validator enforces daily limit >= single limit when both provided."""
    from sentinel_chain_drive.schemas.capability import CapabilityUpdate

    with pytest.raises(ValidationError, match="max_daily_cumulative_amount"):
        CapabilityUpdate(
            max_amount_per_transaction=Decimal("5000.00"),
            max_daily_cumulative_amount=Decimal("2000.00"),
        )

    with pytest.raises(ValidationError, match="operating_start_hour_utc"):
        CapabilityUpdate(
            operating_start_hour_utc=10,
            operating_end_hour_utc=None,
        )
