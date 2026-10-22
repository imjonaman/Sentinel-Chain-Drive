"""Validation script for PostgreSQL migrations and schema constraints.

Can be run locally or in CI against an isolated PostgreSQL database.
If PostgreSQL is unreachable, marks runtime execution UNVERIFIED and exits with code 0
or informative diagnostic output without crashing.
"""

import os
import sys
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, pool, text


def get_test_database_urls() -> tuple[str, str]:
    """Resolve sync and async PostgreSQL test connection URLs from environment."""
    test_url = os.environ.get("TEST_POSTGRES_URL")
    if test_url:
        sync_url = test_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
        async_url = test_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
        return sync_url, async_url

    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "sentinel_test")
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "postgres")

    sync_url = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"
    async_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"
    return sync_url, async_url


def check_postgres_availability(sync_url: str) -> tuple[bool, str | None]:
    """Probe PostgreSQL server connectivity and return server version string."""
    try:
        engine = create_engine(sync_url, connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();")).scalar()
            return True, str(result)
    except Exception as exc:
        return False, str(exc)


def validate_migrations(sync_url: str) -> dict[str, Any]:
    """Execute live migration validation suite against PostgreSQL:

    1. Applies all migrations to head.
    2. Validates schema objects, columns, FKs, indexes, and unique constraints.
    3. Tests downgrade to Phase 3.
    4. Tests re-upgrade to Phase 4 (head).
    """
    os.environ["ALEMBIC_DATABASE_URL"] = sync_url
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)

    engine = create_engine(sync_url, poolclass=pool.NullPool)

    report: dict[str, Any] = {
        "upgrade_head": False,
        "tables_verified": [],
        "constraints_verified": [],
        "downgrade_verified": False,
        "re_upgrade_verified": False,
    }

    # 1. Upgrade to head
    print("[MIGRATION_CHECK] Running 'alembic upgrade head'...")
    command.upgrade(alembic_cfg, "head")
    report["upgrade_head"] = True

    # 2. Inspect Schema
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

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
        "cases",
        "case_transactions",
        "case_alerts",
        "case_accounts",
        "case_evidence",
        "case_status_history",
        "recovery_requests",
        "recovery_status_history",
    }
    missing_tables = expected_tables - table_names
    if missing_tables:
        raise RuntimeError(f"Missing expected tables after migration: {missing_tables}")
    report["tables_verified"] = list(expected_tables)
    print(f"[MIGRATION_CHECK] Verified all {len(expected_tables)} expected tables exist.")

    # Check unique constraints on cases
    case_uq_constraints = inspector.get_unique_constraints("cases")
    case_uq_names = [uq["name"] for uq in case_uq_constraints]
    assert "uq_cases_case_number" in case_uq_names, (
        f"Missing uq_cases_case_number in {case_uq_names}"
    )
    report["constraints_verified"].append("uq_cases_case_number")
    assert "uq_cases_institution_source" in case_uq_names, (
        f"Missing uq_cases_institution_source in {case_uq_names}"
    )
    report["constraints_verified"].append("uq_cases_institution_source")

    # Check unique constraints on recovery_requests
    recovery_uq_constraints = inspector.get_unique_constraints("recovery_requests")
    recovery_uq_names = [uq["name"] for uq in recovery_uq_constraints]
    assert "uq_recovery_requests_number" in recovery_uq_names, (
        f"Missing uq_recovery_requests_number in {recovery_uq_names}"
    )
    report["constraints_verified"].append("uq_recovery_requests_number")
    assert "uq_recovery_requests_institution_idempotency" in recovery_uq_names, (
        f"Missing uq_recovery_requests_institution_idempotency in {recovery_uq_names}"
    )
    report["constraints_verified"].append("uq_recovery_requests_institution_idempotency")


    # Check unique constraint on policy_evaluations
    unique_constraints = inspector.get_unique_constraints("policy_evaluations")
    uq_names = [uq["name"] for uq in unique_constraints]
    assert "uq_policy_evaluations_institution_idempotency" in uq_names, (
        f"Missing uq_policy_evaluations_institution_idempotency in {uq_names}"
    )
    report["constraints_verified"].append("uq_policy_evaluations_institution_idempotency")

    # Check unique constraint on shared_indicators
    shared_uq_constraints = inspector.get_unique_constraints("shared_indicators")
    shared_uq_names = [uq["name"] for uq in shared_uq_constraints]
    assert "uq_shared_indicators_origin_mesh_type_policy" in shared_uq_names, (
        f"Missing uq_shared_indicators_origin_mesh_type_policy in {shared_uq_names}"
    )
    report["constraints_verified"].append("uq_shared_indicators_origin_mesh_type_policy")

    # Check unique constraint on drunix_outbox_events
    outbox_uq_constraints = inspector.get_unique_constraints("drunix_outbox_events")
    outbox_uq_names = [uq["name"] for uq in outbox_uq_constraints]
    assert "uq_drunix_outbox_institution_idempotency" in outbox_uq_names, (
        f"Missing uq_drunix_outbox_institution_idempotency in {outbox_uq_names}"
    )
    report["constraints_verified"].append("uq_drunix_outbox_institution_idempotency")
    assert "uq_drunix_outbox_ordering_seq" in outbox_uq_names, (
        f"Missing uq_drunix_outbox_ordering_seq in {outbox_uq_names}"
    )
    report["constraints_verified"].append("uq_drunix_outbox_ordering_seq")

    # Check unique constraint on processed_events
    proc_uq_constraints = inspector.get_unique_constraints("processed_events")
    proc_uq_names = [uq["name"] for uq in proc_uq_constraints]
    assert "uq_processed_events_consumer_event" in proc_uq_names, (
        f"Missing uq_processed_events_consumer_event in {proc_uq_names}"
    )
    report["constraints_verified"].append("uq_processed_events_consumer_event")

    # Check indexes on drunix_outbox_events
    outbox_indexes = inspector.get_indexes("drunix_outbox_events")
    outbox_index_names = [idx["name"] for idx in outbox_indexes]
    for required_idx in [
        "ix_drunix_outbox_events_status",
        "ix_drunix_outbox_events_next_attempt_at",
        "ix_drunix_outbox_events_institution_id",
        "ix_drunix_outbox_events_idempotency_key",
        "ix_drunix_outbox_events_ordering_seq",
    ]:
        assert required_idx in outbox_index_names, (
            f"Missing index on drunix_outbox_events: {required_idx} (found: {outbox_index_names})"
        )
        report["constraints_verified"].append(required_idx)

    # Check indexes on spending_reservations
    indexes = inspector.get_indexes("spending_reservations")
    index_names = [idx["name"] for idx in indexes]
    for required_idx in [
        "ix_spending_reservations_agent_id",
        "ix_spending_reservations_status",
        "ix_spending_reservations_expires_at",
    ]:
        assert required_idx in index_names, f"Missing index: {required_idx}"
        report["constraints_verified"].append(required_idx)

    # Check indexes on audit_logs
    audit_indexes = inspector.get_indexes("audit_logs")
    audit_index_names = [idx["name"] for idx in audit_indexes]
    for required_idx in [
        "ix_audit_logs_event_type",
        "ix_audit_logs_severity",
        "ix_audit_logs_correlation_id",
        "ix_audit_logs_created_at_desc",
    ]:
        assert required_idx in audit_index_names, f"Missing index on audit_logs: {required_idx}"
        report["constraints_verified"].append(required_idx)

    # Check indexes and foreign keys on capabilities
    cap_indexes = inspector.get_indexes("capabilities")
    cap_index_names = [idx["name"] for idx in cap_indexes]
    for required_idx in [
        "ix_capabilities_agent_id",
        "ix_capabilities_institution_id",
        "ix_capabilities_is_active",
    ]:
        assert required_idx in cap_index_names, f"Missing index on capabilities: {required_idx}"
        report["constraints_verified"].append(required_idx)

    cap_fks = inspector.get_foreign_keys("capabilities")
    cap_fk_targets = {fk["referred_table"] for fk in cap_fks}
    assert "agents" in cap_fk_targets, "Missing foreign key to agents on capabilities"
    assert "institutions" in cap_fk_targets, "Missing foreign key to institutions on capabilities"
    report["constraints_verified"].append("fk_capabilities_agents")
    report["constraints_verified"].append("fk_capabilities_institutions")

    print("[MIGRATION_CHECK] Verified unique constraints, foreign keys, and performance indexes.")

    # 3. Test Downgrade to 20261016_0003
    engine.dispose()
    print("[MIGRATION_CHECK] Testing downgrade to 20261016_0003...")
    command.downgrade(alembic_cfg, "20261016_0003")
    inspector = inspect(engine)
    remaining_tables = set(inspector.get_table_names())
    phase4_8_tables = {
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
    dropped_failures = phase4_8_tables & remaining_tables
    assert not dropped_failures, (
        f"Phase 4-8 tables were not dropped on downgrade: {dropped_failures}"
    )

    report["downgrade_verified"] = True
    print("[MIGRATION_CHECK] Downgrade verified: Phase 4-8 tables dropped cleanly.")

    # 4. Re-upgrade to head
    engine.dispose()
    print("[MIGRATION_CHECK] Testing re-upgrade to head (20261021_0008)...")
    command.upgrade(alembic_cfg, "head")
    inspector = inspect(engine)
    restored_tables = set(inspector.get_table_names())
    assert expected_tables.issubset(restored_tables), (
        f"Tables missing after re-upgrade: {expected_tables - restored_tables}"
    )
    report["re_upgrade_verified"] = True
    print("[MIGRATION_CHECK] Re-upgrade verified successfully.")

    engine.dispose()
    return report


def main() -> None:
    sync_url, _ = get_test_database_urls()
    print("=" * 70)
    print("SENTINEL CHAIN DRIVE: POSTGRESQL MIGRATION VALIDATOR")
    print("=" * 70)

    is_available, info_or_err = check_postgres_availability(sync_url)

    if not is_available:
        print("[POSTGRES_STATUS] NOT VERIFIED (PostgreSQL test instance is unreachable)")
        print(f"[REASON] {info_or_err}")
        print("[NOTICE] Alembic upgrade/downgrade/re-upgrade was NOT executed on PostgreSQL.")
        print("\nTo validate against a live PostgreSQL test instance:")
        print("  1. Ensure an isolated test database is running (e.g. in GitHub Actions CI).")
        print(
            "  2. Set TEST_POSTGRES_URL=postgresql+asyncpg://<user>:<password>@<host>:<port>/<db>"
        )
        print("  3. Re-run: python scripts/verify_postgres_migrations.py")
        print("=" * 70)
        # In strict or CI environments where TEST_POSTGRES_URL was explicitly provided or required
        if os.environ.get("REQUIRE_POSTGRES") == "1" or "--require-postgres" in sys.argv:
            print("[FATAL] PostgreSQL is required by configuration, but connection failed.")
            sys.exit(1)
        sys.exit(0)

    print(f"[POSTGRES_STATUS] CONNECTED: {info_or_err}")
    try:
        report = validate_migrations(sync_url)
        print("\n[RESULT] ALL MIGRATION AND SCHEMA CHECKS PASSED.")
        print(f"Tables verified: {len(report['tables_verified'])}")
        print(f"Constraints verified: {report['constraints_verified']}")
        print("Upgrade -> Downgrade -> Re-upgrade lifecycle: VERIFIED.")
    except Exception as err:
        import traceback

        print(f"\n[MIGRATION_ERROR] Migration validation failed: {err}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
