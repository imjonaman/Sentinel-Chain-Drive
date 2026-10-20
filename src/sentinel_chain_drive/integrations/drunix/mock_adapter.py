"""Mock implementation of the DRUNIX adapter for Phase 1 local development and testing.

Explicitly operates in-memory without attempting real network connections to unconfigured ledgers.
"""

import hashlib
import logging
import time
from typing import Any

from sentinel_chain_drive.integrations.drunix.adapter import DRUNIXAdapter

logger = logging.getLogger(__name__)


class MockDRUNIXAdapter(DRUNIXAdapter):
    """In-memory stub implementing DRUNIXAdapter for Phase 1 foundation."""

    def __init__(self, endpoint_url: str = "http://localhost:9000") -> None:
        self.endpoint_url = endpoint_url
        self._records: dict[str, dict[str, Any]] = {}

    async def is_available(self) -> bool:
        """Simulate connectivity check."""
        return True

    async def record_authorization_state(
        self,
        decision_id: str,
        agent_id: str,
        decision: str,
        payload_hash: str,
    ) -> str:
        """Store authorization state record in memory and return simulated transaction hash."""
        timestamp = time.time()
        record_content = f"{decision_id}:{agent_id}:{decision}:{payload_hash}:{timestamp}"
        tx_hash = f"0x{hashlib.sha256(record_content.encode('utf-8')).hexdigest()}"

        self._records[tx_hash] = {
            "tx_hash": tx_hash,
            "decision_id": decision_id,
            "agent_id": agent_id,
            "decision": decision,
            "payload_hash": payload_hash,
            "recorded_at": timestamp,
            "adapter": "mock",
        }
        logger.debug("Mock DRUNIX ledger recorded state: %s", tx_hash)
        return tx_hash

    async def retrieve_authorization_record(self, record_id: str) -> dict[str, Any] | None:
        """Retrieve stored simulated transaction record."""
        return self._records.get(record_id)
