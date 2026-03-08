"""
Smart BI Agent — Password Hashing
Architecture v3.1 | Security Layer 8
bcrypt cost factor 12 — intentionally slow to resist brute force.

NOTE: We use bcrypt directly instead of passlib.
      passlib is unmaintained and incompatible with bcrypt 4.2+.
"""

from __future__ import annotations

import hashlib
import base64

import bcrypt

# Cost factor 12: ~250ms per hash. Fast enough for login, slow enough for brute force.
BCRYPT_ROUNDS = 12


def _prepare_password(password: str) -> bytes:
    """
    Prepare password for bcrypt.

    bcrypt has a 72-byte input limit. Passwords longer than 72 bytes
    are pre-hashed with SHA-256 and base64-encoded, producing a
    fixed 44-byte string. This is the standard pattern used by
    Dropbox and Django.
    """
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        sha_hash = hashlib.sha256(password_bytes).digest()
        return base64.b64encode(sha_hash)
    return password_bytes


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
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(prepared, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a bcrypt hash.
    bcrypt.checkpw uses constant-time comparison internally.

    Args:
        plain_password: The password attempt.
        hashed_password: The stored bcrypt hash.

    Returns:
        True if password matches, False otherwise.
    """
    if not plain_password or not hashed_password:
        return False
    try:
        prepared = _prepare_password(plain_password)
        return bcrypt.checkpw(prepared, hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def needs_rehash(hashed_password: str) -> bool:
    """
    Check if a hash needs upgrading (e.g., cost factor was increased).
    Parses the bcrypt prefix to check the rounds value.
    """
    try:
        # bcrypt format: $2b$12$...
        parts = hashed_password.split("$")
        if len(parts) >= 3:
            current_rounds = int(parts[2])
            return current_rounds < BCRYPT_ROUNDS
    except (ValueError, IndexError):
        pass
    return True  # If we can't parse it, it needs rehashing