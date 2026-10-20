"""Abstract adapter specification for DRUNIX permissioned-ledger integration.

Isolates all future blockchain / distributed ledger operations behind a strict interface contract.
"""

from abc import ABC, abstractmethod
from typing import Any


class DRUNIXAdapter(ABC):
    """Abstract interface defining required interactions with the DRUNIX platform."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Check whether the DRUNIX gateway node is reachable and responsive."""
        pass

    @abstractmethod
    async def record_authorization_state(
        self,
        decision_id: str,
        agent_id: str,
        decision: str,
        payload_hash: str,
    ) -> str:
        """Submit a signed or hashed authorization decision record to the ledger.

        Returns:
            Deterministic transaction receipt or ledger commit hash.
        """
        pass

    @abstractmethod
    async def retrieve_authorization_record(self, record_id: str) -> dict[str, Any] | None:
        """Fetch a recorded authorization state by transaction or record identifier."""
        pass
