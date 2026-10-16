"""Cryptographic primitives and Ed25519 signature verification for AgentID."""

import hashlib
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

SUPPORTED_SIGNING_ALGORITHMS = {"Ed25519"}


def generate_ed25519_keypair() -> tuple[str, str]:
    """Generate an Ed25519 keypair formatted as PEM strings.

    Returns:
        tuple[str, str]: (private_key_pem, public_key_pem)
    """
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    return private_pem, public_pem


def load_ed25519_public_key(public_key_pem: str) -> ed25519.Ed25519PublicKey:
    """Parse and validate a PEM-encoded Ed25519 public key."""
    key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    if not isinstance(key, ed25519.Ed25519PublicKey):
        raise TypeError("Public key is not an Ed25519 public key.")
    return key


def load_ed25519_private_key(private_key_pem: str) -> ed25519.Ed25519PrivateKey:
    """Parse and validate a PEM-encoded Ed25519 private key."""
    key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"),
        password=None,
    )
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise TypeError("Private key is not an Ed25519 private key.")
    return key


def _validate_no_floats(obj: Any) -> None:
    """Recursively reject binary floating-point numbers to enforce exact Decimal representations."""
    if isinstance(obj, float):
        raise ValueError(f"Floating-point values are prohibited in canonical payloads: {obj}")
    if isinstance(obj, dict):
        for v in obj.values():
            _validate_no_floats(v)
    elif isinstance(obj, list):
        for item in obj:
            _validate_no_floats(item)


def canonicalize_payload(payload: dict[str, Any]) -> bytes:
    """Produce deterministic canonical UTF-8 bytes for a JSON payload.

    Applies lexicographical key sorting, strips unnecessary whitespace, disallows NaN/Infinity,
    and strictly prohibits binary float values to guarantee cross-platform signature consistency.
    """
    _validate_no_floats(payload)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def compute_sha256_hash(data: bytes | str) -> str:
    """Compute the SHA-256 hexadecimal digest of input bytes or string."""
    input_bytes = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(input_bytes).hexdigest()


def compute_transaction_intent_hash(
    intent_or_origin_institution_code: dict[str, Any] | str,
    origin_account_number: str | None = None,
    destination_institution_code: str | None = None,
    destination_account_number: str | None = None,
    amount: str | None = None,
    currency: str | None = None,
    transaction_type: str | None = None,
    purpose_code: str | None = None,
) -> str:
    """Compute deterministic SHA-256 digest of canonical transaction intent fields."""
    if isinstance(intent_or_origin_institution_code, dict):
        filtered = {k: v for k, v in intent_or_origin_institution_code.items() if v is not None}
        return compute_sha256_hash(canonicalize_payload(filtered))

    intent = {
        "amount": str(amount),
        "currency": str(currency).upper() if currency else "",
        "destination_account_number": str(destination_account_number or ""),
        "destination_institution_code": str(destination_institution_code or ""),
        "origin_account_number": str(origin_account_number or ""),
        "origin_institution_code": str(intent_or_origin_institution_code or ""),
        "transaction_type": str(transaction_type or ""),
    }
    if purpose_code:
        intent["purpose_code"] = str(purpose_code)
    return compute_sha256_hash(canonicalize_payload(intent))


def sign_payload(
    private_key: ed25519.Ed25519PrivateKey | str,
    payload: bytes | dict[str, Any] | str,
) -> str:
    """Generate an Ed25519 digital signature over canonical payload bytes.

    Returns:
        Hex-encoded signature string.
    """
    key = load_ed25519_private_key(private_key) if isinstance(private_key, str) else private_key

    if isinstance(payload, dict):
        payload_bytes = canonicalize_payload(payload)
    elif isinstance(payload, str):
        payload_bytes = payload.encode("utf-8")
    else:
        payload_bytes = payload

    signature = key.sign(payload_bytes)
    return signature.hex()


def verify_signature(
    public_key: ed25519.Ed25519PublicKey | str | None = None,
    payload: bytes | dict[str, Any] | str | None = None,
    signature_hex: str = "",
    algorithm: str = "Ed25519",
    public_key_pem: str | None = None,
) -> bool:
    """Verify an Ed25519 signature over canonical payload bytes.

    Returns:
        True if the signature is valid, False otherwise.
    """
    if algorithm not in SUPPORTED_SIGNING_ALGORITHMS:
        raise ValueError(
            f"Unsupported cryptographic algorithm '{algorithm}'. "
            f"Allowed algorithms: {list(SUPPORTED_SIGNING_ALGORITHMS)}"
        )

    target_key = public_key_pem if public_key is None else public_key
    if target_key is None:
        raise ValueError("A public key must be provided.")

    try:
        key = load_ed25519_public_key(target_key) if isinstance(target_key, str) else target_key

        if isinstance(payload, dict):
            payload_bytes = canonicalize_payload(payload)
        elif isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        elif payload is not None:
            payload_bytes = payload
        else:
            payload_bytes = b""

        signature_bytes = bytes.fromhex(signature_hex)
        key.verify(signature_bytes, payload_bytes)
        return True
    except (ValueError, InvalidSignature, TypeError):
        return False
