"""Unit tests for cryptographic primitives and canonicalization."""

import pytest

from sentinel_chain_drive.core.crypto import (
    canonicalize_payload,
    compute_sha256_hash,
    compute_transaction_intent_hash,
    generate_ed25519_keypair,
    load_ed25519_private_key,
    load_ed25519_public_key,
    sign_payload,
    verify_signature,
)


def test_ed25519_keypair_generation_and_loading() -> None:
    """Verify generated Ed25519 keypairs are valid PEM format and loadable."""
    private_pem, public_pem = generate_ed25519_keypair()
    assert "BEGIN PRIVATE KEY" in private_pem
    assert "BEGIN PUBLIC KEY" in public_pem

    priv_key = load_ed25519_private_key(private_pem)
    pub_key = load_ed25519_public_key(public_pem)
    assert priv_key is not None
    assert pub_key is not None


def test_canonicalize_payload_deterministic() -> None:
    """Ensure canonicalization produces sorted keys without whitespace variance."""
    payload_1 = {"b": 2, "a": 1, "nested": {"y": "val", "x": 10}}
    payload_2 = {"a": 1, "nested": {"x": 10, "y": "val"}, "b": 2}

    canon_1 = canonicalize_payload(payload_1)
    canon_2 = canonicalize_payload(payload_2)

    assert canon_1 == canon_2
    assert b" " not in canon_1
    assert canon_1 == b'{"a":1,"b":2,"nested":{"x":10,"y":"val"}}'


def test_sha256_and_transaction_intent_hash() -> None:
    """Verify SHA-256 hash generation and transaction intent digests."""
    digest = compute_sha256_hash(b"test data")
    assert len(digest) == 64
    assert digest == "916f0027a575074ce72a331777c3478d6513f786a591bd892da1a577bf2335f9"

    tx = {
        "amount": "100.0000",
        "currency": "USD",
        "origin_account_number": "ACC100",
        "destination_account_number": "ACC200",
    }
    tx_hash_1 = compute_transaction_intent_hash(tx)
    # Reordered keys should result in identical digest
    tx_reordered = {
        "destination_account_number": "ACC200",
        "amount": "100.0000",
        "currency": "USD",
        "origin_account_number": "ACC100",
    }
    tx_hash_2 = compute_transaction_intent_hash(tx_reordered)
    assert tx_hash_1 == tx_hash_2


def test_sign_and_verify_signature_success() -> None:
    """Verify end-to-end signing and verification with Ed25519."""
    private_pem, public_pem = generate_ed25519_keypair()
    payload = {"agent_id": "test-agent", "nonce": "abc1234567890", "amount": "500.00"}

    sig_hex = sign_payload(private_pem, payload)
    assert len(sig_hex) == 128  # 64 bytes in hex

    is_valid = verify_signature(
        public_key_pem=public_pem,
        payload=payload,
        signature_hex=sig_hex,
        algorithm="Ed25519",
    )
    assert is_valid is True


def test_verify_signature_tampered_payload_rejected() -> None:
    """Verify tampered payload is rejected immediately."""
    private_pem, public_pem = generate_ed25519_keypair()
    payload = {"agent_id": "test-agent", "amount": "500.00"}

    sig_hex = sign_payload(private_pem, payload)

    tampered_payload = {"agent_id": "test-agent", "amount": "500.01"}
    is_valid = verify_signature(
        public_key_pem=public_pem,
        payload=tampered_payload,
        signature_hex=sig_hex,
        algorithm="Ed25519",
    )
    assert is_valid is False


def test_verify_signature_wrong_key_rejected() -> None:
    """Verify signature verification fails if checked against a different public key."""
    priv1, pub1 = generate_ed25519_keypair()
    _, pub2 = generate_ed25519_keypair()

    payload = {"agent_id": "test-agent"}
    sig_hex = sign_payload(priv1, payload)

    assert verify_signature(pub2, payload, sig_hex, algorithm="Ed25519") is False


def test_unsupported_algorithm_rejected() -> None:
    """Verify algorithm substitution attacks are rejected via allowlist."""
    _, public_pem = generate_ed25519_keypair()
    with pytest.raises(ValueError, match="Unsupported cryptographic algorithm"):
        verify_signature(
            public_key_pem=public_pem,
            payload={"test": 1},
            signature_hex="00" * 64,
            algorithm="RSA-MD5",
        )


def test_canonicalize_payload_rejects_floats() -> None:
    """Verify that floating-point values are rejected to prevent precision ambiguity."""
    with pytest.raises(ValueError, match="Floating-point values are prohibited"):
        canonicalize_payload({"amount": 12.34})

    with pytest.raises(ValueError, match="Floating-point values are prohibited"):
        canonicalize_payload({"nested": {"limit": 1000.5}})

    with pytest.raises(ValueError, match="Floating-point values are prohibited"):
        canonicalize_payload({"items": ["valid", 3.14]})


def test_canonicalize_payload_rejects_nan_and_inf() -> None:
    """Verify NaN and Infinity values cannot be serialized into canonical payloads."""
    with pytest.raises(ValueError, match="Floating-point values are prohibited"):
        canonicalize_payload({"bad": float("nan")})

    with pytest.raises(ValueError, match="Floating-point values are prohibited"):
        canonicalize_payload({"bad": float("inf")})


def test_canonicalize_payload_preserves_utf8() -> None:
    """Verify UTF-8 characters are encoded directly without ASCII escaping."""
    payload = {"merchant": "München Prüfungs GmbH", "branch": "東京支店"}
    canon = canonicalize_payload(payload)
    # Must not contain \u escaping
    assert b"\\u" not in canon
    assert "München Prüfungs GmbH".encode() in canon
    assert "東京支店".encode() in canon
