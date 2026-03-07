"""
Smart BI Agent — HKDF Key Manager
Architecture v3.1 | Security Layer 8 | Threats: T1, T2

PURPOSE:
    One master key → multiple purpose-specific derived keys via HKDF.
    This prevents a single compromised key from exposing ALL encrypted data.

HIERARCHY:
    ENCRYPTION_MASTER_KEY (env var)
        ├── db_credentials    → encrypts database connection credentials
        ├── llm_api_keys      → encrypts LLM provider API keys
        ├── notification_keys → encrypts notification platform tokens
        ├── totp_secrets      → encrypts TOTP secrets for admin MFA
        └── session_keys      → encrypts session-related data

KEY VERSIONING (T2):
    Every encrypted value is prefixed with "v{N}:" where N is the key version.
    This enables zero-downtime key rotation:
        1. Increment version, derive new keys
        2. New encryptions use new version
        3. Decryption reads prefix, uses correct version
        4. Background job re-encrypts old values with new version
        5. After full re-encryption, retire old version

VAULT INTEGRATION PATH:
    Replace get_master_key() to read from HashiCorp Vault, AWS KMS, or
    GCP Cloud KMS. The rest of the hierarchy remains unchanged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from enum import Enum
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class KeyPurpose(str, Enum):
    """
    Purpose-specific key derivation contexts.
    Each purpose gets a unique derived key from the master key.
    A compromise of one derived key does NOT compromise others.
    """
    DB_CREDENTIALS = "db_credentials"
    LLM_API_KEYS = "llm_api_keys"
    NOTIFICATION_KEYS = "notification_keys"
    TOTP_SECRETS = "totp_secrets"
    SESSION_KEYS = "session_keys"


# Current key version — increment on rotation
CURRENT_KEY_VERSION: int = 1

# Version prefix format: "v{N}:" prepended to every encrypted value
VERSION_PREFIX = "v{version}:"


class KeyDerivationError(Exception):
    """Raised when key derivation fails."""
    pass


class DecryptionError(Exception):
    """Raised when decryption fails (wrong key, corrupted data, invalid version)."""
    pass


class EncryptionError(Exception):
    """Raised when encryption fails."""
    pass


def _derive_key(master_key: bytes, purpose: KeyPurpose, version: int) -> bytes:
    """
    Derive a purpose-specific encryption key using HKDF-SHA256.

    HKDF (HMAC-based Key Derivation Function) is the industry standard
    for deriving multiple keys from a single master key. It provides:
        - Cryptographic independence between derived keys
        - Deterministic output (same inputs → same key)
        - Resistance to related-key attacks

    Args:
        master_key: The raw master key bytes.
        purpose: Which subsystem this key is for.
        version: Key version number for rotation.

    Returns:
        32 bytes suitable for Fernet (after base64 encoding).
    """
    # Info string binds the derived key to its specific purpose and version.
    # Changing purpose OR version produces a completely different key.
    info = f"smart-bi-agent:{purpose.value}:v{version}".encode("utf-8")

    # Salt is fixed per deployment. In production, this could come from
    # a separate secret, but HKDF with a fixed salt is still secure
    # when the master key has sufficient entropy (32+ bytes).
    salt = b"smart-bi-agent-hkdf-salt-v1"

    hkdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=salt,
        info=info,
    )

    return hkdf.derive(master_key)


def _get_fernet(master_key: bytes, purpose: KeyPurpose, version: int) -> Fernet:
    """
    Get a Fernet instance for a specific purpose and version.

    Fernet uses AES-128-CBC with HMAC-SHA256 for authenticated encryption.
    The derived 32-byte key is base64-encoded as Fernet expects.
    """
    derived = _derive_key(master_key, purpose, version)
    # Fernet requires a 32-byte key, base64url-encoded
    fernet_key = base64.urlsafe_b64encode(derived)
    return Fernet(fernet_key)


class KeyManager:
    """
    Central key management for Smart BI Agent.

    Manages the HKDF key hierarchy, versioned encryption/decryption,
    and provides the foundation for zero-downtime key rotation.

    Usage:
        km = KeyManager(master_key_hex="abcdef0123456789...")

        # Encrypt
        encrypted = km.encrypt("my-secret-api-key", KeyPurpose.LLM_API_KEYS)
        # Returns: "v1:<base64-encrypted-data>"

        # Decrypt
        plaintext = km.decrypt(encrypted, KeyPurpose.LLM_API_KEYS)
        # Returns: "my-secret-api-key"
    """

    def __init__(self, master_key_hex: str) -> None:
        """
        Initialize with the master key from environment.

        Args:
            master_key_hex: Hex-encoded master key (64+ hex chars = 32+ bytes).

        Raises:
            KeyDerivationError: If master key is too short or invalid.
        """
        if not master_key_hex or len(master_key_hex) < 32:
            raise KeyDerivationError(
                "ENCRYPTION_MASTER_KEY must be at least 32 characters. "
                "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )

        try:
            self._master_key = bytes.fromhex(master_key_hex)
        except ValueError:
            # If not valid hex, use raw bytes via SHA256 hash
            # This handles non-hex master keys gracefully
            self._master_key = hashlib.sha256(master_key_hex.encode("utf-8")).digest()

        self._current_version = CURRENT_KEY_VERSION

        # Pre-derive current version keys for all purposes (performance)
        self._fernet_cache: dict[tuple[KeyPurpose, int], Fernet] = {}

    def _get_fernet_cached(self, purpose: KeyPurpose, version: int) -> Fernet:
        """Get or create a cached Fernet instance for purpose+version."""
        cache_key = (purpose, version)
        if cache_key not in self._fernet_cache:
            self._fernet_cache[cache_key] = _get_fernet(
                self._master_key, purpose, version
            )
        return self._fernet_cache[cache_key]

    @property
    def current_version(self) -> int:
        """Current key version used for new encryptions."""
        return self._current_version

    def encrypt(self, plaintext: str, purpose: KeyPurpose) -> str:
        """
        Encrypt a string with a purpose-specific derived key.

        The result is prefixed with the key version for future rotation:
            "v1:<fernet-encrypted-base64>"

        Args:
            plaintext: The secret to encrypt (e.g., API key, DB password).
            purpose: Which subsystem this secret belongs to.

        Returns:
            Versioned encrypted string: "v{N}:<encrypted-data>"

        Raises:
            EncryptionError: If encryption fails.
        """
        if not plaintext:
            raise EncryptionError("Cannot encrypt empty string")

        try:
            fernet = self._get_fernet_cached(purpose, self._current_version)
            encrypted_bytes = fernet.encrypt(plaintext.encode("utf-8"))
            encrypted_str = encrypted_bytes.decode("utf-8")

            # Prepend version prefix for rotation support
            prefix = VERSION_PREFIX.format(version=self._current_version)
            return f"{prefix}{encrypted_str}"

        except Exception as e:
            raise EncryptionError(f"Encryption failed for {purpose.value}: {e}") from e

    def decrypt(self, encrypted_value: str, purpose: KeyPurpose) -> str:
        """
        Decrypt a versioned encrypted string.

        Reads the version prefix to determine which derived key to use.
        This enables decryption of values encrypted with ANY previous version,
        which is critical during key rotation.

        Args:
            encrypted_value: The "v{N}:<encrypted>" string from the database.
            purpose: Which subsystem this secret belongs to.

        Returns:
            The original plaintext string.

        Raises:
            DecryptionError: If version is invalid, key is wrong, or data is corrupted.
        """
        if not encrypted_value:
            raise DecryptionError("Cannot decrypt empty value")

        try:
            version, ciphertext = self._parse_version(encrypted_value)
            fernet = self._get_fernet_cached(purpose, version)
            decrypted_bytes = fernet.decrypt(ciphertext.encode("utf-8"))
            return decrypted_bytes.decode("utf-8")

        except DecryptionError:
            raise
        except InvalidToken:
            raise DecryptionError(
                f"Decryption failed for {purpose.value}: invalid token "
                "(wrong key version, corrupted data, or wrong purpose)"
            )
        except Exception as e:
            raise DecryptionError(
                f"Decryption failed for {purpose.value}: {e}"
            ) from e

    def re_encrypt(self, encrypted_value: str, purpose: KeyPurpose) -> Optional[str]:
        """
        Re-encrypt a value with the current key version.

        Used during key rotation: decrypt with old version, encrypt with new.
        Returns None if the value is already at the current version.

        Args:
            encrypted_value: The existing encrypted value.
            purpose: Which subsystem this secret belongs to.

        Returns:
            New encrypted string at current version, or None if already current.
        """
        version, _ = self._parse_version(encrypted_value)
        if version == self._current_version:
            return None  # Already at current version

        # Decrypt with old version, encrypt with current
        plaintext = self.decrypt(encrypted_value, purpose)
        return self.encrypt(plaintext, purpose)

    def needs_rotation(self, encrypted_value: str) -> bool:
        """Check if an encrypted value needs re-encryption (old version)."""
        version, _ = self._parse_version(encrypted_value)
        return version < self._current_version

    def get_key_fingerprint(self, purpose: KeyPurpose, version: Optional[int] = None) -> str:
        """
        Get a safe fingerprint of a derived key (for logging/debugging).

        Returns first 8 chars of SHA256 hash — enough to identify which
        key is in use without exposing any key material.
        """
        v = version or self._current_version
        derived = _derive_key(self._master_key, purpose, v)
        return hashlib.sha256(derived).hexdigest()[:8]

    @staticmethod
    def _parse_version(encrypted_value: str) -> tuple[int, str]:
        """
        Parse the version prefix from an encrypted value.

        Expected format: "v{N}:<ciphertext>"

        Returns:
            Tuple of (version_number, ciphertext_without_prefix)

        Raises:
            DecryptionError: If format is invalid.
        """
        if not encrypted_value.startswith("v"):
            raise DecryptionError(
                f"Invalid encrypted value format: missing version prefix. "
                f"Expected 'v{{N}}:...' but got '{encrypted_value[:10]}...'"
            )

        try:
            prefix_end = encrypted_value.index(":")
            version_str = encrypted_value[1:prefix_end]  # Skip "v", take until ":"
            version = int(version_str)
            ciphertext = encrypted_value[prefix_end + 1:]

            if version < 1:
                raise DecryptionError(f"Invalid key version: {version}")
            if not ciphertext:
                raise DecryptionError("Empty ciphertext after version prefix")

            return version, ciphertext

        except (ValueError, IndexError) as e:
            raise DecryptionError(
                f"Invalid version prefix format in encrypted value: {e}"
            ) from e

    def derive_hmac_key(self, purpose: KeyPurpose) -> bytes:
        """
        Derive a key suitable for HMAC operations (e.g., cache key hashing).

        Separate from Fernet encryption keys — uses a different HKDF info string.
        """
        info = f"smart-bi-agent:hmac:{purpose.value}:v{self._current_version}".encode("utf-8")
        salt = b"smart-bi-agent-hmac-salt-v1"

        hkdf = HKDF(
            algorithm=SHA256(),
            length=32,
            salt=salt,
            info=info,
        )

        return hkdf.derive(self._master_key)

    def compute_permission_hash(self, user_id: str, permissions: dict) -> str:
        """
        Compute a deterministic hash of user permissions.

        Used in Redis cache keys (T42) to ensure cached query results
        are never served to a user with different permissions.

        Args:
            user_id: The user's UUID string.
            permissions: The resolved permission dict.

        Returns:
            8-character hex hash string.
        """
        hmac_key = self.derive_hmac_key(KeyPurpose.SESSION_KEYS)
        # Sort for deterministic ordering
        perm_str = f"{user_id}:{_stable_serialize(permissions)}"
        h = hmac.new(hmac_key, perm_str.encode("utf-8"), hashlib.sha256)
        return h.hexdigest()[:8]


def _stable_serialize(obj: object) -> str:
    """Deterministic serialization for permission hashing."""
    if isinstance(obj, dict):
        items = sorted(obj.items())
        return "{" + ",".join(f"{k}:{_stable_serialize(v)}" for k, v in items) + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(_stable_serialize(i) for i in obj) + "]"
    return str(obj)


# =============================================================================
# Module-level singleton (initialized from config)
# =============================================================================

_key_manager_instance: Optional[KeyManager] = None


def init_key_manager(master_key_hex: str) -> KeyManager:
    """
    Initialize the global KeyManager singleton.
    Called once during application startup (lifespan).
    """
    global _key_manager_instance
    _key_manager_instance = KeyManager(master_key_hex)
    return _key_manager_instance


def get_key_manager() -> KeyManager:
    """
    Get the global KeyManager instance.

    Raises:
        RuntimeError: If init_key_manager() hasn't been called yet.
    """
    if _key_manager_instance is None:
        raise RuntimeError(
            "KeyManager not initialized. Call init_key_manager() during app startup."
        )
    return _key_manager_instance