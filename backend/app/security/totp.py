"""
Smart BI Agent — TOTP (Time-based One-Time Password)
Architecture v3.1 | Security Layer 8 | Threat: T8

Admin accounts have god-mode access. MFA is REQUIRED.

Flow:
    1. Admin enables TOTP → server generates secret → returns QR code
    2. Admin scans QR in authenticator app (Google Auth, Authy, etc.)
    3. Admin verifies by submitting a code → TOTP enabled
    4. On every login, admin provides password + TOTP code
    5. TOTP secret is encrypted at rest using HKDF-derived key (KeyPurpose.TOTP_SECRETS)

Security:
    - Secret encrypted in DB (never plaintext)
    - QR code generated server-side, never stored
    - Verification allows ±1 window (30s tolerance for clock skew)
    - Re-authentication required for destructive admin operations
"""

from __future__ import annotations

import io
import base64
from typing import Optional

import pyotp
import qrcode

from app.security.key_manager import KeyManager, KeyPurpose


# TOTP configuration
TOTP_ISSUER = "Smart BI Agent"
TOTP_DIGITS = 6
TOTP_INTERVAL = 30  # seconds
TOTP_VALID_WINDOW = 1  # ±1 interval tolerance (handles 30s clock skew)


def generate_totp_secret() -> str:
    """
    Generate a new TOTP secret (base32-encoded, 32 chars).

    Returns:
        Base32-encoded secret string for use with authenticator apps.
    """
    return pyotp.random_base32(length=32)


def encrypt_totp_secret(secret: str, key_manager: KeyManager) -> str:
    """
    Encrypt a TOTP secret for database storage.

    Args:
        secret: The base32 TOTP secret.
        key_manager: KeyManager instance for encryption.

    Returns:
        Encrypted, versioned string: "v{N}:<encrypted>"
    """
    return key_manager.encrypt(secret, KeyPurpose.TOTP_SECRETS)


def decrypt_totp_secret(encrypted_secret: str, key_manager: KeyManager) -> str:
    """
    Decrypt a TOTP secret from database storage.

    Args:
        encrypted_secret: The encrypted TOTP secret from DB.
        key_manager: KeyManager instance for decryption.

    Returns:
        The original base32 TOTP secret.
    """
    return key_manager.decrypt(encrypted_secret, KeyPurpose.TOTP_SECRETS)


def generate_totp_uri(secret: str, email: str) -> str:
    """
    Generate an otpauth:// URI for QR code scanning.

    This URI is what authenticator apps expect when scanning a QR code.
    Format: otpauth://totp/Smart%20BI%20Agent:{email}?secret={secret}&issuer=Smart%20BI%20Agent

    Args:
        secret: The base32 TOTP secret.
        email: The user's email (used as account identifier in the app).

    Returns:
        otpauth:// URI string.
    """
    totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL)
    return totp.provisioning_uri(name=email, issuer_name=TOTP_ISSUER)


def generate_qr_code_base64(uri: str) -> str:
    """
    Generate a QR code image as a base64-encoded PNG.

    The frontend displays this as: <img src="data:image/png;base64,{result}" />

    This QR code is generated once during TOTP setup, sent to the client,
    and NEVER stored on the server.

    Args:
        uri: The otpauth:// URI to encode.

    Returns:
        Base64-encoded PNG image string.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return base64.b64encode(buffer.read()).decode("utf-8")


def verify_totp_code(secret: str, code: str) -> bool:
    """
    Verify a TOTP code against the secret.

    Allows ±1 window (30-second tolerance) to handle clock skew
    between server and authenticator app.

    Args:
        secret: The base32 TOTP secret.
        code: The 6-digit code from the authenticator app.

    Returns:
        True if the code is valid for the current or adjacent time window.
    """
    if not secret or not code:
        return False

    # Strip whitespace and dashes (some users type "123 456" or "123-456")
    code = code.replace(" ", "").replace("-", "")

    # Validate format
    if not code.isdigit() or len(code) != TOTP_DIGITS:
        return False

    totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL)
    return totp.verify(code, valid_window=TOTP_VALID_WINDOW)


class TOTPSetupResult:
    """Result of initiating TOTP setup for an admin user."""

    def __init__(self, secret: str, email: str) -> None:
        self.secret = secret
        self.uri = generate_totp_uri(secret, email)
        self.qr_code_base64 = generate_qr_code_base64(self.uri)

    def to_dict(self) -> dict:
        """
        Serialize for API response.
        NOTE: secret is included so user can manually enter it if QR fails.
        This response is sent ONCE during setup and never stored.
        """
        return {
            "qr_code": f"data:image/png;base64,{self.qr_code_base64}",
            "secret": self.secret,  # Manual entry fallback
            "uri": self.uri,
        }


def setup_totp(email: str) -> TOTPSetupResult:
    """
    Initiate TOTP setup for an admin user.

    Generates a new secret, creates QR code, returns setup data.
    The secret is NOT saved to DB yet — that happens after verification.

    Args:
        email: Admin user's email.

    Returns:
        TOTPSetupResult with QR code and secret.
    """
    secret = generate_totp_secret()
    return TOTPSetupResult(secret=secret, email=email)
