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
