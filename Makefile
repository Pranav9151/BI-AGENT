# =============================================================================
# Smart BI Agent — Makefile
# =============================================================================

.PHONY: help setup dev prod down logs test lint audit migrate keys clean

# Default target
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
setup: ## First-time setup: generate keys, copy env, build containers
	@./scripts/setup.sh

keys: ## Generate RSA key pair for JWT RS256
	@./scripts/generate_keys.sh

env: ## Copy .env.example to .env (won't overwrite existing)
	@test -f .env || cp .env.example .env && echo "Created .env — edit it now"
	@test -f .env && echo ".env already exists — skipping"

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------
dev: ## Start all services in development mode (hot-reload)
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

dev-d: ## Start all services in development mode (detached)
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d

dev-ollama: ## Start with Ollama for air-gapped LLM testing
	docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile ollama up --build

# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------
prod: ## Start all services in production mode
	docker compose up --build -d

prod-ollama: ## Start production with Ollama
	docker compose --profile ollama up --build -d

# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------
down: ## Stop all services
	docker compose down

down-v: ## Stop all services and remove volumes (DESTRUCTIVE)
	docker compose down -v

logs: ## Tail all service logs
	docker compose logs -f

logs-backend: ## Tail backend logs only
	docker compose logs -f backend

logs-db: ## Tail database logs only
	docker compose logs -f db

restart-backend: ## Restart backend only
	docker compose restart backend

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
migrate: ## Run Alembic migrations
	docker compose exec backend alembic upgrade head

migrate-gen: ## Auto-generate new migration
	docker compose exec backend alembic revision --autogenerate -m "$(msg)"

migrate-down: ## Rollback one migration
	docker compose exec backend alembic downgrade -1

db-shell: ## Open psql shell
	docker compose exec db psql -U $${POSTGRES_USER:-sbi_admin} -d $${POSTGRES_DB:-smart_bi_agent}

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
redis-shell: ## Open Redis CLI (DB 0 — Cache)
	docker compose exec redis redis-cli -a $${REDIS_PASSWORD} -n 0

redis-security: ## Open Redis CLI (DB 1 — Security)
	docker compose exec redis redis-cli -a $${REDIS_PASSWORD} -n 1

redis-coord: ## Open Redis CLI (DB 2 — Coordination)
	docker compose exec redis redis-cli -a $${REDIS_PASSWORD} -n 2

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
test: ## Run all tests
	docker compose exec backend pytest -v --tb=short

test-security: ## Run security-critical tests only
	docker compose exec backend pytest -v -m security --tb=short

test-cov: ## Run tests with coverage
	docker compose exec backend pytest --cov=app --cov-report=html --cov-report=term-missing

test-fast: ## Run tests in parallel (skip slow)
	docker compose exec backend pytest -v -n auto -m "not slow" --tb=short

# ---------------------------------------------------------------------------
# Code Quality
# ---------------------------------------------------------------------------
lint: ## Run ruff linter
	cd backend && ruff check app/ tests/

lint-fix: ## Run ruff with auto-fix
	cd backend && ruff check app/ tests/ --fix

format: ## Format code with ruff
	cd backend && ruff format app/ tests/

typecheck: ## Run mypy type checking
	cd backend && mypy app/

# ---------------------------------------------------------------------------
# Security Audit
# ---------------------------------------------------------------------------
audit: ## Run pip-audit for known vulnerabilities
	cd backend && pip-audit

audit-fix: ## Run pip-audit and attempt to fix
	cd backend && pip-audit --fix

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
clean: ## Remove Python cache files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true

clean-all: clean down-v ## Remove everything: caches, containers, volumes
