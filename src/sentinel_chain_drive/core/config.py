"""Application configuration using Pydantic Settings.

Ensures strict validation, secure default boundaries, and prevention of credential leakage.
"""

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable resolution and validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Environment & Basic Metadata
    ENVIRONMENT: Literal["development", "testing", "staging", "production"] = Field(
        default="development",
        description="Runtime environment name",
    )
    DEBUG: bool = Field(
        default=False,
        description="Enable debug mode (should never be enabled in production)",
    )
    APP_NAME: str = Field(
        default="Sentinel Chain Drive",
        description="Public human-readable application name",
    )
    APP_VERSION: str = Field(
        default="0.1.0",
        description="Semantic application version",
    )
    HOST: str = Field(
        default="0.0.0.0",
        description="Host interface for server binding",
    )
    PORT: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Port for server binding",
    )

    # Security & Networking
    CORS_ORIGINS: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000"],
        description="Allowed CORS origins list. Must be explicit and conservative.",
    )
    MAX_REQUEST_SIZE_BYTES: int = Field(
        default=1_048_576,  # 1 MB
        ge=1024,
        le=52_428_800,  # 50 MB upper cap
        description="Maximum accepted request body size in bytes",
    )

    # Logging
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Application logging verbosity",
    )
    LOG_FORMAT: Literal["json", "text"] = Field(
        default="json",
        description="Structured log emission format",
    )

    # Database Configuration
    POSTGRES_HOST: str = Field(
        default="localhost",
        description="PostgreSQL server hostname",
    )
    POSTGRES_PORT: int = Field(
        default=5432,
        ge=1,
        le=65535,
        description="PostgreSQL server port",
    )
    POSTGRES_DB: str = Field(
        default="sentinel_chain_drive",
        description="PostgreSQL database name",
    )
    POSTGRES_USER: str = Field(
        default="sentinel_user",
        description="PostgreSQL username",
    )
    POSTGRES_PASSWORD: SecretStr = Field(
        default=SecretStr("replace_with_secure_local_dev_password"),
        description="PostgreSQL password (strictly masked)",
    )
    POSTGRES_POOL_SIZE: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Connection pool size",
    )
    POSTGRES_MAX_OVERFLOW: int = Field(
        default=20,
        ge=0,
        le=100,
        description="Connection pool max overflow",
    )
    POSTGRES_POOL_TIMEOUT_SECONDS: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Connection pool acquisition timeout in seconds",
    )
    DATABASE_URL: str | None = Field(
        default=None,
        description="Explicit async database connection URL overriding individual fields",
    )

    # Integrations: DRUNIX ledger interface settings
    DRUNIX_ADAPTER_TYPE: Literal["mock", "rpc"] = Field(
        default="mock",
        description="DRUNIX adapter type for permissioned ledger integration",
    )
    DRUNIX_ENDPOINT_URL: str = Field(
        default="http://localhost:9000",
        description="DRUNIX integration endpoint",
    )

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, v: list[str]) -> list[str]:
        """Validate CORS origins to prevent wildcard usage in restrictive environments."""
        for origin in v:
            if origin == "*":
                raise ValueError("Wildcard '*' CORS origin is forbidden for security.")
        return v

    @property
    def async_database_url(self) -> str:
        """Construct or return the async PostgreSQL database connection URL."""
        if self.DATABASE_URL:
            # Ensure asyncpg driver dialect is present if standard postgresql is passed
            if self.DATABASE_URL.startswith("postgresql://"):
                return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
            return self.DATABASE_URL

        password = self.POSTGRES_PASSWORD.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{password}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def sync_database_url(self) -> str:
        """Construct or return the sync PostgreSQL database connection URL for Alembic."""
        if self.DATABASE_URL:
            if self.DATABASE_URL.startswith("postgresql+asyncpg://"):
                return self.DATABASE_URL.replace(
                    "postgresql+asyncpg://", "postgresql+psycopg://", 1
                )
            if self.DATABASE_URL.startswith("postgresql://"):
                return self.DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
            return self.DATABASE_URL

        password = self.POSTGRES_PASSWORD.get_secret_value()
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{password}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    def get_safe_metadata(self) -> dict[str, Any]:
        """Return non-sensitive runtime metadata safe for exposure in diagnostics."""
        return {
            "app_name": self.APP_NAME,
            "version": self.APP_VERSION,
            "environment": self.ENVIRONMENT,
            "database_host": self.POSTGRES_HOST,
            "database_port": self.POSTGRES_PORT,
            "database_name": self.POSTGRES_DB,
            "drunix_adapter": self.DRUNIX_ADAPTER_TYPE,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
