"""
Smart BI Agent — Password Hashing
Architecture v3.1 | Security Layer 8
bcrypt cost factor 12 — intentionally slow to resist brute force.
"""

from __future__ import annotations

import hashlib
import base64

from passlib.context import CryptContext

# bcrypt with cost factor 12
# Each hash takes ~250ms — fast enough for login, slow enough to resist brute force.
# NEVER reduce the cost factor below 12 in production.
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)


def _prepare_password(password: str) -> str:
    """
    Prepare password for bcrypt.

    bcrypt has a 72-byte input limit. Passwords longer than 72 bytes
    are pre-hashed with SHA-256 and base64-encoded, which produces a
    fixed 44-character string that bcrypt can handle safely.

    This is a standard pattern used by Dropbox and Django.
    """
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        # Pre-hash with SHA-256 → base64 encode → 44 chars (fits in 72 bytes)
        sha_hash = hashlib.sha256(password_bytes).digest()
        return base64.b64encode(sha_hash).decode("ascii")
    return password


def hash_password(password: str) -> str:
    """
    Hash a plaintext password with bcrypt (cost 12).

    Args:
        password: The plaintext password.

    Returns:
        bcrypt hash string (e.g., "$2b$12$...").
    """
    if not password:
        raise ValueError("Password cannot be empty")
    prepared = _prepare_password(password)
    return pwd_context.hash(prepared)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a bcrypt hash.
    Uses constant-time comparison internally (passlib handles this).

    Args:
        plain_password: The password attempt.
        hashed_password: The stored bcrypt hash.

    Returns:
        True if password matches, False otherwise.
    """
    if not plain_password or not hashed_password:
        return False
    prepared = _prepare_password(plain_password)
    return pwd_context.verify(prepared, hashed_password)


def needs_rehash(hashed_password: str) -> bool:
    """
    Check if a hash needs upgrading (e.g., cost factor was increased).
    Call on successful login to transparently upgrade old hashes.
    """
    return pwd_context.needs_update(hashed_password)