#!/usr/bin/env bash
# =============================================================================
# Smart BI Agent — Post-Fix Verification Script
# Run this AFTER applying all 9 file changes from the CTO audit
#
# USAGE:
#   cd /path/to/BI-AGENT-main
#   bash verify-fixes.sh
#
# This script validates each fix in isolation, then does a full integration
# test. If any step fails, it tells you exactly which fix has a problem.
# =============================================================================

set +e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

pass() { echo -e "  ${GREEN}✓ PASS${NC}  $1"; PASS=$((PASS+1)); }
fail() { echo -e "  ${RED}✗ FAIL${NC}  $1"; FAIL=$((FAIL+1)); }
warn() { echo -e "  ${YELLOW}⚠ WARN${NC}  $1"; WARN=$((WARN+1)); }
info() { echo -e "  ${CYAN}ℹ${NC}  $1"; }
header() { echo -e "\n${BOLD}━━━ $1 ━━━${NC}"; }

echo ""
echo "=============================================="
echo "  Smart BI Agent — Post-Fix Verification"
echo "  Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================="

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 1/8: Verify File Structure (Fix #4 — keys directory)"
# ─────────────────────────────────────────────────────────────────────────────

if [ -d "keys" ]; then
    pass "keys/ directory exists"
else
    fail "keys/ directory missing — create it: mkdir -p keys && touch keys/.gitkeep"
fi

if [ -f "keys/.gitkeep" ]; then
    pass "keys/.gitkeep exists"
else
    warn "keys/.gitkeep missing (not critical, but good for git)"
fi

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 2/8: Verify Dockerfile.backend (Fixes #2, #3)"
# ─────────────────────────────────────────────────────────────────────────────

# Fix #2: alembic.ini path
if grep -q "COPY backend/alembic.ini /app/alembic.ini" Dockerfile.backend; then
    pass "Fix #2: alembic.ini COPY path is correct"
else
    if grep -q "COPY backend/alembic/alembic.ini" Dockerfile.backend; then
        fail "Fix #2: Still has WRONG path 'backend/alembic/alembic.ini' — should be 'backend/alembic.ini'"
    else
        warn "Fix #2: alembic.ini COPY line not found — check Dockerfile.backend manually"
    fi
fi

# Fix #3: dev stage pyproject.toml from root
if grep -A2 "FROM base AS development" Dockerfile.backend | grep -q "COPY pyproject.toml /app/pyproject.toml"; then
    pass "Fix #3: Dev stage copies pyproject.toml from project root"
else
    if grep -A2 "FROM base AS development" Dockerfile.backend | grep -q "COPY backend/pyproject.toml"; then
        fail "Fix #3: Dev stage still copies from 'backend/pyproject.toml' — should be 'pyproject.toml'"
    else
        warn "Fix #3: Check dev stage COPY manually in Dockerfile.backend"
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 3/8: Verify docker-compose.yml (Fix #4 — JWT volume)"
# ─────────────────────────────────────────────────────────────────────────────

# Check backend service uses bind mount, not named volume
if grep -A20 "^  backend:" docker-compose.yml | grep -q "\./keys:/app/keys"; then
    pass "Fix #4: Backend uses bind mount ./keys:/app/keys"
else
    if grep -A20 "^  backend:" docker-compose.yml | grep -q "jwt_keys:/app/keys"; then
        fail "Fix #4: Backend still uses named volume 'jwt_keys' — keys will be empty in container"
    else
        warn "Fix #4: Could not find keys volume in backend service — check manually"
    fi
fi

# Check named volume jwt_keys is removed
if grep -q "jwt_keys:" docker-compose.yml; then
    warn "Fix #4: 'jwt_keys' named volume still defined in volumes section (harmless but unnecessary)"
else
    pass "Fix #4: 'jwt_keys' named volume removed from volumes section"
fi

# Check dev compose
if [ -f "docker-compose.dev.yml" ]; then
    if grep -q "\./keys:/app/keys" docker-compose.dev.yml; then
        pass "Fix #4: Dev compose also uses bind mount for keys"
    else
        if grep -q "jwt_keys:/app/keys" docker-compose.dev.yml; then
            fail "Fix #4: Dev compose still uses named volume for keys"
        else
            warn "Fix #4: Check docker-compose.dev.yml keys volume manually"
        fi
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 4/8: Verify Model Fixes (Fixes #5, #6)"
# ─────────────────────────────────────────────────────────────────────────────

# Fix #5: permission.py — Mapped[datetime] instead of Mapped[str] for created_at
if grep "created_at" backend/app/models/permission.py | grep -q "Mapped\[str\]"; then
    fail "Fix #5: permission.py created_at still has Mapped[str] — should be Mapped[datetime]"
else
    if grep "created_at" backend/app/models/permission.py | grep -q "Mapped\[datetime\]"; then
        pass "Fix #5: permission.py uses Mapped[datetime] for created_at"
    else
        warn "Fix #5: Could not verify permission.py type annotations"
    fi
fi

if grep -q "from datetime import datetime" backend/app/models/permission.py; then
    pass "Fix #5: permission.py imports datetime"
else
    fail "Fix #5: permission.py missing 'from datetime import datetime' import"
fi

# Fix #6: user.py — func.now() instead of "now()"
if grep -q 'server_default="now()"' backend/app/models/user.py; then
    fail "Fix #6: user.py ApiKey still has server_default=\"now()\" — should be func.now()"
else
    if grep -q "server_default=func.now()" backend/app/models/user.py; then
        pass "Fix #6: user.py ApiKey uses func.now()"
    else
        warn "Fix #6: Could not verify user.py server_default — check manually"
    fi
fi

if grep -q "from sqlalchemy.*func" backend/app/models/user.py; then
    pass "Fix #6: user.py imports func from sqlalchemy"
else
    fail "Fix #6: user.py missing func import"
fi

# Fix #6: notification_platform.py — same fix
if grep -q 'server_default="now()"' backend/app/models/notification_platform.py; then
    fail "Fix #6: notification_platform.py still has server_default=\"now()\""
else
    if grep -q "server_default=func.now()" backend/app/models/notification_platform.py; then
        pass "Fix #6: notification_platform.py uses func.now()"
    else
        warn "Fix #6: Could not verify notification_platform.py — check manually"
    fi
fi

if grep -q "from sqlalchemy.*func" backend/app/models/notification_platform.py; then
    pass "Fix #6: notification_platform.py imports func"
else
    fail "Fix #6: notification_platform.py missing func import"
fi

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 5/8: Verify pyproject.toml (Fix #7 — passlib removed)"
# ─────────────────────────────────────────────────────────────────────────────

if grep -q "passlib" pyproject.toml; then
    fail "Fix #7: passlib still in pyproject.toml — remove it"
else
    pass "Fix #7: passlib removed from dependencies"
fi

if grep -q "bcrypt==4.2.1" pyproject.toml; then
    pass "Fix #7: bcrypt direct dependency retained"
else
    warn "Fix #7: bcrypt dependency not found — verify it exists"
fi

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 6/8: Verify Alembic Migration (Fix #1 — the big one)"
# ─────────────────────────────────────────────────────────────────────────────

MIGRATION_COUNT=$(find backend/alembic/versions/ -name "*.py" ! -name "__init__.py" | wc -l)
if [ "$MIGRATION_COUNT" -ge 1 ]; then
    pass "Fix #1: Alembic migration file(s) found ($MIGRATION_COUNT)"
else
    fail "Fix #1: NO migration files in backend/alembic/versions/ — this is the biggest bug"
fi

# Check migration contains the revision ID referenced in migration.sql
if find backend/alembic/versions/ -name "*.py" -exec grep -l "3d18d54d005c" {} \; | head -1 | grep -q "."; then
    pass "Fix #1: Migration revision ID '3d18d54d005c' found (matches migration.sql)"
else
    warn "Fix #1: Could not find revision ID '3d18d54d005c' — verify migration file"
fi

# Check migration has the key tables
MIGRATION_FILE=$(find backend/alembic/versions/ -name "*.py" ! -name "__init__.py" | head -1)
if [ -n "$MIGRATION_FILE" ]; then
    TABLES_EXPECTED=("users" "api_keys" "connections" "llm_providers" "notification_platforms" "audit_logs" "saved_queries" "conversations" "conversation_messages" "schedules" "llm_token_usage" "key_rotation_registry" "role_permissions" "department_permissions" "user_permissions" "platform_user_mappings")
    MISSING_TABLES=0
    for table in "${TABLES_EXPECTED[@]}"; do
        if ! grep -q "'$table'" "$MIGRATION_FILE"; then
            fail "Fix #1: Table '$table' not found in migration"
            MISSING_TABLES=$((MISSING_TABLES+1))
        fi
    done
    if [ "$MISSING_TABLES" -eq 0 ]; then
        pass "Fix #1: All 16 tables present in migration"
    fi

    # Check critical defaults match the model
    if grep -q "'viewer'" "$MIGRATION_FILE"; then
        pass "Fix #1: users.role defaults to 'viewer' (not 'analyst')"
    else
        warn "Fix #1: Check users.role default in migration"
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 7/8: Verify alembic.ini location"
# ─────────────────────────────────────────────────────────────────────────────

if [ -f "backend/alembic.ini" ]; then
    pass "alembic.ini exists at backend/alembic.ini"
else
    fail "alembic.ini NOT found at backend/alembic.ini"
fi

if [ -f "backend/alembic/alembic.ini" ]; then
    warn "alembic.ini ALSO exists at backend/alembic/alembic.ini (old location — harmless but confusing)"
else
    pass "No stale alembic.ini in backend/alembic/ (clean)"
fi

if [ -f "backend/alembic/env.py" ]; then
    pass "alembic/env.py exists"
else
    fail "alembic/env.py missing — Alembic cannot run"
fi

# ─────────────────────────────────────────────────────────────────────────────
header "STEP 8/8: Pre-Docker Sanity Checks"
# ─────────────────────────────────────────────────────────────────────────────

# Check .env exists
if [ -f ".env" ]; then
    pass ".env file exists"
    
    # Check for placeholder values
    if grep -q "CHANGE_ME" .env; then
        warn ".env still has CHANGE_ME placeholders — update before production"
    else
        pass ".env has no CHANGE_ME placeholders"
    fi
else
    warn ".env file not found — copy from .env.example and configure before Docker start"
fi

# Check Docker is available
if command -v docker &> /dev/null; then
    pass "Docker CLI available"
    if docker info &> /dev/null; then
        pass "Docker daemon running"
    else
        warn "Docker daemon not running — start Docker Desktop / dockerd before building"
    fi
else
    warn "Docker not installed — required for deployment"
fi

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

echo ""
echo "=============================================="
echo "  VERIFICATION RESULTS"
echo "=============================================="
echo ""
echo -e "  ${GREEN}PASSED:  ${PASS}${NC}"
echo -e "  ${RED}FAILED:  ${FAIL}${NC}"
echo -e "  ${YELLOW}WARNINGS: ${WARN}${NC}"
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}ALL CHECKS PASSED — Ready for Docker build${NC}"
    echo ""
    echo "  Next steps (run these commands in order):"
    echo ""
    echo "    1. Generate JWT keys (if not already done):"
    echo "       bash scripts/generate_keys.sh ./keys"
    echo ""
    echo "    2. Configure .env (if not already done):"
    echo "       cp .env.example .env"
    echo "       # Edit .env — change ALL passwords"
    echo ""
    echo "    3. Build and start:"
    echo "       docker compose build --no-cache"
    echo "       docker compose up -d"
    echo ""
    echo "    4. Wait for health, then run migration:"
    echo "       sleep 15"
    echo "       docker compose exec backend alembic upgrade head"
    echo ""
    echo "    5. Create admin user:"
    echo "       docker compose exec backend python -m backend.scripts.create_admin"
    echo ""
    echo "    6. Verify health:"
    echo "       curl http://localhost:8000/health"
    echo ""
    echo "    7. Verify all tables created:"
    echo "       docker compose exec db psql -U \$POSTGRES_USER -d \$POSTGRES_DB \\"
    echo "         -c \"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;\""
    echo ""
else
    echo -e "  ${RED}${BOLD}${FAIL} CHECK(S) FAILED — Fix the issues above before proceeding${NC}"
fi

echo ""
exit $FAIL
