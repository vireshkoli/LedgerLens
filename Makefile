.DEFAULT_GOAL := help
.PHONY: help setup lint test dev up down demo costs eval-smoke eval-full

help: ## List the available targets
	@grep -E '^[a-z-]+( [a-z-]+)*:.*## ' Makefile | sed -E 's/:.*## /: /'

setup: ## Install dependencies and the git hooks
	uv sync
	uv run pre-commit install

lint: ## Run every pre-commit hook on all tracked files
	uv run pre-commit run --all-files

test: ## Run the tests with the coverage gate
	uv run pytest

# These fail loudly until their task lands, so nothing can appear to pass by doing nothing.
dev up down: ## Local stack (arrives in M0-2)
	@echo "make $@ arrives in M0-2" >&2; exit 1

costs: ## Cost ledger (arrives in M0-6)
	@echo "make $@ arrives in M0-6" >&2; exit 1

eval-smoke eval-full: ## Evaluation suites (arrive in V1-24)
	@echo "make $@ arrives in V1-24" >&2; exit 1

demo: ## Demo stack (arrives in V3-20)
	@echo "make $@ arrives in V3-20" >&2; exit 1
