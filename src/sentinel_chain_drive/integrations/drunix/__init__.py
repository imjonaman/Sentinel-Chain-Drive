"""DRUNIX permissioned-ledger integration package."""

from functools import lru_cache

from sentinel_chain_drive.core.config import get_settings
from sentinel_chain_drive.integrations.drunix.adapter import DRUNIXAdapter, DRUNIXReceipt
from sentinel_chain_drive.integrations.drunix.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerSnapshot,
    CircuitBreakerState,
)
from sentinel_chain_drive.integrations.drunix.exceptions import (
    DRUNIXAdapterError,
    DRUNIXMalformedResponseError,
    DRUNIXTerminalError,
    DRUNIXTimeoutError,
    DRUNIXTransientError,
    DRUNIXUncertainOutcomeError,
)
from sentinel_chain_drive.integrations.drunix.mock_adapter import (
    MockDRUNIXAdapter,
    MockSimulationMode,
)


@lru_cache(maxsize=1)
def get_drunix_adapter() -> DRUNIXAdapter:
    """Factory creating the configured DRUNIXAdapter instance."""
    settings = get_settings()
    if settings.DRUNIX_ADAPTER_TYPE == "mock":
        return MockDRUNIXAdapter(endpoint_url=settings.DRUNIX_ENDPOINT_URL)

    # For Phase 1-7, only mock simulator is supported to prevent premature unverified
    # network dependencies
    return MockDRUNIXAdapter(endpoint_url=settings.DRUNIX_ENDPOINT_URL)


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerSnapshot",
    "CircuitBreakerState",
    "DRUNIXAdapter",
    "DRUNIXAdapterError",
    "DRUNIXMalformedResponseError",
    "DRUNIXReceipt",
    "DRUNIXTerminalError",
    "DRUNIXTimeoutError",
    "DRUNIXTransientError",
    "DRUNIXUncertainOutcomeError",
    "MockDRUNIXAdapter",
    "MockSimulationMode",
    "get_drunix_adapter",
]
