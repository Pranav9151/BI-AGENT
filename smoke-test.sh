#!/bin/bash
# =============================================================================
# Smart BI Agent — Post-Deployment Smoke Test
# Run this AFTER docker compose up -d + wait 30 seconds
# =============================================================================

set -e
PASS=0
FAIL=0
WARN=0

check() {
    local name="$1"
    local result="$2"
    if [ "$result" = "PASS" ]; then
        echo "  ✅ $name"
        PASS=$((PASS + 1))
    elif [ "$result" = "WARN" ]; then
        echo "  ⚠️  $name"
        WARN=$((WARN + 1))
    else
        echo "  ❌ $name"
        FAIL=$((FAIL + 1))
    fi
}

echo ""
echo "============================================="
echo "  Smart BI Agent — Smoke Test"
echo "============================================="
echo ""

# 1. Health check
echo "[1/8] Health Check"
HEALTH=$(curl -sf http://localhost/health 2>/dev/null || echo "FAIL")
if echo "$HEALTH" | grep -q '"status"'; then
    check "GET /health returns JSON" "PASS"
else
    check "GET /health returns JSON" "FAIL"
fi

# 2. Metrics endpoint
echo "[2/8] Metrics"
METRICS=$(curl -sf http://localhost/metrics 2>/dev/null || echo "FAIL")
if echo "$METRICS" | grep -q "sbi_http"; then
    check "GET /metrics returns Prometheus data" "PASS"
else
    check "GET /metrics returns Prometheus data" "WARN"
fi

# 3. Login
echo "[3/8] Authentication"
LOGIN=$(curl -sf -X POST http://localhost/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@smartbi.com","password":"Admin@123456!"}' 2>/dev/null || echo '{"error":"FAIL"}')

TOKEN=$(echo "$LOGIN" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null || echo "")
TOTP=$(echo "$LOGIN" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('totp_required',False))" 2>/dev/null || echo "")

if [ -n "$TOKEN" ] && [ "$TOKEN" != "" ]; then
    check "POST /auth/login returns access_token" "PASS"
else
    check "POST /auth/login returns access_token" "FAIL"
    echo "       Response: $LOGIN"
fi

if [ "$TOTP" = "False" ] || [ "$TOTP" = "false" ]; then
    check "TOTP is skipped in development" "PASS"
else
    check "TOTP is skipped in development (got: $TOTP)" "FAIL"
fi

# Check token type
if [ -n "$TOKEN" ]; then
    JWT_TYPE=$(echo "$TOKEN" | cut -d. -f2 | python -c "
import sys,base64,json
p = sys.stdin.read().strip()
p += '=' * (-len(p) % 4)
d = json.loads(base64.b64decode(p))
print(d.get('type',''))
" 2>/dev/null || echo "unknown")
    if [ "$JWT_TYPE" = "access" ]; then
        check "JWT type is 'access' (not 'pre_totp')" "PASS"
    else
        check "JWT type is '$JWT_TYPE' (expected 'access')" "FAIL"
    fi
fi

# 4. Authenticated API call
echo "[4/8] Authenticated API"
if [ -n "$TOKEN" ]; then
    CONNS=$(curl -sf http://localhost/api/v1/connections/ \
        -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo '{"error":"FAIL"}')
    if echo "$CONNS" | grep -q '"connections"'; then
        check "GET /connections/ with Bearer token" "PASS"
    else
        check "GET /connections/ with Bearer token" "FAIL"
        echo "       Response: $CONNS"
    fi

    ME=$(curl -sf http://localhost/api/v1/auth/me \
        -H "Authorization: Bearer $TOKEN" 2>/dev/null || echo '{"error":"FAIL"}')
    if echo "$ME" | grep -q '"email"'; then
        check "GET /auth/me returns user profile" "PASS"
    else
        check "GET /auth/me returns user profile" "FAIL"
    fi
else
    check "Skipping authenticated tests (no token)" "FAIL"
fi

# 5. Database tables exist
echo "[5/8] Database Schema"
TABLES=$(docker compose exec -T db psql -U sbi_admin -d smart_bi_agent -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'" 2>/dev/null | tr -d ' ' || echo "0")
if [ "$TABLES" -gt "10" ] 2>/dev/null; then
    check "App database has $TABLES tables" "PASS"
else
    check "App database tables (got: $TABLES)" "FAIL"
fi

# 6. Novamart test data
echo "[6/8] Test Dataset (NovaMart)"
NOVAMART=$(docker compose exec -T db psql -U sbi_admin -d novamart -t -c "SELECT COUNT(*) FROM orders" 2>/dev/null | tr -d ' ' || echo "0")
if [ "$NOVAMART" -gt "1000" ] 2>/dev/null; then
    check "NovaMart orders table has $NOVAMART rows" "PASS"
else
    check "NovaMart not loaded (run the SQL script)" "WARN"
fi

# 7. Docker containers
echo "[7/8] Docker Containers"
for svc in sbi-backend sbi-frontend sbi-db sbi-redis sbi-nginx; do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$svc" 2>/dev/null || echo "missing")
    if [ "$STATUS" = "healthy" ]; then
        check "$svc: $STATUS" "PASS"
    elif [ "$STATUS" = "missing" ]; then
        # Frontend doesn't have healthcheck
        RUNNING=$(docker inspect --format='{{.State.Status}}' "$svc" 2>/dev/null || echo "not found")
        if [ "$RUNNING" = "running" ]; then
            check "$svc: running (no healthcheck)" "PASS"
        else
            check "$svc: $RUNNING" "FAIL"
        fi
    else
        check "$svc: $STATUS" "FAIL"
    fi
done

# 8. Frontend accessible
echo "[8/8] Frontend"
FRONTEND=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost/ 2>/dev/null || echo "000")
if [ "$FRONTEND" = "200" ]; then
    check "GET / returns 200 (React SPA)" "PASS"
else
    check "GET / returns $FRONTEND" "FAIL"
fi

# Summary
echo ""
echo "============================================="
echo "  Results: $PASS passed, $FAIL failed, $WARN warnings"
echo "============================================="

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "  ❌ SOME CHECKS FAILED — review the output above"
    echo ""
    exit 1
else
    echo ""
    echo "  ✅ ALL CHECKS PASSED — product is ready!"
    echo ""
    echo "  Open http://localhost in your browser"
    echo "  Login: admin@smartbi.com / Admin@123456!"
    echo ""
fi
