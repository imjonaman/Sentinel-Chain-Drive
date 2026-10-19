"""Unit tests for Phase 6 Privacy Gateway cryptographic core and MeshID generation."""

import hashlib

import pytest

from sentinel_chain_drive.core.privacy import (
    MeshKeyManager,
    compute_mesh_id,
)


def test_compute_mesh_id_deterministic() -> None:
    """Same input parameters produce identical MeshID."""
    mesh_1 = compute_mesh_id(
        institution_code="BANK_ALPHA",
        account_number="ACC-1000-XYZ",
        purpose="FRAUD_SHARING",
    )
    mesh_2 = compute_mesh_id(
        institution_code="BANK_ALPHA",
        account_number="ACC-1000-XYZ",
        purpose="FRAUD_SHARING",
    )
    assert mesh_1 == mesh_2
    assert len(mesh_1) == 64
    assert int(mesh_1, 16) > 0  # Valid hex digest


def test_purpose_isolation_prevents_cross_purpose_linkability() -> None:
    """Pseudonyms for the same account must differ across distinct purposes."""
    mesh_fraud = compute_mesh_id(
        institution_code="BANK_ALPHA",
        account_number="ACC-1000-XYZ",
        purpose="FRAUD_SHARING",
    )
    mesh_auth = compute_mesh_id(
        institution_code="BANK_ALPHA",
        account_number="ACC-1000-XYZ",
        purpose="PAYMENT_AUTHORIZATION",
    )
    mesh_inv = compute_mesh_id(
        institution_code="BANK_ALPHA",
        account_number="ACC-1000-XYZ",
        purpose="INVESTIGATION",
    )

    assert mesh_fraud != mesh_auth
    assert mesh_fraud != mesh_inv
    assert mesh_auth != mesh_inv


def test_institution_scoping() -> None:
    """Same account number at different institutions produces different pseudonyms."""
    mesh_bank_a = compute_mesh_id(
        institution_code="BANK_ALPHA",
        account_number="ACC-9999",
        purpose="FRAUD_SHARING",
    )
    mesh_bank_b = compute_mesh_id(
        institution_code="BANK_BETA",
        account_number="ACC-9999",
        purpose="FRAUD_SHARING",
    )
    assert mesh_bank_a != mesh_bank_b


def test_canonicalization_whitespace_and_casing() -> None:
    """Whitespace variations and casing differences are normalized before hashing."""
    mesh_normal = compute_mesh_id(
        institution_code="BANK_ALPHA",
        account_number="ACC-9999",
        purpose="FRAUD_SHARING",
    )
    mesh_padded = compute_mesh_id(
        institution_code="  bank_alpha  ",
        account_number="  acc-9999  ",
        purpose="  fraud_sharing  ",
    )
    assert mesh_normal == mesh_padded


def test_unkeyed_hash_is_distinct_and_forbidden() -> None:
    """MeshID must use keyed HMAC, not plain unsalted SHA-256."""
    raw_input = b"FRAUD_SHARING:BANK_ALPHA:ACC-9999"
    plain_sha256 = hashlib.sha256(raw_input).hexdigest()

    mesh_id = compute_mesh_id(
        institution_code="BANK_ALPHA",
        account_number="ACC-9999",
        purpose="FRAUD_SHARING",
    )
    # Keyed HMAC digest must never equal plain hash
    assert mesh_id != plain_sha256


def test_epoch_key_rotation() -> None:
    """Rotating the epoch secret key changes the resulting MeshID for same inputs."""
    km = MeshKeyManager()
    key_q4 = km.get_epoch_key("epoch_2026_q4")
    key_q3 = km.get_epoch_key("epoch_2026_q3")
    assert key_q4 != key_q3

    mesh_q4 = km.compute_mesh_id(
        institution_code="BANK_ALPHA",
        account_number="ACC-1234",
        epoch_id="epoch_2026_q4",
    )
    mesh_q3 = km.compute_mesh_id(
        institution_code="BANK_ALPHA",
        account_number="ACC-1234",
        epoch_id="epoch_2026_q3",
    )
    assert mesh_q4 != mesh_q3


def test_register_invalid_epoch_key() -> None:
    """Secret keys with insufficient entropy (< 32 bytes) are rejected."""
    km = MeshKeyManager()
    with pytest.raises(ValueError, match="at least 32 bytes of entropy"):
        km.register_epoch_key("epoch_weak", b"short-secret")


def test_invalid_purpose_rejected() -> None:
    """Unauthorized purpose codes are rejected."""
    with pytest.raises(ValueError, match="Invalid purpose"):
        compute_mesh_id(
            institution_code="BANK_ALPHA",
            account_number="ACC-1234",
            purpose="UNAUTHORIZED_MARKETING_LOOKUP",
        )


def test_empty_account_rejected() -> None:
    """Empty or whitespace account numbers are rejected."""
    with pytest.raises(ValueError, match="Account number must not be empty"):
        compute_mesh_id(
            institution_code="BANK_ALPHA",
            account_number="   ",
            purpose="FRAUD_SHARING",
        )


def test_unknown_epoch_raises_key_error_without_fallback() -> None:
    """Missing or unknown epochs must fail closed with KeyError, never generate fallback keys."""
    km = MeshKeyManager()
    with pytest.raises(KeyError, match="Unknown or expired epoch identifier"):
        km.get_epoch_key("epoch_unknown_9999")

    with pytest.raises(KeyError, match="Unknown or expired epoch identifier"):
        km.compute_mesh_id(
            institution_code="BANK_ALPHA",
            account_number="ACC-1234",
            epoch_id="epoch_unknown_9999",
        )


def test_cross_institution_matching_same_target_account() -> None:
    """Distinct institutions querying the same beneficiary account produce identical MeshID."""
    # When Bank A shares intel about an external account at Bank B (BANK_B, ACC-TARGET-1)
    mesh_from_bank_a = compute_mesh_id(
        institution_code="BANK_B",
        account_number="ACC-TARGET-1",
        purpose="FRAUD_SHARING",
    )
    # When Bank B (the home institution) or Bank C evaluates the same target account at Bank B
    mesh_from_bank_b = compute_mesh_id(
        institution_code="BANK_B",
        account_number="ACC-TARGET-1",
        purpose="FRAUD_SHARING",
    )
    # The MeshIDs MUST match because both refer to the target account at Bank B
    assert mesh_from_bank_a == mesh_from_bank_b

    # BUT if Bank A refers to its OWN internal account ACC-TARGET-1 at Bank A
    mesh_own_bank_a = compute_mesh_id(
        institution_code="BANK_A",
        account_number="ACC-TARGET-1",
        purpose="FRAUD_SHARING",
    )
    # They MUST NOT match, preventing collisions across distinct banks with identical local numbers
    assert mesh_own_bank_a != mesh_from_bank_a
