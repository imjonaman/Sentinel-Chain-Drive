"""Cryptographic primitives and HMAC-SHA256 pseudonymization for MeshID."""

import hashlib
import hmac
from typing import Final

DEFAULT_EPOCH_ID: Final[str] = "epoch_2026_q4"

# Safe development default secret key (32 bytes entropy).
# Production deployment requires institutional KMS or secure environment injection.
_DEVELOPMENT_EPOCH_SECRETS: dict[str, bytes] = {
    "epoch_2026_q4": b"sentinel-chain-drive-meshid-secret-key-epoch-2026-q4-development-32b",
    "epoch_2026_q3": b"sentinel-chain-drive-meshid-secret-key-epoch-2026-q3-development-32b",
}

VALID_PURPOSES: Final[set[str]] = {
    "PAYMENT_AUTHORIZATION",
    "FRAUD_SHARING",
    "INVESTIGATION",
}


class MeshKeyManager:
    """Manages epoch-keyed HMAC secrets and deterministic pseudonym generation.

    Privacy & Security Properties:
    1. Keyed HMAC-SHA256: Unkeyed hashes (e.g., plain SHA-256) are strictly forbidden
       to prevent rainbow-table and dictionary attacks against structured bank account numbers.
    2. Purpose Isolation: Binds purpose code into the HMAC message so pseudonyms
       cannot be cross-correlated across unrelated operational boundaries.
    3. Normalization: Normalizes whitespace and casing before hashing.
    4. One-Way Resistance: Computationally infeasible to derive raw account numbers
       from MeshID without the epoch secret key.
    """

    def __init__(self, key_store: dict[str, bytes] | None = None) -> None:
        self._key_store = dict(key_store or _DEVELOPMENT_EPOCH_SECRETS)

    def register_epoch_key(self, epoch_id: str, secret_key: bytes) -> None:
        """Register or rotate an epoch secret key."""
        if len(secret_key) < 32:
            raise ValueError("Epoch secret key must provide at least 32 bytes of entropy.")
        self._key_store[epoch_id] = secret_key

    def get_epoch_key(self, epoch_id: str) -> bytes:
        """Retrieve the secret key for a given epoch."""
        if epoch_id not in self._key_store:
            raise KeyError(f"Unknown or expired epoch identifier: '{epoch_id}'")
        return self._key_store[epoch_id]

    def compute_mesh_id(
        self,
        institution_code: str,
        account_number: str,
        purpose: str = "FRAUD_SHARING",
        epoch_id: str = DEFAULT_EPOCH_ID,
    ) -> str:
        """Compute a deterministic, purpose-bound HMAC-SHA256 pseudonym (MeshID).

        Args:
            institution_code: Standard financial institution identifier (e.g., SWIFT BIC).
            account_number: Synthetic bank account number.
            purpose: Scoped operational context (e.g. PAYMENT_AUTHORIZATION, FRAUD_SHARING).
            epoch_id: Versioned key rotation epoch.

        Returns:
            64-character lowercase hex digest representing the pseudonymous MeshID.
        """
        inst_clean = institution_code.strip().upper()
        acct_clean = account_number.strip().upper()
        purpose_clean = purpose.strip().upper()

        if not inst_clean:
            raise ValueError("Institution code must not be empty.")
        if not acct_clean:
            raise ValueError("Account number must not be empty.")
        if purpose_clean not in VALID_PURPOSES:
            raise ValueError(
                f"Invalid purpose '{purpose}'. Must be one of: {sorted(VALID_PURPOSES)}"
            )

        secret_key = self.get_epoch_key(epoch_id)

        # Canonical message representation: PURPOSE:INSTITUTION:ACCOUNT
        canonical_msg = f"{purpose_clean}:{inst_clean}:{acct_clean}".encode()

        mesh_digest = hmac.new(
            key=secret_key,
            msg=canonical_msg,
            digestmod=hashlib.sha256,
        ).hexdigest()

        return mesh_digest


# Module-level default singleton instance
default_mesh_key_manager = MeshKeyManager()


def compute_mesh_id(
    institution_code: str,
    account_number: str,
    purpose: str = "FRAUD_SHARING",
    epoch_id: str = DEFAULT_EPOCH_ID,
) -> str:
    """Convenience helper to compute a MeshID using the default key manager."""
    return default_mesh_key_manager.compute_mesh_id(
        institution_code=institution_code,
        account_number=account_number,
        purpose=purpose,
        epoch_id=epoch_id,
    )
