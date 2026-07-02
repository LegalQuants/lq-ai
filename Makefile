# LQ.AI — top-level Makefile
#
# Conventional targets per CONTRIBUTING.md and M1-IMPLEMENTATION-ORDER A1:
#   install   — install Python and Node dev dependencies
#   test      — run unit + integration tests (skips provider-marked)
#   lint      — ruff check + mypy on Python; eslint on web
#   format    — ruff format + prettier
#   migrate   — run Alembic migrations against the configured DB
#   run-dev   — bring up the dev stack via docker compose
#   clean     — tear down dev stack and remove caches
#   help      — print this help
#
# Targets that operate on a specific subsystem prefix the name:
#   api-test, gateway-test, web-test, api-lint, etc.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ANSI styling for help output
BLUE := \033[34m
RESET := \033[0m

.PHONY: help
help:
	@printf '\n  %bLQ.AI — Make targets%b\n\n' '$(BLUE)' '$(RESET)'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[34m%-18s\033[0m %s\n", $$1, $$2}'
	@printf '\n'

# ---------- Top-level orchestration ----------

.PHONY: install
install: install-api install-gateway install-web ## Install all subsystem dependencies

.PHONY: test
test: api-test gateway-test ## Run unit + integration tests (skip provider-marked)

.PHONY: lint
lint: api-lint gateway-lint ## Run ruff + mypy on Python subsystems

.PHONY: format
format: api-format gateway-format ## Apply ruff format to Python subsystems

.PHONY: format-check
format-check: api-format-check gateway-format-check ## Verify code is ruff-formatted (CI use)

.PHONY: run-dev
run-dev: ## Bring up the dev stack via docker compose
	docker compose up -d
	@echo ""
	@echo "  Services starting. Watch readiness with:"
	@echo "    docker compose ps"
	@echo "    docker compose logs -f"
	@echo ""

.PHONY: stop-dev
stop-dev: ## Stop the dev stack (preserves volumes)
	docker compose down

.PHONY: clean
clean: ## Tear down dev stack, volumes, and caches
	docker compose down -v
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name .ruff_cache -prune -exec rm -rf {} +
	find . -type d -name .mypy_cache -prune -exec rm -rf {} +

.PHONY: migrate
migrate: ## Run Alembic migrations against the running api container
	docker compose exec api alembic upgrade head

.PHONY: migrate-down
migrate-down: ## Roll back one migration in the running api container
	docker compose exec api alembic downgrade -1

.PHONY: migrate-status
migrate-status: ## Show current migration head in the running api container
	docker compose exec api alembic current

.PHONY: migrate-create
migrate-create: ## Create a new migration from model diffs. Pass MSG="..."
	@if [ -z "$(MSG)" ]; then echo "Usage: make migrate-create MSG=\"description\""; exit 1; fi
	docker compose exec api alembic revision --autogenerate -m "$(MSG)"

.PHONY: psql
psql: ## Open a psql shell against the dev database
	docker compose exec postgres psql -U $${POSTGRES_USER:-lq_ai} -d $${POSTGRES_DB:-lq_ai}

# ---------- api/ ----------

.PHONY: install-api
install-api:
	cd api && python -m venv .venv && \
		.venv/bin/pip install --upgrade pip && \
		.venv/bin/pip install -e ".[dev]"

.PHONY: api-test
api-test:
	cd api && .venv/bin/pytest -m "not provider and not slow"

.PHONY: api-test-all
api-test-all:
	cd api && .venv/bin/pytest

.PHONY: api-lint
api-lint:
	cd api && .venv/bin/ruff check . && .venv/bin/mypy app

.PHONY: api-format
api-format:
	cd api && .venv/bin/ruff format .

.PHONY: api-format-check
api-format-check:
	cd api && .venv/bin/ruff format --check .

.PHONY: openapi
openapi: ## Regenerate docs/api/backend-openapi.generated.yaml from the live app (DE-373)
	api/.venv/bin/python scripts/gen_openapi.py

# ---------- gateway/ ----------

.PHONY: install-gateway
install-gateway:
	cd gateway && python -m venv .venv && \
		.venv/bin/pip install --upgrade pip && \
		.venv/bin/pip install -e ".[dev]"

.PHONY: gateway-test
gateway-test:
	cd gateway && .venv/bin/pytest -m "not provider and not slow"

.PHONY: gateway-test-all
gateway-test-all:
	cd gateway && .venv/bin/pytest

.PHONY: gateway-lint
gateway-lint:
	cd gateway && .venv/bin/ruff check . && .venv/bin/mypy app

.PHONY: gateway-format
gateway-format:
	cd gateway && .venv/bin/ruff format .

.PHONY: gateway-format-check
gateway-format-check:
	cd gateway && .venv/bin/ruff format --check .

# ---------- web/ ----------
# Lands when OpenWebUI fork is imported in A1.d.

.PHONY: install-web
install-web:
	@if [ -f web/package.json ]; then \
		cd web && npm install; \
	else \
		echo "web/ not yet imported (Task A1.d)."; \
	fi

.PHONY: web-test
web-test:
	@if [ -f web/package.json ]; then \
		cd web && npm test; \
	else \
		echo "web/ not yet imported (Task A1.d)."; \
	fi

.PHONY: web-lint
web-lint:
	@if [ -f web/package.json ]; then \
		cd web && npm run lint; \
	else \
		echo "web/ not yet imported (Task A1.d)."; \
	fi

# ----------------------------------------------------------------------
# Release-readiness (Phase E)
# ----------------------------------------------------------------------

.PHONY: release-dryrun
release-dryrun:
	@echo "Trigger the release workflow on workflow_dispatch with dry_run=true to test locally."
	@echo "gh workflow run release.yml -f dry_run=true"

.PHONY: helm-lint
helm-lint:
	helm lint deploy/helm/lq-ai

.PHONY: helm-template
helm-template:
	helm template lq-ai deploy/helm/lq-ai \
		--values deploy/helm/lq-ai/values-example.yaml

.PHONY: sbom
sbom:
	@mkdir -p artifacts/sbom
	syft scan dir:./api -o spdx-json=artifacts/sbom/api.spdx.json
	syft scan dir:./gateway -o spdx-json=artifacts/sbom/gateway.spdx.json
	syft scan dir:./web -o spdx-json=artifacts/sbom/web.spdx.json
	@echo "SBOMs written to artifacts/sbom/*.spdx.json"
