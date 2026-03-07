#!/usr/bin/env bash
# =============================================================================
# Smart BI Agent — One-Command Setup
# Architecture v3.1
#
# Usage: ./scripts/setup.sh
# This is the ENTIRE installer. After this, run: docker compose up -d
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo "==========================================="
echo "  Smart BI Agent — Setup v3.1"
echo "==========================================="
echo ""

# -------------------------------------------------------------------------
# Step 1: Environment file
# -------------------------------------------------------------------------
if [ ! -f .env ]; then
    echo -e "${YELLOW}Creating .env from .env.example...${NC}"
    cp .env.example .env
    echo -e "${RED}⚠️  EDIT .env NOW — change ALL passwords and secrets before proceeding!${NC}"
    echo ""
    echo "Required changes:"
    echo "  - POSTGRES_PASSWORD (strong, unique)"
    echo "  - REDIS_PASSWORD (strong, unique)"
    echo "  - ENCRYPTION_MASTER_KEY (run: python -c \"import secrets; print(secrets.token_hex(32))\")"
    echo "  - ADMIN_PASSWORD (strong, unique)"
    echo "  - FRONTEND_URL and CORS_ORIGINS (your actual domain)"
    echo ""
    read -p "Press Enter after editing .env, or Ctrl+C to abort..."
else
    echo -e "${GREEN}✅ .env already exists${NC}"
fi

# Source .env for validation
set -a
source .env
set +a

# -------------------------------------------------------------------------
# Step 2: Validate critical secrets
# -------------------------------------------------------------------------
echo "Validating configuration..."

if echo "$POSTGRES_PASSWORD" | grep -q "CHANGE_ME"; then
    echo -e "${RED}❌ POSTGRES_PASSWORD still has default value!${NC}"
    exit 1
fi

if echo "$ENCRYPTION_MASTER_KEY" | grep -q "CHANGE_ME"; then
    echo -e "${RED}❌ ENCRYPTION_MASTER_KEY still has default value!${NC}"
    echo "Generate one: python -c \"import secrets; print(secrets.token_hex(32))\""
    exit 1
fi

if [ ${#ENCRYPTION_MASTER_KEY} -lt 32 ]; then
    echo -e "${RED}❌ ENCRYPTION_MASTER_KEY too short (need 32+ chars)${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Configuration validated${NC}"

# -------------------------------------------------------------------------
# Step 3: Generate JWT keys
# -------------------------------------------------------------------------
KEYS_DIR="./keys"
if [ ! -f "$KEYS_DIR/private.pem" ]; then
    echo "Generating JWT RS256 key pair..."
    bash ./scripts/generate_keys.sh "$KEYS_DIR"
else
    echo -e "${GREEN}✅ JWT keys already exist${NC}"
fi

# -------------------------------------------------------------------------
# Step 4: Create Ollama models.lock (T33)
# -------------------------------------------------------------------------
if [ ! -f "models.lock" ]; then
    echo "Creating models.lock (Ollama model pinning)..."
    cat > models.lock << 'EOF'
# Smart BI Agent — Ollama Model Pinning (T33)
# Each model is pinned by SHA256 digest.
# To update: pull new model, get digest, update this file.
# Runtime pulls are DISABLED in production (Nginx blocks /api/pull).
#
# Format: model_name=sha256:digest
# Populate after running: ollama pull <model> && ollama show <model> --modelfile
EOF
    echo -e "${GREEN}✅ models.lock created (populate after pulling Ollama models)${NC}"
else
    echo -e "${GREEN}✅ models.lock already exists${NC}"
fi

# -------------------------------------------------------------------------
# Step 5: Build containers
# -------------------------------------------------------------------------
echo ""
echo "Building Docker containers..."
docker compose build

# -------------------------------------------------------------------------
# Step 6: Start services
# -------------------------------------------------------------------------
echo ""
echo "Starting services..."
docker compose up -d

# Wait for health
echo "Waiting for services to be healthy..."
sleep 10

# -------------------------------------------------------------------------
# Step 7: Run migrations
# -------------------------------------------------------------------------
echo "Running database migrations..."
docker compose exec -T backend alembic upgrade head

# -------------------------------------------------------------------------
# Step 8: Create initial admin (if configured)
# -------------------------------------------------------------------------
if [ -n "${ADMIN_EMAIL:-}" ] && [ -n "${ADMIN_PASSWORD:-}" ]; then
    echo "Creating initial admin account..."
    docker compose exec -T backend python -m app.scripts.create_admin || true
fi

# -------------------------------------------------------------------------
# Done
# -------------------------------------------------------------------------
echo ""
echo "==========================================="
echo -e "  ${GREEN}Smart BI Agent is running!${NC}"
echo "==========================================="
echo ""
echo "  🌐 Application:  https://localhost"
echo "  🔧 Backend API:  http://localhost:8000 (internal)"
echo "  📊 PostgreSQL:   localhost:5432 (internal)"
echo "  ⚡ Redis:        localhost:6379 (internal)"
echo ""
echo "  📋 Next steps:"
echo "     1. Configure LLM provider in Admin → LLM Providers"
echo "     2. Add database connection in Admin → Connections"
echo "     3. Set up permissions in Admin → Permissions"
echo "     4. Start asking questions!"
echo ""
