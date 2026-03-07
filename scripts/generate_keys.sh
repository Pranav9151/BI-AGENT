#!/usr/bin/env bash
# =============================================================================
# Smart BI Agent — RSA Key Pair Generation for JWT RS256
# Architecture v3.1 | T4: Algorithm confusion prevention
# 
# Generates a 4096-bit RSA key pair for signing/verifying JWTs.
# Algorithm is HARDCODED to RS256 in auth.py — these keys are the ONLY
# way to sign tokens. HS256 and "none" are permanently blocked.
# =============================================================================

set -euo pipefail

KEYS_DIR="${1:-./keys}"

echo "==========================================="
echo "Smart BI Agent — JWT Key Generation"
echo "==========================================="

mkdir -p "$KEYS_DIR"

# Check if keys already exist
if [ -f "$KEYS_DIR/private.pem" ] && [ -f "$KEYS_DIR/public.pem" ]; then
    echo "⚠️  Keys already exist at $KEYS_DIR/"
    read -p "Overwrite? (y/N): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Aborted."
        exit 0
    fi
fi

# Generate 4096-bit RSA private key
openssl genrsa -out "$KEYS_DIR/private.pem" 4096 2>/dev/null
echo "✅ Private key generated: $KEYS_DIR/private.pem"

# Extract public key
openssl rsa -in "$KEYS_DIR/private.pem" -pubout -out "$KEYS_DIR/public.pem" 2>/dev/null
echo "✅ Public key generated: $KEYS_DIR/public.pem"

# Restrict permissions
chmod 600 "$KEYS_DIR/private.pem"
chmod 644 "$KEYS_DIR/public.pem"
echo "✅ Permissions set: private=600, public=644"

echo ""
echo "==========================================="
echo "Keys ready. NEVER commit these to git."
echo "==========================================="
