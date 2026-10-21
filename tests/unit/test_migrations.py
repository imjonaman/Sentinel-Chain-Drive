"""Regression test suite for database migrations and schema lifecycle."""

from pathlib import Path

import sentinel_chain_drive.db.models  # noqa: F401
from scripts.verify_postgres_migrations import validate_migrations
from sentinel_chain_drive.db.base import Base


def test_metadata_tables_match_domain_models() -> None:
    """Verify that SQLAlchemy Base.metadata contains all 21 registered domain tables."""
    expected_tables = {
        "institutions",
        "accounts",
        "transactions",
        "transaction_status_history",
        "agents",
        "agent_credentials",
        "capabilities",
        "processed_nonces",
        "authorization_records",
        "audit_logs",
        "policies",
        "spending_reservations",
        "step_up_challenges",
        "transaction_holds",
        "policy_evaluations",
        "fraud_alerts",
        "shared_indicators",
        "privacy_audit_logs",
        "drunix_outbox_events",
        "drunix_ledger_submissions",
        "processed_events",
    }
    assert set(Base.metadata.tables.keys()) == expected_tables


def test_migration_lifecycle_upgrade_downgrade_reupgrade(tmp_path: Path) -> None:
    """Test full migration lifecycle against an isolated database:

    1. Base to head upgrade.
    2. Verification of all 21 tables, indexes, constraints, and foreign keys.
    3. Downgrade to Phase 3 (20261016_0003).
    4. Re-upgrade to head (20261021_0008).
    """
    db_file = tmp_path / "test_migration_lifecycle.db"
    sync_url = f"sqlite:///{db_file}"

    report = validate_migrations(sync_url)

    assert report["upgrade_head"] is True
    assert len(report["tables_verified"]) == 21
    assert "capabilities" in report["tables_verified"]
    assert "audit_logs" in report["tables_verified"]
    assert "drunix_outbox_events" in report["tables_verified"]
    assert "drunix_ledger_submissions" in report["tables_verified"]
    assert "processed_events" in report["tables_verified"]
    assert report["downgrade_verified"] is True
    assert report["re_upgrade_verified"] is True
