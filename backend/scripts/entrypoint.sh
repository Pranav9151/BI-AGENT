#!/bin/bash
set -e

echo "============================================="
echo "  Smart BI Agent — Bootstrap"
echo "  Environment: ${APP_ENV:-production}"
echo "============================================="

# ── Step 1: Wait for PostgreSQL ──
echo "[1/4] Waiting for PostgreSQL..."
for i in $(seq 1 30); do
    if python -c "
from sqlalchemy import create_engine, text
import os
url = os.environ.get('DATABASE_URL','').replace('+asyncpg', '')
if not url:
    exit(1)
engine = create_engine(url)
with engine.connect() as conn:
    conn.execute(text('SELECT 1'))
" 2>/dev/null; then
        echo "  ✓ PostgreSQL is ready"
        break
    fi
    if [ "$i" = "30" ]; then
        echo "  ⚠ PostgreSQL not ready after 30s — starting anyway"
    fi
    sleep 1
done

# ── Step 2: Run Alembic Migrations ──
echo "[2/4] Running database migrations..."
if alembic upgrade head 2>&1; then
    echo "  ✓ Migrations complete"
else
    echo "  ⚠ Migration failed — tables may already exist"
fi

# ── Step 3: Seed Admin User ──
if [ -n "$ADMIN_EMAIL" ] && [ -n "$ADMIN_PASSWORD" ]; then
    echo "[3/4] Seeding admin user..."
    python scripts/create_admin.py 2>&1 || echo "  ⚠ Admin seed skipped (may already exist)"
else
    echo "[3/4] Skipping admin seed (ADMIN_EMAIL/ADMIN_PASSWORD not set)"
fi

# ── Step 4: Start Uvicorn ──
echo "[4/4] Starting uvicorn (workers=${APP_WORKERS:-4})..."
echo "============================================="

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${APP_WORKERS:-4}" \
    --log-level "${LOG_LEVEL:-info}"
