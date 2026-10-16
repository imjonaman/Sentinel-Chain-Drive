"""Unit tests for application configuration validation and security boundaries."""

import pytest
from pydantic import ValidationError

from sentinel_chain_drive.core.config import Settings


def test_settings_defaults(test_settings: Settings) -> None:
    """Verify that default settings instantiate with expected values."""
    assert test_settings.APP_NAME == "Sentinel Chain Drive Test"
    assert test_settings.ENVIRONMENT == "testing"
    assert test_settings.PORT == 5432 or test_settings.PORT == 8000


def test_password_secret_masking(test_settings: Settings) -> None:
    """Verify that sensitive database password is not leaked in string or dict dumps."""
    secret_val = test_settings.POSTGRES_PASSWORD.get_secret_value()
    assert secret_val == "test_only_mock_password"

    # Representation must mask the secret
    str_repr = repr(test_settings)
    assert secret_val not in str_repr
    assert "**********" in str_repr or "SecretStr" in str_repr

    dumped = test_settings.model_dump()
    assert dumped["POSTGRES_PASSWORD"] != secret_val


def test_cors_origins_disallows_wildcard() -> None:
    """Verify that wildcard CORS is rejected for security."""
    with pytest.raises(ValidationError):
        Settings(CORS_ORIGINS=["*"])


def test_safe_metadata_never_contains_credentials(test_settings: Settings) -> None:
    """Ensure safe metadata exports exclude sensitive authentication attributes."""
    metadata = test_settings.get_safe_metadata()
    assert "password" not in metadata
    assert "POSTGRES_PASSWORD" not in metadata
    assert metadata["app_name"] == test_settings.APP_NAME
    assert metadata["environment"] == "testing"


def test_invalid_port_validation() -> None:
    """Verify port validation bounds."""
    with pytest.raises(ValidationError):
        Settings(PORT=70000)
    with pytest.raises(ValidationError):
        Settings(PORT=0)


def test_database_url_derivations() -> None:
    """Verify sync and async URL transformations for PostgreSQL, SQLite, and custom URLs."""
    # Default auto-assembly when DATABASE_URL is None
    s_default = Settings(
        POSTGRES_USER="test_u", POSTGRES_HOST="10.0.0.1", POSTGRES_DB="db1", DATABASE_URL=None
    )
    assert "postgresql+asyncpg://test_u:" in s_default.async_database_url
    assert "postgresql+psycopg://test_u:" in s_default.sync_database_url

    # Overridden with explicit DATABASE_URL
    s_custom = Settings(
        DATABASE_URL="postgresql://user:pass@db.example.supabase.co:5432/postgres?sslmode=require"
    )
    assert s_custom.async_database_url.startswith("postgresql+asyncpg://")
    assert s_custom.sync_database_url.startswith("postgresql+psycopg://")
    assert "ssl=require" in s_custom.async_database_url
    assert "sslmode=require" in s_custom.sync_database_url

    # Check postgres:// alias prefix normalization
    s_alias = Settings(DATABASE_URL="postgres://user:pass@db.example.supabase.co:5432/postgres")
    assert s_alias.async_database_url.startswith("postgresql+asyncpg://")
    assert s_alias.sync_database_url.startswith("postgresql+psycopg://")

    # Safe metadata exports parsed host without leaking credentials
    meta = s_custom.get_safe_metadata()
    assert meta["database_host"] == "db.example.supabase.co"
    assert "pass" not in repr(meta)

    # Overridden with SQLite
    s_sqlite = Settings(DATABASE_URL="sqlite+aiosqlite:///./test.db")
    assert s_sqlite.async_database_url == "sqlite+aiosqlite:///./test.db"
    assert s_sqlite.sync_database_url == "sqlite:///./test.db"


def test_supabase_and_pooler_settings() -> None:
    """Verify settings specific to Supabase transaction poolers and dedicated migration URLs."""
    s_pooler = Settings(
        DATABASE_URL="postgresql://user.proj:pass@aws-0.pooler.supabase.com:6543/postgres",
        ALEMBIC_DATABASE_URL="postgresql://user:pass@db.proj.supabase.co:5432/postgres",
        POSTGRES_STATEMENT_CACHE_SIZE=0,
        POSTGRES_USE_NULL_POOL=True,
    )
    assert s_pooler.POSTGRES_STATEMENT_CACHE_SIZE == 0
    assert s_pooler.POSTGRES_USE_NULL_POOL is True
    # Alembic URLs should use direct session URL
    assert s_pooler.sync_database_url.startswith("postgresql+psycopg://")
    assert ":5432" in s_pooler.sync_database_url
    assert s_pooler.alembic_async_url.startswith("postgresql+asyncpg://")
    assert ":5432" in s_pooler.alembic_async_url
    # Main app URL uses pooler
    assert ":6543" in s_pooler.async_database_url
