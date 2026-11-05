.DEFAULT_GOAL := help
.PHONY: help setup lint test dev up down wipe logs demo costs eval-smoke eval-full

COMPOSE := docker compose --env-file .env --file deploy/compose.yaml
COMPOSE_DEV := $(COMPOSE) --file deploy/compose.dev.yaml

help: ## List the available targets
	@grep -E '^[a-z-]+( [a-z-]+)*:.*## ' Makefile | sed -E 's/:.*## /: /'

setup: ## Install dependencies and the git hooks
	uv sync
	npm --prefix web ci --no-fund --no-audit
	uv run pre-commit install

lint: ## Run every pre-commit hook on all tracked files
	uv run pre-commit run --all-files

test: ## Run the tests with the coverage gate
	uv run pytest
	npm --prefix web test

.env:
	cp .env.example .env

dev: .env ## Start the local stack with hot reload (add COMPOSE_PROFILES=auth,dashboards for more)
	uv run python scripts/colima_ready.py
	$(COMPOSE_DEV) up --build --detach --wait --renew-anon-volumes
	@echo "Web http://localhost:5173  API http://localhost:8000/docs"

up: .env ## Start the local stack from production images
	uv run python scripts/colima_ready.py
	$(COMPOSE) up --build --detach --wait
	@echo "Web http://localhost:5173  API http://localhost:8000/docs"

down: .env ## Stop the local stack and keep its data
	$(COMPOSE_DEV) --profile '*' down --remove-orphans

wipe: .env ## Stop the local stack and delete its data
	$(COMPOSE_DEV) --profile '*' down --remove-orphans --volumes

logs: .env ## Follow the local stack's logs
	$(COMPOSE_DEV) --profile '*' logs --follow

# These fail loudly until their task lands, so nothing can appear to pass by doing nothing.
costs: ## Cost ledger (arrives in M0-6)
	@echo "make $@ arrives in M0-6" >&2; exit 1

eval-smoke eval-full: ## Evaluation suites (arrive in V1-24)
	@echo "make $@ arrives in V1-24" >&2; exit 1

demo: ## Demo stack (arrives in V3-20)
	@echo "make $@ arrives in V3-20" >&2; exit 1
