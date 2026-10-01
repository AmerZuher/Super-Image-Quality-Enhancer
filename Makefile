# SIQE Studio developer commands. `make help` lists them.
SHELL := /bin/bash
COMPOSE := docker compose
GPU := -f compose.yaml -f compose.gpu.yaml
DEV := -f compose.yaml -f compose.dev.yaml

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this list
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.env:
	@cp .env.example .env
	@pw=$$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))'); \
	  sed -i.bak "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$$pw/" .env && rm -f .env.bak
	@echo "Created .env with a random database password."

.PHONY: env
env: .env ## Create .env from .env.example with a generated password

# --- Run ----------------------------------------------------------------------------
.PHONY: up
up: .env ## Build and start everything (CPU)
	$(COMPOSE) up -d --build
	@echo "SIQE Studio: http://localhost:$${SIQE_PORT:-8080}"

.PHONY: up-gpu
up-gpu: .env ## Build and start everything with the NVIDIA GPU
	$(COMPOSE) $(GPU) up -d --build
	@echo "SIQE Studio: http://localhost:$${SIQE_PORT:-8080}"

.PHONY: pull
pull: .env ## Start from published release images instead of building
	$(COMPOSE) pull
	$(COMPOSE) up -d --no-build

.PHONY: ops
ops: ## Also start the Temporal UI on http://localhost:8233
	$(COMPOSE) --profile ops up -d temporal-ui

.PHONY: down
down: ## Stop everything (data is kept)
	$(COMPOSE) --profile ops down

.PHONY: logs
logs: ## Follow logs from all services
	$(COMPOSE) logs -f --tail=100

.PHONY: ps
ps: ## Show service status
	$(COMPOSE) ps

# --- Develop --------------------------------------------------------------------------
.PHONY: install
install: ## Install backend and frontend dependencies locally
	cd backend && uv sync
	cd frontend && pnpm install

.PHONY: dev-services
dev-services: .env ## Start only PostgreSQL and Temporal, published on localhost
	$(COMPOSE) $(DEV) up -d db temporal-schema temporal

.PHONY: dev
dev: ## Run API, workers and Vite locally with hot reload (needs dev-services)
	./scripts/dev.sh

.PHONY: gen-api
gen-api: ## Regenerate the frontend API client from the backend's OpenAPI schema
	cd backend && uv run siqe openapi > ../frontend/openapi.json
	cd frontend && pnpm gen:api

# --- Quality ----------------------------------------------------------------------------
.PHONY: lint
lint: ## Lint and type-check backend and frontend
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd frontend && pnpm lint && pnpm typecheck

.PHONY: format
format: ## Auto-format backend and frontend
	cd backend && uv run ruff check --fix . && uv run ruff format .
	cd frontend && pnpm format

.PHONY: test
test: ## Unit tests (no running stack needed)
	cd backend && uv run pytest
	cd frontend && pnpm test

.PHONY: test-integration
test-integration: ## API integration tests against the running stack
	cd backend && uv run pytest -m integration

.PHONY: e2e
e2e: ## Browser tests against the running stack
	cd frontend && pnpm e2e

.PHONY: gallery
gallery: ## Capture README screenshots into gallery/ (stack must be running)
	cd frontend && pnpm gallery

.PHONY: check
check: lint test ## Everything CI runs before building images
