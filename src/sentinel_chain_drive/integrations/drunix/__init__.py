"""DRUNIX permissioned-ledger integration package."""

from functools import lru_cache

from sentinel_chain_drive.core.config import get_settings
from sentinel_chain_drive.integrations.drunix.adapter import DRUNIXAdapter
from sentinel_chain_drive.integrations.drunix.mock_adapter import MockDRUNIXAdapter


@lru_cache(maxsize=1)
def get_drunix_adapter() -> DRUNIXAdapter:
    """Factory creating the configured DRUNIXAdapter instance."""
    settings = get_settings()
    if settings.DRUNIX_ADAPTER_TYPE == "mock":
        return MockDRUNIXAdapter(endpoint_url=settings.DRUNIX_ENDPOINT_URL)

    # For Phase 1, only mock adapter is supported to prevent premature network dependencies
    return MockDRUNIXAdapter(endpoint_url=settings.DRUNIX_ENDPOINT_URL)


__all__ = ["DRUNIXAdapter", "MockDRUNIXAdapter", "get_drunix_adapter"]
