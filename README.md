# Smart BI Agent v3.1

**AI-powered Business Intelligence platform** — Ask questions in plain English, get instant SQL-backed answers with insights, charts, and reports.

Architecture v3.1 | 57 threats identified, 55 resolved (96.5%) | Production-ready security

---

## Quick Start

```bash
git clone <repo-url> smart-bi-agent
cd smart-bi-agent
./scripts/setup.sh
```

That's it. `setup.sh` handles everything: environment config, JWT key generation, Docker build, database migration, and admin account creation.

---

## Architecture Overview

| Layer | Components | Security Controls |
|-------|-----------|-------------------|
| Client | React SPA, Notification Platforms, REST API | JWT in memory, CSP, no innerHTML, auto-clear |
| Edge | Nginx, TLS 1.3 | HSTS, limit_conn:500, Ollama blocked, login rate limit |
| API Gateway | FastAPI, Middleware Stack | CORS whitelist, rate limits, RS256, lockout, req logging |
| Application | Routes, Pydantic validation | TOTP admin, IDOR checks, closed registration |
| AI Processing | Multi-LLM BYOK, Prompt Guard | Sanitized schema, token budget, fallback chain |
| Query Processing | SQL Validator (10-step), Executor | Dialect blocklists, DNS-pinned SSRF, 50MB limit |
| Data | PostgreSQL 16, Redis (segmented) | HKDF encryption, 3 Redis DBs, hash-chained audit |
| Security | Key Manager, Auth, IAM, SSRF Guard | Cross-cutting, fail-closed |
| Observability | Structlog, Prometheus, Audit | Redacted logs, SIEM shipping |
| Infrastructure | Docker Compose, CI/CD | Pinned deps, Ollama lockdown, daily backups |

---

## Developer Commands

```bash
make help              # Show all commands
make dev               # Start development (hot-reload)
make test              # Run all tests
make test-security     # Run security tests only
make lint              # Check code quality
make migrate           # Run database migrations
make db-shell          # Open PostgreSQL shell
make audit             # Check dependencies for vulnerabilities
```

---

## VS Code IDE Setup Guide

This section explains exactly how to set up your development environment in VS Code and how to implement code effectively for this project.

### Step 1: Open the Workspace

The project includes a VS Code workspace file that gives you a clean multi-root view:

```
File → Open Workspace from File → select smart-bi-agent.code-workspace
```

This opens three root folders in your sidebar:
- **Smart BI Agent** — the full project (Docker, configs, scripts)
- **Backend (Python)** — FastAPI application code
- **Frontend (React)** — React SPA code

### Step 2: Install Recommended Extensions

VS Code will prompt you to install recommended extensions. Click **Install All**. These are:

| Extension | Purpose |
|-----------|---------|
| **Python** + **Pylance** | Python IntelliSense, type checking, auto-imports |
| **Ruff** | Linting + formatting (replaces black, isort, flake8) |
| **Mypy** | Static type checking |
| **Docker** | Dockerfile/compose syntax, container management |
| **ESLint** | TypeScript/React linting |
| **Tailwind CSS IntelliSense** | Class autocomplete in JSX |
| **Prettier** | Frontend code formatting |
| **Error Lens** | Inline error display (see issues immediately) |
| **GitLens** | Git blame, history, authorship |
| **SQLTools + PostgreSQL** | DB browser and query runner |

### Step 3: Configure Python Environment

Two options for Python development:

**Option A: Local Python (Recommended for Speed)**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate       # Linux/Mac
# .venv\Scripts\activate        # Windows
pip install -e ".[dev]"
```

In VS Code: `Cmd/Ctrl+Shift+P` → "Python: Select Interpreter" → choose `.venv`

**Option B: Docker Only (No local Python)**

All commands run inside Docker:
```bash
make dev-d                                    # Start services
docker compose exec backend pytest -v         # Run tests
docker compose exec backend ruff check app/   # Lint
```

### Step 4: Using VS Code Tasks (One-Click Commands)

Instead of typing terminal commands, use VS Code's Task Runner:

```
Cmd/Ctrl+Shift+P → "Tasks: Run Task" → pick from list
```

Or use the keyboard shortcut:
```
Cmd/Ctrl+Shift+B → select a task
```

Available tasks include:
- 🚀 Dev: Start All Services
- 🧪 Test: Run All / Security Only / With Coverage
- 🔍 Lint: Check / Auto-Fix
- 🗃️ DB: Run Migrations / Generate Migration / Open Shell
- 📋 Logs: Backend
- 🔐 Security: Audit Dependencies

### Step 5: Debugging

The project includes pre-configured debug configurations. Use the **Run and Debug** panel (`Cmd/Ctrl+Shift+D`):

| Configuration | What it does |
|--------------|-------------|
| **Backend: FastAPI** | Runs uvicorn with debugger attached. Set breakpoints anywhere. |
| **Backend: Current Test File** | Debug the test file you currently have open |
| **Backend: All Security Tests** | Debug all `@pytest.mark.security` tests |
| **Frontend: Chrome** | Launch Chrome with debugger for React |
| **Docker: Attach to Backend** | Attach debugger to running Docker container |
| **Full Stack** | Launch backend + frontend together |

**Setting breakpoints:** Click the left gutter next to any line number. A red dot appears. When that code executes, VS Code pauses and shows you variables, call stack, etc.

### Step 6: The Development Workflow

Here's the exact workflow for implementing a new component:

#### 1. Check the architecture docs first

Open the architecture files (they're in the repo root) and find the component specification:
- `FINAL-Architecture-v3_1-Production-Ready.md` — security controls and schema
- `architecture-v2-1.md` — implementation details and code patterns

#### 2. Create the file in the right location

Follow the folder structure exactly:
```
backend/app/
├── security/       ← Security components (key_manager, auth, ssrf_guard, etc.)
├── models/         ← SQLAlchemy ORM models (users, connections, etc.)
├── schemas/        ← Pydantic request/response schemas
├── api/v1/         ← FastAPI route handlers
├── core/           ← Business logic (schema_reader, sql_validator, etc.)
├── llm/            ← LLM provider adapters
├── db/             ← Database session, Redis client
├── errors/         ← Exception classes and handlers
├── logging/        ← Structlog config, audit writer
├── notifications/  ← Notification provider adapters
├── prompts/        ← LLM prompt templates
├── scheduler/      ← APScheduler jobs
└── services/       ← Cross-cutting services
```

#### 3. Write the code

Example: creating `security/key_manager.py`

```
Cmd/Ctrl+N  → New file
Cmd/Ctrl+S  → Save as backend/app/security/key_manager.py
```

Write the implementation following v3.1 specs. Use type hints everywhere.

#### 4. Write tests alongside

For every `app/security/foo.py`, create `tests/test_foo.py`:
```
backend/tests/test_key_manager.py
```

Run your test immediately:
- Press `F5` with the test file open (uses "Current Test File" debug config)
- Or: `Cmd/Ctrl+Shift+P` → "Tasks: Run Task" → "🧪 Test: Run All"

#### 5. Check code quality before committing

```bash
make lint          # Ruff checks
make typecheck     # Mypy checks
make test          # All tests pass
make audit         # No known vulnerabilities
```

Or use VS Code tasks for any of these.

### Step 7: Connecting to Services for Debugging

**PostgreSQL Browser:**
1. Install SQLTools + PostgreSQL extension
2. Create connection: host=`localhost`, port=`5432`, user=`sbi_admin`, database=`smart_bi_agent`
3. Browse tables, run queries, inspect data

**Redis Inspector:**
Use the terminal:
```bash
make redis-shell      # DB 0 — Cache
make redis-security   # DB 1 — Security
make redis-coord      # DB 2 — Coordination
```

**Docker Logs:**
```bash
make logs-backend     # Or use the VS Code task
```

### Step 8: Git Workflow

```bash
git checkout -b phase1/key-manager      # Feature branch per component
# ... implement ...
make lint && make test                   # Quality gates
git add -A && git commit -m "feat(security): implement HKDF key manager with versioning"
git push origin phase1/key-manager
# Create PR → review → merge to main
```

Branch naming convention:
```
phase1/component-name     (e.g., phase1/key-manager, phase1/ssrf-guard)
fix/issue-description      (e.g., fix/redis-connection-timeout)
```

### Keyboard Shortcuts Cheat Sheet

| Shortcut | Action |
|----------|--------|
| `Cmd/Ctrl+Shift+P` | Command palette (find anything) |
| `Cmd/Ctrl+Shift+B` | Run build task |
| `F5` | Start debugging |
| `F9` | Toggle breakpoint |
| `Cmd/Ctrl+P` | Quick file open |
| `Cmd/Ctrl+Shift+F` | Search across all files |
| `Cmd/Ctrl+\`` | Toggle terminal |
| `Cmd/Ctrl+Shift+E` | File explorer |
| `Cmd/Ctrl+Shift+D` | Debug panel |
| `Cmd/Ctrl+Shift+G` | Git panel |

---

## Project Structure

```
smart-bi-agent/
├── docker-compose.yml           # All services
├── docker-compose.dev.yml       # Dev overrides (hot-reload, ports)
├── Dockerfile.backend           # Multi-stage backend build
├── Dockerfile.frontend          # Multi-stage frontend build
├── pyproject.toml               # Python dependencies (all pinned)
├── Makefile                     # Developer commands
├── .env.example                 # Environment template
├── models.lock                  # Ollama model SHA256 pinning (T33)
├── smart-bi-agent.code-workspace # VS Code workspace
├── nginx/                       # Edge layer config
├── scripts/                     # Setup and utility scripts
├── keys/                        # JWT RSA keys (gitignored)
├── docs/                        # Architecture documents
├── backend/
│   ├── app/                     # FastAPI application
│   │   ├── config.py            # Pydantic Settings
│   │   ├── main.py              # App factory
│   │   ├── security/            # All security components
│   │   ├── models/              # SQLAlchemy models
│   │   ├── schemas/             # Pydantic schemas
│   │   ├── api/v1/              # Route handlers
│   │   ├── core/                # Business logic
│   │   ├── llm/                 # LLM providers
│   │   ├── db/                  # Database + Redis
│   │   ├── errors/              # Exceptions
│   │   ├── logging/             # Structlog + Audit
│   │   ├── notifications/       # Notification providers
│   │   ├── prompts/             # LLM prompt templates
│   │   └── scheduler/           # APScheduler
│   ├── alembic/                 # Database migrations
│   ├── tests/                   # Test suite
│   └── scripts/                 # Admin scripts
└── frontend/
    └── src/                     # React application
```

---

## Security Architecture

57 threats identified across 3 analysis rounds. 55 resolved at the architecture level (96.5%).

**Key security decisions:**
- HKDF key hierarchy (not single Fernet) — T1
- Redis segmented 3 DBs (cache/security/coordination) — T12
- DNS-pinned SSRF guard — T51
- TOTP required for admin accounts — T8
- Security enforced in code, never in LLM prompts — T35
- Ollama localhost-only, pinned, pulls disabled — T32, T33

See `FINAL-Architecture-v3_1-Production-Ready.md` for the complete threat register.

---

## License

Proprietary — All rights reserved.
