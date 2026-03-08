"""
Smart BI Agent — Password Hashing
Architecture v3.1 | Security Layer 8
bcrypt cost factor 12 — intentionally slow to resist brute force.
"""

from __future__ import annotations

from passlib.context import CryptContext

# bcrypt with cost factor 12
# Each hash takes ~250ms — fast enough for login, slow enough to resist brute force.
# NEVER reduce the cost factor below 12 in production.
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)


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
    return pwd_context.hash(password)


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
    return pwd_context.verify(plain_password, hashed_password)


def needs_rehash(hashed_password: str) -> bool:
    """
    Check if a hash needs upgrading (e.g., cost factor was increased).
    Call on successful login to transparently upgrade old hashes.
    """
    return pwd_context.needs_update(hashed_password)
