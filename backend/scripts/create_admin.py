"""
Smart BI Agent — Create Initial Admin User
Architecture v3.1 | Bootstrap Script

PURPOSE:
    Creates the first admin user in the database.
    Run this ONCE after initial deployment before any login is possible.

USAGE:
    cd backend
    source .venv/Scripts/activate   # Windows Git Bash
    python scripts/create_admin.py

    Or with custom credentials:
    ADMIN_EMAIL=admin@company.com ADMIN_PASSWORD=SecurePass123! python scripts/create_admin.py

SECURITY:
    - Password is bcrypt cost-12 hashed (never stored plain)
    - TOTP secret is generated and encrypted with HKDF-derived key
    - If ADMIN_EMAIL/ADMIN_PASSWORD env vars are not set, prompts interactively
    - Idempotent: if admin already exists, prints status and exits cleanly

TOTP SETUP:
    After running this script, the admin must:
    1. Log in at /api/v1/auth/login
    2. Use the QR code / secret shown here to set up their authenticator app
    3. Complete TOTP verification at /api/v1/auth/totp/verify
    4. All subsequent logins require both password + TOTP code
"""

from __future__ import annotations

import asyncio
import getpass
import os
import sys

# Add backend/ to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def create_admin() -> None:
    """Main entry point — create admin user."""

    # Load settings (triggers env var validation)
    from app.config import get_settings
    settings = get_settings()

    print(f"\n{'='*60}")
    print(f"  Smart BI Agent — Admin Bootstrap")
    print(f"  Environment: {settings.APP_ENV.value}")
    print(f"{'='*60}\n")

    # ------------------------------------------------------------------
    # Gather credentials
    # ------------------------------------------------------------------
    email = (
        os.environ.get("ADMIN_EMAIL")
        or settings.ADMIN_EMAIL
        or input("Admin email: ").strip()
    )
    if not email or "@" not in email:
        print("ERROR: Invalid email address.")
        sys.exit(1)

    name = (
        os.environ.get("ADMIN_NAME")
        or settings.ADMIN_NAME
        or input("Admin name [System Admin]: ").strip()
        or "System Admin"
    )

    password = (
        os.environ.get("ADMIN_PASSWORD")
        or settings.ADMIN_PASSWORD
    )
    if not password:
        password = getpass.getpass("Admin password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("ERROR: Passwords do not match.")
            sys.exit(1)

    if len(password) < 12:
        print("ERROR: Password must be at least 12 characters.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Initialize infrastructure
    # ------------------------------------------------------------------
    from app.logging.structured import configure_logging
    configure_logging()

    from app.security.key_manager import init_key_manager
    km = init_key_manager(settings.ENCRYPTION_MASTER_KEY)

    from app.db.session import init_db_engine
    import app.db.session as db_session
    init_db_engine()

    # ------------------------------------------------------------------
    # Check for existing admin
    # ------------------------------------------------------------------
    from sqlalchemy import select
    from app.models.user import User

    async with db_session._async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.email == email)
        )
        existing = result.scalar_one_or_none()

        if existing:
            print(f"\n✓ Admin user already exists: {email}")
            print(f"  Role:     {existing.role}")
            print(f"  Active:   {existing.is_active}")
            print(f"  Approved: {existing.is_approved}")
            print(f"  TOTP:     {'enabled' if existing.totp_enabled else 'not yet set up'}")
            print("\nNothing changed. Use the TOTP setup endpoint to enable MFA.\n")
            return

        # ------------------------------------------------------------------
        # Hash password
        # ------------------------------------------------------------------
        from app.security.password import hash_password
        hashed_pw = hash_password(password)
        print(f"\n✓ Password hashed (bcrypt cost-12)")

        # ------------------------------------------------------------------
        # Generate and encrypt TOTP secret
        # ------------------------------------------------------------------
        from app.security.totp import generate_totp_secret, encrypt_totp_secret, TOTPSetupResult
        totp_secret = generate_totp_secret()
        encrypted_secret = encrypt_totp_secret(totp_secret, km)
        totp_result = TOTPSetupResult(secret=totp_secret, email=email)
        print(f"✓ TOTP secret generated and encrypted")

        # ------------------------------------------------------------------
        # Create user
        # ------------------------------------------------------------------
        import uuid
        admin_user = User(
            id=uuid.uuid4(),
            email=email,
            name=name,
            hashed_password=hashed_pw,
            role="admin",
            is_active=True,
            is_approved=True,
            totp_secret_enc=encrypted_secret,
            totp_enabled=False,  # Must be confirmed via TOTP verify endpoint
        )

        session.add(admin_user)
        await session.commit()
        print(f"✓ Admin user created in database")

    # ------------------------------------------------------------------
    # Print TOTP setup instructions
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"  ADMIN USER CREATED SUCCESSFULLY")
    print(f"{'='*60}")
    print(f"\n  Email:    {email}")
    print(f"  Name:     {name}")
    print(f"  Role:     admin")
    print(f"\n  ⚠  MFA SETUP REQUIRED (admin accounts require TOTP)")
    print(f"\n  TOTP Secret (save this securely — shown once):")
    print(f"  {totp_secret}")
    print(f"\n  TOTP URI for authenticator app:")
    print(f"  {totp_result.uri}")
    print(f"\n  NEXT STEPS:")
    print(f"  1. Scan the QR code or enter the secret in your authenticator app")
    print(f"  2. Log in: POST /api/v1/auth/login")
    print(f"  3. Verify TOTP: POST /api/v1/auth/totp/verify")
    print(f"     Body: {{\"code\": \"<6-digit-code>\"}}")
    print(f"  4. After verification, TOTP is required for every future login")
    print(f"\n{'='*60}\n")

    # Clean up
    from app.db.session import close_db_engine
    await close_db_engine()


if __name__ == "__main__":
    asyncio.run(create_admin())
